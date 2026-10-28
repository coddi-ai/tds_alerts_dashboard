"""
Informe preliminar de fallas: lectura de la capa golden del Predictivo, desde la copia local o desde S3.

El origen se elige con INFORME_FALLA_ORIGEN (config.py):
- "local" (por defecto): la copia local en data/, la misma que lee el dashboard. El informe muestra
  exactamente lo que ve el cliente en la plataforma.
- "s3": el origen de los datos (predictive_data_contracts.md, "Storage Location"):
      s3://{bucket}/MultiTechnique Alerts/{tecnica}/golden/{cliente}/{componente}/{tabla}/year=YYYY/week=WW/*.parquet
  con el bucket de ERS_S3_BUCKET y las credenciales de AWS del entorno (variables AWS_* o el rol de la
  maquina). Siempre trae lo ultimo, pero puede adelantarse a la copia local del dashboard.

Con los dos origenes, unit_status_summary y risk_scores se leen solo en las semanas del informe
(particiones_entre): listar la tabla entera es lo lento, no leerla.

Las particiones son ISO year/week (lunes a domingo). Se leen archivo por archivo: una columna toda vacia
en una semana no debe romper la lectura conjunta, y asi se conservan los metadatos del parquet (la curva
acumulada guarda ahi la configuracion de sus zonas).
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from functools import lru_cache
from typing import List, Optional, Tuple

import pandas as pd
import pyarrow as pa
import pyarrow.fs as pafs
import pyarrow.parquet as pq

from src.informe_falla import catalog as c
from src.informe_falla.config import get_informe_settings
from src.utils.logger import get_logger

logger = get_logger(__name__)

ORIGEN_LOCAL, ORIGEN_S3 = "local", "s3"
# Una particion publicada cuelga DIRECTAMENTE de la tabla: <tabla>/year=YYYY/week=WW/<archivo>.parquet.
# Asi quedan fuera las corridas en preparacion (_staging/, _runs/<id>/) y cualquier otra subcarpeta.
_PARTICION = re.compile(r"^year=(\d+)/week=(\d+)/([^/]+\.parquet)$")


def origen() -> str:
    return get_informe_settings().origen


@lru_cache(maxsize=8)
def _region_del_bucket(bucket: str) -> Optional[str]:
    """La region real del bucket. Conectarse con otra region responde HTTP 301 (PermanentRedirect)."""
    try:
        return pafs.resolve_s3_region(bucket)
    except Exception as exc:
        logger.warning(f"No se pudo consultar la region del bucket {bucket} ({type(exc).__name__}: {exc}); "
                       "definala en INFORME_FALLA_S3_REGION")
        return None


def _filesystem() -> Tuple[pafs.FileSystem, str]:
    """(sistema de archivos, raiz de la capa golden) segun el origen configurado."""
    ajustes = get_informe_settings()
    if ajustes.origen == ORIGEN_S3:
        if not ajustes.s3_bucket:
            raise RuntimeError("INFORME_FALLA_ORIGEN=s3 requiere el bucket en ERS_S3_BUCKET")
        region = ajustes.s3_region or _region_del_bucket(ajustes.s3_bucket)
        fs = pafs.S3FileSystem(region=region) if region else pafs.S3FileSystem()
        return fs, f"{ajustes.s3_bucket}/{ajustes.s3_prefix}".rstrip("/")
    return pafs.LocalFileSystem(), str(ajustes.data_dir.resolve())


def _ruta_tabla(raiz: str, cliente: str, tabla: str, tecnica: str) -> str:
    return f"{raiz}/{tecnica}/golden/{cliente.lower()}/{c.COMPONENTE}/{tabla}"


def _archivo_canonico(tabla: str, nombres: List[str]) -> Optional[str]:
    """El archivo publicado de una semana. El contrato lo llama <tabla>.parquet o part-0.parquet; las
    copias con sufijo (_old, _v2, ...) no son la version publicada y se ignoran."""
    for preferido in (f"{tabla}.parquet", "part-0.parquet"):
        if preferido in nombres:
            return preferido
    return nombres[0] if len(nombres) == 1 else None


def particiones(cliente: str, tabla: str, tecnica: str = "predictive") -> List[Tuple[int, int, str]]:
    """[(year, week, ruta del archivo publicado)] de la tabla, una por semana, ordenadas. Vacio si no existe."""
    fs, raiz = _filesystem()
    base = _ruta_tabla(raiz, cliente, tabla, tecnica)
    try:
        archivos = fs.get_file_info(pafs.FileSelector(base, recursive=True, allow_not_found=True))
    except OSError as exc:
        # En S3 un error al listar es de acceso (region, credenciales, permisos, red), no falta de datos:
        # se propaga para que el servicio lo informe como "data_source" y no como "no_data".
        if origen() == ORIGEN_S3:
            raise RuntimeError(f"No se pudo leer {tabla} en S3 ({base}): {exc}") from exc
        logger.warning(f"{tabla} {cliente}: no se pudo listar {base} ({type(exc).__name__}: {exc})")
        return []
    base_normal = base.replace("\\", "/").rstrip("/") + "/"
    por_semana: dict = {}
    for info in archivos:
        ruta = info.path.replace("\\", "/")
        m = _PARTICION.match(ruta[len(base_normal):]) if ruta.startswith(base_normal) else None
        if info.type == pafs.FileType.File and m:
            por_semana.setdefault((int(m.group(1)), int(m.group(2))), {})[m.group(3)] = info.path
    salida = []
    for (year, week), archivos_semana in sorted(por_semana.items()):
        elegido = _archivo_canonico(tabla, sorted(archivos_semana))
        if elegido is None:
            logger.warning(f"{tabla} {cliente} {year}-W{week:02d}: varios archivos y ninguno canónico "
                           f"({', '.join(sorted(archivos_semana))}); se omite la semana")
            continue
        salida.append((year, week, archivos_semana[elegido]))
    return salida


def _carpetas(fs: pafs.FileSystem, ruta: str) -> List[str]:
    """Nombres de las subcarpetas directas de `ruta` (vacio si no existe)."""
    try:
        infos = fs.get_file_info(pafs.FileSelector(ruta, recursive=False, allow_not_found=True))
    except OSError:
        return []
    return [i.base_name for i in infos if i.type == pafs.FileType.Directory]


def particiones_entre(cliente: str, tabla: str, desde: date, hasta: date,
                      tecnica: str = "predictive") -> List[Tuple[int, int, str]]:
    """Como `particiones`, pero solo las semanas cuyo lunes cae entre `desde` y `hasta`, listando solo esas
    carpetas: recorrer toda la tabla (cientos de semanas mas _staging/ y _runs/) es lo que mas tarda,
    sobre todo en S3 y en el volumen montado de Docker."""
    fs, raiz = _filesystem()
    base = _ruta_tabla(raiz, cliente, tabla, tecnica)
    salida = []
    for carpeta_year in _carpetas(fs, base):
        m_year = re.fullmatch(r"year=(\d+)", carpeta_year)
        if not m_year or not desde.isocalendar()[0] - 1 <= int(m_year.group(1)) <= hasta.isocalendar()[0]:
            continue
        year = int(m_year.group(1))
        for carpeta_week in _carpetas(fs, f"{base}/{carpeta_year}"):
            m_week = re.fullmatch(r"week=(\d+)", carpeta_week)
            if not m_week:
                continue
            week = int(m_week.group(1))
            try:
                lunes = date.fromisocalendar(year, week, 1)
            except ValueError:
                continue
            if not desde <= lunes <= hasta:
                continue
            ruta_semana = f"{base}/{carpeta_year}/{carpeta_week}"
            infos = fs.get_file_info(pafs.FileSelector(ruta_semana, recursive=False, allow_not_found=True))
            archivos = {i.base_name: i.path for i in infos
                        if i.type == pafs.FileType.File and i.base_name.endswith(".parquet")}
            elegido = _archivo_canonico(tabla, sorted(archivos))
            if elegido is None:
                if archivos:
                    logger.warning(f"{tabla} {cliente} {year}-W{week:02d}: varios archivos y ninguno canónico "
                                   f"({', '.join(sorted(archivos))}); se omite la semana")
                continue
            salida.append((year, week, archivos[elegido]))
    return sorted(salida)


def leer_archivo(ruta: str) -> pa.Table:
    """Un archivo parquet, con sus metadatos. Se abre como archivo suelto: con la ruta, pyarrow deduce
    year/week de las carpetas y choca con las columnas year/week que el archivo ya trae."""
    fs, _ = _filesystem()
    with fs.open_input_file(ruta) as archivo:
        return pq.read_table(archivo)


def leer_particiones(cliente: str, tabla: str, desde: Optional[date] = None, hasta: Optional[date] = None,
                     tecnica: str = "predictive") -> pd.DataFrame:
    """Las particiones cuya semana empieza entre `desde` y `hasta` (lunes, inclusive), con year y week."""
    partes = []
    semanas = (particiones_entre(cliente, tabla, desde, hasta, tecnica) if desde and hasta
               else particiones(cliente, tabla, tecnica))
    for year, week, ruta in semanas:
        lunes = date.fromisocalendar(year, week, 1)
        if (desde and lunes < desde) or (hasta and lunes > hasta):
            continue
        try:
            df = leer_archivo(ruta).to_pandas()
        except Exception as exc:
            logger.warning(f"{tabla} {cliente}: no se pudo leer {ruta} ({type(exc).__name__}: {exc})")
            continue
        df["year"], df["week"] = year, week
        partes.append(df)
    return pd.concat(partes, ignore_index=True) if partes else pd.DataFrame()


def semanas_del_informe(fecha) -> Tuple[date, date]:
    """(desde, hasta): lunes de las semanas que usa el informe de una detencion, con una de margen."""
    f = pd.Timestamp(fecha).date()
    lunes = f - timedelta(days=f.weekday())
    return lunes - timedelta(weeks=c.SEMANAS_ATRAS + 1), lunes