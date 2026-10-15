"""
Catalogo de reportes generados que viven en S3 (pestaña Reportes > Reportabilidad).

Estructura en el bucket, una carpeta por cliente en minusculas y una por lote:

    {REPORTS_S3_ROOT}/{cliente}/reports/{yyyy-mm-dd}/{archivo}

Por ahora solo hay informes predictivos:

    informe_predictivo_{unidad}_{yyyymmdd}[_{nn}].pdf               -> motor
    informe_predictivo_{unidad}_transmision_{yyyymmdd}[_{nn}].pdf   -> transmision

La unidad puede traer `_` o `-` (`t_10`, `ca-30`), por eso el nombre se lee con
una expresion y no partiendo por `_`. El sufijo `_{nn}` aparece cuando un informe
se regenera el mismo dia; se guarda como `version`.

Las credenciales se quedan en el servidor: este modulo lista y lee los objetos, y
la ruta Flask de dashboard/report_files.py es la unica que entrega bytes al
navegador. La pagina solo conoce claves relativas (`fecha/archivo`).

Configuracion por entorno (mismas variables que el resto de la integracion S3):
BUCKET_NAME, ACCESS_KEY, SECRET_KEY; sin llaves se usa la cadena estandar de AWS
(rol IAM en el despliegue). REPORTS_S3_ROOT (por defecto `test_chatbot`) y
REPORTS_CACHE_SECONDS (por defecto 300) ajustan la raiz y la vida del listado.
"""

from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional, Tuple

from dotenv import load_dotenv

from src.utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_ROOT = "test_chatbot"
DEFAULT_CACHE_SECONDS = 300

TECHNIQUE_PREDICTIVE = "predictivo"
SYSTEM_MOTOR = "motor"
SYSTEM_TRANSMISSION = "transmision"

# Tecnica -> sistemas que puede traer. El orden manda en la interfaz.
TECHNIQUE_SYSTEMS: Dict[str, Tuple[str, ...]] = {
    TECHNIQUE_PREDICTIVE: (SYSTEM_MOTOR, SYSTEM_TRANSMISSION),
}

