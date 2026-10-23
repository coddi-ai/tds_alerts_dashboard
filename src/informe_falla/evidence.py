"""
Informe preliminar de falla, paso 1 (sin IA): la evidencia del Predictivo para una unidad y una fecha.

Score semanal (unit_status_summary): compara el ultimo mes de cada modo de falla contra
la propia unidad y contra la flota, y asigna un nivel por modo (alto, medio, bajo, ninguno).
Score diario (risk_scores): ubica el inicio de una señal en un dia, usa los dias de la
semana de la detencion anteriores a la fecha y reporta las brechas con fechas exactas.
El nivel final de cada modo es el mayor entre el semanal y el diario.

Uso:
    status = preparar_status(load_unit_status_history(cliente, "motor"))
    risk = preparar_risk(load_risk_scores_history(cliente, "motor"))
    evid = armar_evidencia("CA-51", "2026-03-08", status, risk, perfil_cliente(cliente))
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from src.informe_falla import catalog as c
from src.informe_falla.catalog import MODOS, NIVELES
from src.utils.logger import get_logger

logger = get_logger(__name__)


# =============================================================================
# Utilidades
# =============================================================================
def limpio(obj):
    """Convierte a tipos serializables en JSON (numpy, NaN, fechas) y redondea."""
    if isinstance(obj, dict):
        return {str(k): limpio(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [limpio(v) for v in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        return None if np.isnan(obj) else round(float(obj), c.DECIMALES)
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, (pd.Timestamp, date)):
        return obj.isoformat()[:10]
    return obj


def _lunes(d):
    return d - timedelta(days=d.weekday())


def _semana_iso(d):
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def _menor_confianza(a, b):
    return min(a, b, key=c.CONFIANZAS.index)


def _inicio_base(perfil):
    return c.fecha_inicio_base(perfil)


# =============================================================================
# Preparacion de las fuentes (desde los lectores de src/data/predictive_v2.py)
# =============================================================================
def _modos(valor) -> dict:
    if isinstance(valor, dict):
        return valor
    if not valor:
        return {}
    try:
        return json.loads(valor)
    except (TypeError, ValueError):
        return {}


# Columnas de unit_status_summary que usa el informe. Las primeras son imprescindibles; las demas, si
# faltan en las particiones leidas (puede pasar entre la copia local y S3), se agregan vacias.
COLUMNAS_STATUS_OBLIGATORIAS = ["Unit", "Fecha", "year", "week", "modos_ordenados"]
COLUMNAS_STATUS_OPCIONALES = ["dias_sin_datos", "dias_media_30d", "estado", "media_30d", "ranking", "peor_modo",
                              "peor_valor"]


def preparar_status(df: pd.DataFrame) -> pd.DataFrame:
    """unit_status_summary (todas las semanas, con year/week) con los modos como columnas y el lunes de cada semana."""
    df = df.copy()
    if df.empty:
        return pd.DataFrame(columns=COLUMNAS_STATUS_OBLIGATORIAS + ["lunes"] + COLUMNAS_STATUS_OPCIONALES + MODOS)
    faltan = [col for col in COLUMNAS_STATUS_OBLIGATORIAS if col not in df.columns]
    if faltan:
        raise ValueError(f"unit_status_summary sin las columnas {faltan}: no se puede armar el informe")
    df["Fecha"] = pd.to_datetime(df["Fecha"])
    opcionales = [col for col in COLUMNAS_STATUS_OPCIONALES if col not in df.columns]
    if opcionales:
        logger.warning(f"unit_status_summary sin las columnas {opcionales}: se usan vacias")
        for col in opcionales:
            df[col] = np.nan
    if "dias_sin_datos" in opcionales:
        # Mismo calculo que el contrato: dias entre la Fecha de la unidad y la ultima Fecha de esa semana.
        df["dias_sin_datos"] = (df.groupby(["year", "week"])["Fecha"].transform("max") - df["Fecha"]).dt.days
    df["lunes"] = [pd.Timestamp(date.fromisocalendar(int(y), int(w), 1)) for y, w in zip(df["year"], df["week"])]
    modos = df["modos_ordenados"].apply(_modos)
    for m in MODOS:
        df[m] = modos.apply(lambda d: d.get(m, np.nan)).astype(float)
    return df


def preparar_risk(df: pd.DataFrame) -> pd.DataFrame:
    """risk_scores en formato ancho: una fila por unidad y dia, una columna por modo. Vacio = sin dato ese dia."""
    if df.empty:
        return pd.DataFrame(columns=["Unit", "Fecha", *MODOS])
    df = df.copy()
    df["Fecha"] = pd.to_datetime(df["Fecha"]).dt.normalize()
    ancho = (df.pivot_table(index=["Unit", "Fecha"], columns="failure_mode", values="risk_value", aggfunc="last")
               .reset_index().rename_axis(columns=None))
    # Un cliente puede no publicar algun modo (CDA no tiene refrigerante ni turbo): queda sin datos.
    for m in MODOS:
        if m not in ancho.columns:
            ancho[m] = np.nan
    return ancho


# =============================================================================
# Consulta y ventana semanal
# =============================================================================
def preparar_consulta(unidad, fecha):
    """La fecha puede ser 'AAAA-MM-DD' o un texto con hora y zona; si trae zona, se pasa a hora local."""
    ts = pd.Timestamp(fecha)
    if ts.tzinfo is not None:
        ts = ts.tz_convert(c.ZONA_HORARIA)
    f = ts.date()
    return {"unidad": unidad, "fecha": f.isoformat(), "semana_iso": _semana_iso(f)}


def _zona(rel):
    return "base" if rel < -c.SEMANAS_RECIENTES else "reciente"


def ventana(status, fecha, inicio_base):
    """
    Semanas -SEMANAS_ATRAS a -1 respecto de la semana de la fecha. Solo entran particiones cuyo ultimo
    dato es anterior a la fecha. La semana de la fecha (rel = 0) se excluye: su dato incluye dias posteriores.
    """
    f = pd.Timestamp(fecha).date()
    df = status.copy()
    df["rel"] = (df["lunes"] - pd.Timestamp(_lunes(f))).dt.days // 7
    fecha_max = df.groupby("rel")["Fecha"].transform("max")
    df = df[(df["rel"] <= -1) & (df["rel"] >= -c.SEMANAS_ATRAS) & (fecha_max.dt.date < f)].copy()
    df["valida"] = df["dias_sin_datos"].fillna(np.inf) <= c.DIAS_SIN_DATOS_MAX
    df["en_base"] = df["lunes"].dt.date >= inicio_base
    df["zona"] = df["rel"].map(_zona)
    return df


def trayectoria(vista, unidad):
    """Filas de la unidad, de la mas antigua a la mas reciente."""
    return vista[vista["Unit"] == unidad].sort_values("rel").reset_index(drop=True)


# =============================================================================
# Herramientas semanales
# =============================================================================
def auditoria(vista, tray, fecha, inicio_base):
    """Cobertura, frescura de los datos, brechas semana a semana y techo de confianza."""
    f = pd.Timestamp(fecha).date()
    lunes0 = _lunes(f)
    primera = max(-c.SEMANAS_ATRAS, (_lunes(inicio_base + timedelta(days=6)) - lunes0).days // 7)
    por_rel = {int(r["rel"]): r for _, r in tray.iterrows()}
    con_particion = set(vista["rel"])

    brechas = []
    for rel in range(primera, 0):
        if rel not in con_particion:
            tipo, fila = "sin_particion", None
        elif rel not in por_rel:
            tipo, fila = "unidad_ausente", None
        elif not por_rel[rel]["valida"]:
            tipo, fila = "unidad_sin_datos", por_rel[rel]
        else:
            continue
        brechas.append({"semana_rel": rel, "semana_iso": _semana_iso(lunes0 + timedelta(weeks=rel)),
                        "zona": _zona(rel), "tipo": tipo,
                        "dias_sin_datos": fila["dias_sin_datos"] if fila is not None else None,
                        "fecha_ultimo_dato": fila["Fecha"] if fila is not None else None})

    ok = tray[tray["valida"]]
    n_base = int(((ok["zona"] == "base") & ok["en_base"]).sum())
    n_rec = int((ok["zona"] == "reciente").sum())
    ultimo = tray["Fecha"].max() if len(tray) else None
    dias_ultimo = (f - ultimo.date()).days if ultimo is not None else None
    media_corta = ok.loc[(ok["zona"] == "reciente") & (ok["dias_media_30d"] < c.MIN_DIAS_MEDIA_30D), "rel"].tolist()

    advertencias = []
    if dias_ultimo is not None and dias_ultimo > c.DIAS_DATOS_VIEJOS:
        advertencias.append(f"La unidad no tiene datos nuevos desde {ultimo.date().isoformat()} "
                            f"({dias_ultimo} días antes de la fecha): el Predictivo no estaba mirando esta unidad.")
    if n_rec < c.MIN_SEMANAS_RECIENTES:
        techo = "insuficiente"
        advertencias.append(f"Solo {n_rec} semanas válidas en el último mes.")
    elif n_base < c.MIN_SEMANAS_BASE or n_rec < c.SEMANAS_RECIENTES or (dias_ultimo or 0) > c.DIAS_DATOS_VIEJOS:
        techo = "baja"
    else:
        techo = "media"   # tope de esta version: una sola fuente, sin aceite ni telemetria por señal
    if n_base < c.MIN_SEMANAS_BASE:
        advertencias.append(f"Línea base con {n_base} semanas (mínimo {c.MIN_SEMANAS_BASE}): "
                            "no se puede comparar contra la propia unidad.")
    if 0 < n_rec < c.SEMANAS_RECIENTES:
        advertencias.append(f"Último mes con {n_rec} de {c.SEMANAS_RECIENTES} semanas válidas.")
    if media_corta:
        advertencias.append(f"Media de 30 días calculada con menos de {c.MIN_DIAS_MEDIA_30D} días "
                            f"en las semanas {media_corta}.")

    return limpio({
        "semanas_validas": {"base": n_base, "reciente": n_rec},
        "ultimo_dato_unidad": ultimo, "dias_desde_ultimo_dato": dias_ultimo,
        "brechas": brechas,
        "techo_confianza": techo,
        "advertencias": advertencias,
    })


def _semanas_anomalas(vista, metrica):
    """
    Para todas las unidades a la vez: percentil semanal en la flota (sin contarse a si misma), linea base
    propia y si cada semana del ultimo mes es anomala. Sin base suficiente, basta el percentil de flota.
    """
    v = vista[vista["valida"] & vista[metrica].notna()][["Unit", "rel", "zona", "en_base", metrica]].copy()
    n = v.groupby("rel")[metrica].transform("count")
    rango = v.groupby("rel")[metrica].rank(method="average")
    v["pct"] = np.where(n > 1, 100 * (rango - 1) / (n - 1).clip(lower=1), np.nan)

    base = v[(v["zona"] == "base") & v["en_base"]].groupby("Unit")[metrica].agg(["max", "mean", "std", "count"])
    b_max, b_media = v["Unit"].map(base["max"]), v["Unit"].map(base["mean"])
    b_desv, b_n = v["Unit"].map(base["std"]).fillna(0), v["Unit"].map(base["count"]).fillna(0)
    z = (v[metrica] - b_media) / b_desv.where(b_desv > 0)
    sobre_base = (v[metrica] - b_max >= c.SALTO_MIN) & ((z >= c.Z_MIN) | (b_desv == 0))   # desv 0: basta el salto
    sobre_base |= b_n < c.MIN_SEMANAS_BASE

    v["anomala"] = (v["zona"] == "reciente") & (v["pct"] >= c.PERCENTIL_FLOTA_MIN) & sobre_base
    return v


def _patron(filas):
    """Semanas anomalas del ultimo mes y racha de semanas anomalas hasta la ultima semana."""
    rec = filas[filas["zona"] == "reciente"].sort_values("rel")
    anomalas = rec.loc[rec["anomala"], "rel"].astype(int).tolist()
    racha = 0
    for a in reversed(rec["anomala"].tolist()):
        if not a:
            break
        racha += 1
    return anomalas, racha


def _nivel(anomalas, racha, alertas, especifica, subio_sobre_base):
    if not anomalas:
        return "bajo" if subio_sobre_base else "ninguno"
    if not especifica:
        return "bajo"
    if racha >= c.RACHA_ALTA or len(anomalas) >= c.SEMANAS_ANOMALAS_ALTA or alertas:
        return "alto"
    if len(anomalas) >= c.SEMANAS_ANOMALAS_MEDIA or max(anomalas) >= -c.SEMANAS_FRESCAS:
        return "medio"
    return "bajo"   # una semana anomala aislada, lejos de la fecha


def analizar_metrica(vista, unidad, metrica):
    """Comparacion del ultimo mes contra la propia unidad y contra la flota, especificidad y nivel."""
    tabla = _semanas_anomalas(vista, metrica)
    propia = tabla[tabla["Unit"] == unidad]
    rec = propia[propia["zona"] == "reciente"].sort_values("rel")
    base = propia.loc[(propia["zona"] == "base") & propia["en_base"], metrica]
    if rec.empty:
        return {"nivel": "sin_datos"}

    anomalas, racha = _patron(propia)
    alertas = rec.loc[rec[metrica] >= c.UMBRAL_ALERTA_PREDICTIVO, "rel"].astype(int).tolist()

    # Especificidad: ¿cuantas otras unidades tienen el mismo patron en las mismas semanas?
    minimo = max(1, min(len(anomalas), c.SEMANAS_ANOMALAS_MEDIA))
    otras = [len(_patron(g)[0]) for _, g in tabla[tabla["Unit"] != unidad].groupby("Unit")
             if (g["zona"] == "reciente").any()]
    con_patron = sum(x >= minimo for x in otras)
    fraccion = con_patron / len(otras) if otras else None
    especifica = fraccion is not None and fraccion <= c.MAX_FRACCION_FLOTA

    subio = len(base) > 0 and rec[metrica].max() > base.max()
    return limpio({
        "nivel": _nivel(anomalas, racha, alertas, especifica, subio),
        "semanas_anomalas": anomalas,
        "racha_hasta_ultima_semana": racha,
        "semanas_sobre_alerta": alertas,
        "vs_unidad": {
            "semanas_base": len(base), "base_suficiente": len(base) >= c.MIN_SEMANAS_BASE,
            "base_media": base.mean() if len(base) else None, "base_max": base.max() if len(base) else None,
            "reciente_media": rec[metrica].mean(), "reciente_max": rec[metrica].max(),
            "ultima_semana": rec[metrica].iloc[-1],
        },
        "vs_flota": {
            "por_semana": [{"rel": int(r), "valor": x, "percentil": p, "anomala": bool(a)}
                           for r, x, p, a in zip(rec["rel"], rec[metrica], rec["pct"], rec["anomala"])],
            "percentil_max_reciente": rec["pct"].max(),
            "percentil_ultima_semana": rec["pct"].iloc[-1],
        },
        "especificidad": {"n_unidades_flota": len(otras), "n_con_mismo_patron": con_patron,
                          "fraccion": fraccion, "especifica": especifica},
    })


def ranking_modos(analisis):
    """Modos ordenados por nivel, luego por numero de semanas anomalas y percentil maximo."""
    filas = [{"modo": m, "nivel": a["nivel"], "semanas_anomalas": len(a.get("semanas_anomalas", [])),
              "racha": a.get("racha_hasta_ultima_semana", 0),
              "percentil_max": a.get("vs_flota", {}).get("percentil_max_reciente")}
             for m, a in analisis.items() if m in MODOS]
    return sorted(filas, key=lambda r: (-NIVELES.index(r["nivel"]), -r["semanas_anomalas"], -(r["percentil_max"] or 0)))


def veredicto_reglas(aud, ranking):
    """Veredicto determinista: referencia para la IA y base del test placebo."""
    techo = aud["techo_confianza"]
    altos = [r["modo"] for r in ranking if r["nivel"] == "alto"]
    medios = [r["modo"] for r in ranking if r["nivel"] == "medio"]
    if techo == "insuficiente":
        return {"veredicto": "DATOS INSUFICIENTES", "confianza": "insuficiente", "modos": []}
    if altos:
        return {"veredicto": "SEÑAL CLARA", "confianza": techo, "modos": altos + medios}
    if medios:
        return {"veredicto": "SEÑAL DÉBIL", "confianza": _menor_confianza(techo, "baja"), "modos": medios}
    return {"veredicto": "SIN SEÑAL ANÓMALA", "confianza": techo, "modos": []}


# =============================================================================
# Score diario
# =============================================================================
def ventana_diaria(risk, fecha, inicio_base):
    """Dias hasta el anterior a la fecha (incluye los de la semana de la detencion). Nada posterior."""
    f = pd.Timestamp(fecha).normalize()
    df = risk[(risk["Fecha"] < f) & (risk["Fecha"] >= f - pd.Timedelta(weeks=c.SEMANAS_ATRAS))].copy()
    df["dias_antes"] = (f - df["Fecha"]).dt.days
    df["zona"] = np.where(df["dias_antes"] <= c.DIAS_RECIENTES, "reciente", "base")
    df["en_base"] = df["Fecha"].dt.date >= inicio_base
    return df


def auditoria_diaria(vd, unidad, fecha):
    """Dias con dato en el ultimo mes, ultimo dia con dato y brechas con fechas exactas (flota o unidad)."""
    f = pd.Timestamp(fecha).normalize()
    dias_mes = pd.date_range(f - pd.Timedelta(days=c.DIAS_RECIENTES), f - pd.Timedelta(days=1))
    propia = vd[vd["Unit"] == unidad]
    con_dato_unidad = set(propia.loc[propia[MODOS].notna().any(axis=1), "Fecha"])
    con_dato_flota = set(vd["Fecha"])

    brechas, actual = [], None
    for d in dias_mes:
        if d in con_dato_unidad:
            actual = None
            continue
        tipo = "sin_datos_flota" if d not in con_dato_flota else "unidad_sin_datos"
        if actual and actual["tipo"] == tipo:
            actual["hasta"], actual["dias"] = d, actual["dias"] + 1
        else:
            actual = {"desde": d, "hasta": d, "dias": 1, "tipo": tipo}
            brechas.append(actual)

    n_rec = sum(d in con_dato_unidad for d in dias_mes)
    n_base = int(((propia["zona"] == "base") & propia["en_base"] & propia[MODOS].notna().any(axis=1)).sum())
    ultimo = max(con_dato_unidad) if con_dato_unidad else None
    if n_rec < c.MIN_DIAS_RECIENTES:
        techo = "insuficiente"
    elif n_rec < c.MIN_DIAS_RECIENTES_MEDIA or n_base < c.MIN_DIAS_BASE:
        techo = "baja"
    else:
        techo = "media"
    return limpio({
        "dias_con_dato": {"base": n_base, "reciente": n_rec, "reciente_esperados": len(dias_mes)},
        "ultimo_dia_con_dato": ultimo, "dias_desde_ultimo_dato": (f - ultimo).days if ultimo is not None else None,
        "brechas": brechas, "techo_confianza": techo,
    })


def _dias_anomalos(vd, modo):
    """Para todas las unidades: percentil diario en la flota, base diaria propia y si cada dia reciente es anomalo."""
    v = vd[["Unit", "Fecha", "dias_antes", "zona", "en_base", modo]].dropna(subset=[modo]).copy()
    n = v.groupby("Fecha")[modo].transform("count")
    rango = v.groupby("Fecha")[modo].rank(method="average")
    v["pct"] = np.where(n > 1, 100 * (rango - 1) / (n - 1).clip(lower=1), np.nan)
    base = v[(v["zona"] == "base") & v["en_base"]].groupby("Unit")[modo]
    stats = pd.DataFrame({"p": base.quantile(c.PERCENTIL_BASE_DIARIO / 100), "media": base.mean(),
                          "desv": base.std(), "n": base.count()})
    p, media = v["Unit"].map(stats["p"]), v["Unit"].map(stats["media"])
    desv, n_base = v["Unit"].map(stats["desv"]).fillna(0), v["Unit"].map(stats["n"]).fillna(0)
    z = (v[modo] - media) / desv.where(desv > 0)
    sobre_base = (v[modo] - p >= c.SALTO_MIN) & ((z >= c.Z_MIN) | (desv == 0))
    sobre_base |= n_base < c.MIN_DIAS_BASE
    v["anomalo"] = (v["zona"] == "reciente") & (v["pct"] >= c.PERCENTIL_FLOTA_MIN) & sobre_base
    return v, stats


def _patron_diario(filas):
    """Dias anomalos del mes, inicio del primer episodio sostenido y racha de dias anomalos hasta el ultimo dia."""
    rec = filas[filas["zona"] == "reciente"].sort_values("Fecha")
    anom = rec.loc[rec["anomalo"], "Fecha"].tolist()
    inicio = next((d for d in anom
                   if sum(d <= x < d + pd.Timedelta(days=c.VENTANA_SOSTENIDO) for x in anom) >= c.DIAS_SOSTENIDO), None)
    racha, esperado = 0, None
    for d, a in zip(reversed(rec["Fecha"].tolist()), reversed(rec["anomalo"].tolist())):
        if not a or (esperado is not None and d != esperado):
            break
        racha, esperado = racha + 1, d - pd.Timedelta(days=1)
    return anom, inicio, racha


def analizar_modo_diario(vd, unidad, modo, fecha):
    """Devuelve (analisis del modo, tabla diaria de todas las unidades para ese modo)."""
    v, stats = _dias_anomalos(vd, modo)
    propia = v[v["Unit"] == unidad]
    rec = propia[propia["zona"] == "reciente"].sort_values("Fecha")
    if rec.empty:
        return {"nivel_diario": "sin_datos"}, v
    anom, inicio, racha = _patron_diario(propia)
    sostenido = inicio is not None or racha >= c.RACHA_DIAS_ALTA
    f = pd.Timestamp(fecha).normalize()
    frescos = [d for d in anom if (f - d).days <= c.DIAS_FRESCOS]

    # Especificidad: otras unidades con el mismo tipo de patron en los mismos dias
    otras = []
    for _, g in v[v["Unit"] != unidad].groupby("Unit"):
        if (g["zona"] == "reciente").any():
            a, i, r = _patron_diario(g)
            otras.append((i is not None or r >= c.RACHA_DIAS_ALTA) if sostenido
                         else len([d for d in a if (f - d).days <= c.DIAS_FRESCOS]) >= 2)
    fraccion = sum(otras) / len(otras) if otras else None
    especifica = fraccion is not None and fraccion <= c.MAX_FRACCION_FLOTA

    if not anom:
        nivel = "ninguno"
    elif not especifica:
        nivel = "bajo"
    elif racha >= c.RACHA_DIAS_ALTA or (inicio is not None and len(anom) >= c.DIAS_ANOMALOS_ALTA):
        nivel = "alto"
    elif inicio is not None or len(frescos) >= 2:
        nivel = "medio"
    else:
        nivel = "bajo"

    s = stats.loc[unidad] if unidad in stats.index else None
    return limpio({
        "nivel_diario": nivel,
        "dias_anomalos": anom,
        "inicio_episodio": inicio,
        "racha_dias_hasta_ultimo_dato": racha,
        "dias_anomalos_ultima_semana": frescos,
        "base_diaria": {"dias": int(s["n"]) if s is not None else 0,
                        "media": s["media"] if s is not None else None,
                        f"p{c.PERCENTIL_BASE_DIARIO}": s["p"] if s is not None else None},
        "ultimo_dia": {"fecha": rec["Fecha"].iloc[-1], "valor": rec[modo].iloc[-1], "percentil_flota": rec["pct"].iloc[-1]},
        "maximo_mes": {"fecha": rec.loc[rec[modo].idxmax(), "Fecha"], "valor": rec[modo].max()},
        "especificidad": {"n_unidades_flota": len(otras), "n_con_mismo_patron": sum(otras),
                          "fraccion": fraccion, "especifica": especifica},
    }), v


def _serie_grafico(tabla, unidad, modo, fecha):
    """Ultimos DIAS_GRAFICO dias de la unidad, para el informe (no se envia a la IA)."""
    desde = pd.Timestamp(fecha).normalize() - pd.Timedelta(days=c.DIAS_GRAFICO)
    t = tabla[(tabla["Unit"] == unidad) & (tabla["Fecha"] >= desde)].sort_values("Fecha")
    return limpio([{"fecha": d, "valor": x, "percentil_flota": p, "anomalo": bool(a), "zona": z}
                   for d, x, p, a, z in zip(t["Fecha"], t[modo], t["pct"], t["anomalo"], t["zona"])])


# =============================================================================
# Evidencia
# =============================================================================
COLUMNAS_TRAYECTORIA = ["rel", "zona", "valida", "dias_sin_datos", "estado", "media_30d", "ranking",
                        "peor_modo", "peor_valor"] + MODOS


def _evidencia_semanal(unidad, fecha, status, inicio_base):
    consulta = preparar_consulta(unidad, fecha)
    vista = ventana(status, consulta["fecha"], inicio_base)
    tray = trayectoria(vista, unidad)
    aud = auditoria(vista, tray, consulta["fecha"], inicio_base)

    if tray.empty:
        analisis, ranking = {}, []
        veredicto = {"veredicto": "DATOS INSUFICIENTES", "confianza": "insuficiente", "modos": [],
                     "motivo": f"La unidad {unidad} no aparece en unit_status_summary antes de la fecha."}
    else:
        analisis = {m: {**analizar_metrica(vista, unidad, m), "componentes_compatibles": c.COMPONENTES_POR_MODO[m],
                        "verificaciones_sugeridas": c.verificaciones(c.VERIFICACIONES_POR_MODO[m])}
                    for m in MODOS}
        analisis["media_30d"] = analizar_metrica(vista, unidad, "media_30d")
        ranking = ranking_modos(analisis)
        veredicto = veredicto_reglas(aud, ranking)

    lunes0 = _lunes(pd.Timestamp(consulta["fecha"]).date())
    ultima_valida = tray[tray["valida"]].tail(1)
    tabla_tray = tray.reindex(columns=COLUMNAS_TRAYECTORIA).copy()
    tabla_tray.insert(1, "semana_iso", [_semana_iso(lunes0 + timedelta(weeks=int(r))) for r in tray["rel"]])
    desde = max(inicio_base, lunes0 - timedelta(weeks=c.SEMANAS_ATRAS))
    return limpio({
        "consulta": consulta,
        "ventanas": {
            "periodo_desde": desde,
            "periodo_hasta": pd.Timestamp(consulta["fecha"]).date() - timedelta(days=1),
            "reciente": f"{_semana_iso(lunes0 - timedelta(weeks=c.SEMANAS_RECIENTES))} a "
                        f"{_semana_iso(lunes0 - timedelta(weeks=1))}",
            "base": f"desde {desde.isoformat()} hasta "
                    f"antes de {_semana_iso(lunes0 - timedelta(weeks=c.SEMANAS_RECIENTES))}",
            "semana_de_la_fecha": "excluida por diseño: su dato incluye días posteriores (no es una brecha)",
        },
        "auditoria": aud,
        "dashboard_ultima_semana": (ultima_valida.reindex(columns=["rel", "estado", "media_30d", "ranking",
                                                                    "peor_modo", "peor_valor"])
                                    .to_dict("records") or [None])[0],
        "trayectoria": tabla_tray.to_dict("records"),
        "analisis_por_metrica": analisis,
        "ranking_modos": ranking,
        "veredicto_reglas": veredicto,
        "acciones_previas": c.verificaciones(c.ACCIONES_PREVIAS),
    })


def armar_evidencia(unidad, fecha, status, risk, perfil: Optional[dict] = None):
    """Todo lo que calculan las herramientas para una unidad y fecha (sin IA): semanal + diario."""
    inicio_base = _inicio_base(perfil)
    evid = _evidencia_semanal(unidad, fecha, status, inicio_base)
    f = evid["consulta"]["fecha"]
    vd = ventana_diaria(risk, f, inicio_base)
    aud_d = auditoria_diaria(vd, unidad, f)

    hay_diario = bool((vd["Unit"] == unidad).any())
    analisis_d, series = {}, {}
    if hay_diario:
        for m in MODOS:
            analisis_d[m], tabla = analizar_modo_diario(vd, unidad, m, f)
            series[m] = _serie_grafico(tabla, unidad, m, f)

    # Nivel final de cada modo: el mayor entre el semanal y el diario
    for m in MODOS:
        a = evid["analisis_por_metrica"].setdefault(m, {    # sin datos semanales: se completa con el catalogo
            "nivel": "sin_datos", "componentes_compatibles": c.COMPONENTES_POR_MODO[m],
            "verificaciones_sugeridas": c.verificaciones(c.VERIFICACIONES_POR_MODO[m])})
        a["nivel_semanal"] = a["nivel"]
        a["nivel_diario"] = analisis_d.get(m, {}).get("nivel_diario", "sin_datos")
        a["nivel"] = max(a["nivel_semanal"], a["nivel_diario"], key=NIVELES.index)

    # Auditoria combinada: si hay datos diarios, manda el techo diario (cuenta dias, no semanas)
    aud = evid["auditoria"]
    if hay_diario:
        aud["techo_confianza"] = aud_d["techo_confianza"]
    if aud_d["ultimo_dia_con_dato"]:
        aud["ultimo_dato_unidad"], aud["dias_desde_ultimo_dato"] = aud_d["ultimo_dia_con_dato"], aud_d["dias_desde_ultimo_dato"]
    dias_u = sum(b["dias"] for b in aud_d["brechas"] if b["tipo"] == "unidad_sin_datos")
    dias_f = sum(b["dias"] for b in aud_d["brechas"] if b["tipo"] == "sin_datos_flota")
    if dias_u:
        aud["advertencias"].append(f"Score diario: la unidad no tiene datos en {dias_u} de los últimos {c.DIAS_RECIENTES} días.")
    if dias_f:
        aud["advertencias"].append(f"Score diario: {dias_f} días del último mes sin datos para toda la flota (problema del pipeline).")

    evid["ranking_modos"] = ranking_modos(evid["analisis_por_metrica"])
    sin_datos = "motivo" in evid["veredicto_reglas"] and not hay_diario     # la unidad no aparece en ninguna fuente
    if not sin_datos:
        evid["veredicto_reglas"] = veredicto_reglas(aud, evid["ranking_modos"])
    evid["ventanas"]["reciente_diario"] = (f"{(pd.Timestamp(f) - pd.Timedelta(days=c.DIAS_RECIENTES)).date()} a "
                                           f"{(pd.Timestamp(f) - pd.Timedelta(days=1)).date()} (incluye los días de "
                                           "la semana de la detención anteriores a la fecha)")
    evid["diario"] = {"auditoria": aud_d, "analisis_por_modo": analisis_d, "series": series}
    return evid


def evaluar_lote(pares, status, risk, perfil: Optional[dict] = None):
    """Veredicto por reglas (sin IA) para muchas (unidad, fecha). Sirve para el test placebo."""
    filas = []
    for unidad, fecha in pares:
        e = armar_evidencia(unidad, fecha, status, risk, perfil)
        v = e["veredicto_reglas"]
        filas.append({"unidad": unidad, "fecha": e["consulta"]["fecha"], "veredicto": v["veredicto"],
                      "confianza": v["confianza"], "modos": ",".join(v["modos"]),
                      "dias_desde_ultimo_dato": e["auditoria"]["dias_desde_ultimo_dato"]})
    return pd.DataFrame(filas)