_DATE_FOLDER = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_PREDICTIVE_FILE = re.compile(
    r"^informe_predictivo_(?P<unit>[a-z0-9][a-z0-9_\-]*?)"
    r"(?:_(?P<system>transmision))?"
    r"_(?P<stamp>\d{8})(?:_(?P<version>\d{1,3}))?\.pdf$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ReportEntry:
    """Un reporte del bucket. `key` es relativa a la carpeta reports/ del cliente."""

    key: str
    filename: str
    technique: str
    system: str
    unit: str
    date: str
    version: int = 0
    size: int = 0
    last_modified: str = ""

    def to_record(self) -> dict:
        return asdict(self)


def parse_report_key(key: str) -> Optional[ReportEntry]:
    """
    Interpreta `yyyy-mm-dd/archivo` o devuelve None si no es un reporte conocido.

    Es tambien la validacion de la ruta de descarga: nada que no pase por aqui
    se pide a S3, asi que no hay forma de salir de la carpeta del cliente.
    """
    parts = str(key or "").split("/")
    if len(parts) != 2:
        return None
    folder, filename = parts
    if not _DATE_FOLDER.match(folder):
        return None
    match = _PREDICTIVE_FILE.match(filename)
    if not match:
        return None
    return ReportEntry(
        key=f"{folder}/{filename}",
        filename=filename,
        technique=TECHNIQUE_PREDICTIVE,
        system=(match.group("system") or SYSTEM_MOTOR).lower(),
        unit=match.group("unit").upper(),
        # La carpeta es el lote de generacion; manda sobre el sello del nombre.
        date=folder,
        version=int(match.group("version") or 0),
    )


def unit_sort_key(unit: str) -> tuple:
    """Orden natural: T_9 antes que T_10."""
    return tuple(int(chunk) if chunk.isdigit() else chunk for chunk in re.split(r"(\d+)", unit or ""))


def latest_by_unit(entries: List[ReportEntry]) -> List[ReportEntry]:
    """El reporte mas reciente (fecha, luego version) por tecnica, sistema y unidad."""
    best: Dict[tuple, ReportEntry] = {}
    for entry in entries:
        slot = (entry.technique, entry.system, entry.unit)
        current = best.get(slot)
        if current is None or (entry.date, entry.version) > (current.date, current.version):
            best[slot] = entry
    return sorted(best.values(), key=lambda e: (e.technique, e.system, unit_sort_key(e.unit)))


class ReportNotFound(Exception):
    """La clave no existe en el bucket."""


class ReportStore:
    """Lista y abre los reportes de un cliente, con un cache corto del listado."""

    def __init__(self, bucket: str, s3_client, root: str = DEFAULT_ROOT,
                 cache_seconds: float = DEFAULT_CACHE_SECONDS,
                 clock: Callable[[], float] = time.monotonic):
        self.bucket = bucket
        self.root = root.strip("/")
        self.cache_seconds = cache_seconds
        self._s3 = s3_client
        self._clock = clock
        self._cache: Dict[str, Tuple[float, List[ReportEntry]]] = {}
        self._lock = threading.Lock()

    def client_prefix(self, client: str) -> str:
        return f"{self.root}/{str(client).strip().lower()}/reports/"

    def list_reports(self, client: str, refresh: bool = False) -> List[ReportEntry]:
        """Reportes del cliente, del lote mas nuevo al mas viejo."""
        client_key = str(client).strip().lower()
        if not client_key:
            return []
        now = self._clock()
        with self._lock:
            cached = self._cache.get(client_key)
        if cached and not refresh and now - cached[0] < self.cache_seconds:
            return cached[1]

        prefix = self.client_prefix(client_key)
        entries: List[ReportEntry] = []
        skipped = 0
        paginator = self._s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                parsed = parse_report_key(obj["Key"][len(prefix):])
                if parsed is None:
                    skipped += 1
                    continue
                modified = obj.get("LastModified")
                entries.append(replace(
                    parsed,
                    size=int(obj.get("Size", 0)),
                    last_modified=modified.isoformat() if modified else "",
                ))
        if skipped:
            logger.info(f"Reportes {client_key}: {skipped} objetos ignorados por nombre no reconocido")

        # Fecha descendente; dentro del lote, en el orden de la interfaz y unidad natural.
        order = {(tech, system): i for i, (tech, system) in enumerate(
            (tech, system) for tech, systems in TECHNIQUE_SYSTEMS.items() for system in systems)}
        entries.sort(key=lambda e: (order.get((e.technique, e.system), len(order)), unit_sort_key(e.unit), -e.version))
        entries.sort(key=lambda e: e.date, reverse=True)
        with self._lock:
            self._cache[client_key] = (now, entries)
        return entries

    def open_report(self, client: str, key: str) -> Tuple[Iterator[bytes], Optional[int]]:
        """Cuerpo del objeto en trozos y su largo. `key` debe venir validada."""
        if parse_report_key(key) is None:
            raise ValueError("clave de reporte invalida")
        full_key = self.client_prefix(client) + key
        try:
            obj = self._s3.get_object(Bucket=self.bucket, Key=full_key)
        except Exception as exc:  # botocore.ClientError sin importar botocore aqui
            code = getattr(exc, "response", {}).get("Error", {}).get("Code", "")
            if code in ("NoSuchKey", "404"):
                raise ReportNotFound(full_key) from exc
            raise
        length = obj.get("ContentLength")
        return obj["Body"].iter_chunks(64 * 1024), int(length) if length is not None else None


_store: Optional[ReportStore] = None
_store_lock = threading.Lock()


def get_report_store() -> Optional[ReportStore]:
    """Instancia del proceso, o None si no hay bucket configurado."""
    global _store
    with _store_lock:
        if _store is not None:
            return _store
        load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")
        bucket = os.getenv("BUCKET_NAME")
        if not bucket:
            logger.warning("Reportabilidad sin BUCKET_NAME: no se pueden listar reportes")
            return None

        import boto3

        access_key, secret_key = os.getenv("ACCESS_KEY"), os.getenv("SECRET_KEY")
        if access_key and secret_key:
            s3 = boto3.client("s3", aws_access_key_id=access_key, aws_secret_access_key=secret_key)
        else:
            s3 = boto3.client("s3")
        _store = ReportStore(
            bucket,
            s3,
            root=os.getenv("REPORTS_S3_ROOT", DEFAULT_ROOT),
            cache_seconds=float(os.getenv("REPORTS_CACHE_SECONDS", DEFAULT_CACHE_SECONDS)),
        )
        return _store
