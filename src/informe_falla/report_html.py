"""
Informe preliminar de falla, paso 3: el informe para el cliente como HTML (pdf.py lo pasa a PDF).

Lo que se puede calcular sale de la evidencia, nunca de la IA: identificacion, estado de la
unidad, linea de tiempo, grafico, otros modos y detenciones previas. De la IA (res["informe"])
salen el resumen, las hipotesis, la cadena causal, la causa probable, las
recomendaciones y las limitaciones. Los pasos de inspeccion se muestran con el texto del
catalogo. Lo que el usuario escribio en el formulario y sus fotos van tal cual, escapados.

El PDF es para el cliente: no lleva el Ishikawa (la IA lo sigue produciendo y queda en el
registro JSON), ni avisos internos de los controles o el veredicto de las reglas (esos se
muestran en la vista del dashboard). Las intervenciones previas (mantenciones.py) se
muestran segun su cobertura: la falta de registros nunca se lee como falta de intervenciones.

Los estilos viven en assets/report.css (fuentes locales en assets/fonts/).
"""

from __future__ import annotations

import html
import re
from datetime import date, timedelta
from pathlib import Path
from typing import List, Optional

from src.informe_falla.catalog import NOMBRE_MODO

ASSETS_DIR = Path(__file__).parent / "assets"

EVALUACION = {   # texto visible, estilo
    "mas_probable": ("Más probable", "fuerte"), "poco_probable": ("Poco probable", "media"),
    "descartada": ("Descartada", "neutra"), "no_evaluable": ("No evaluable", "borde"),
}
NIVEL_CONFIANZA = {"alta": 3, "media": 2, "baja": 1, "insuficiente": 0}
PERCENTIL_FLOTA = 90       # "entre las mas altas de la flota" (igual a catalog.PERCENTIL_FLOTA_MIN)
_MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
          "noviembre", "diciembre"]

# Alcance del informe: va bajo el titulo y al pie.
ALCANCE = ("Informe preliminar elaborado con los datos del Predictivo de los 3 meses previos a la detención. "
           "Indica la falla más probable; la causa debe confirmarse con la inspección de la unidad.")


def numero_informe(unidad: str, fecha: str) -> str:
    """N.º de informe que ve el cliente: IPF-<unidad>-<AAAAMMDD de la detencion>."""
    return "IPF-" + unidad + "-" + fecha.replace("-", "")


# Campos del formulario que se muestran, en orden: (clave en contexto, titulo).
CAMPOS_CONTEXTO = [("sistema", "Sistema indicado"), ("titulo", "Título"), ("descripcion", "Descripción del evento"),
                   ("hallazgos", "Hallazgos de inspección"), ("acciones", "Acciones realizadas")]


def _e(texto):
    return html.escape(str(texto)) if texto is not None else ""


def _d(iso):
    return date.fromisoformat(str(iso)[:10])


def _fecha_larga(iso):
    d = _d(iso)
    return f"{d.day} de {_MESES[d.month - 1]} de {d.year}"


def _fecha_media(iso):
    d = _d(iso)
    return f"{d.day} {_MESES[d.month - 1][:3]} {d.year}"


def _fecha_corta(iso):
    d = _d(iso)
    return f"{d.day} {_MESES[d.month - 1][:3]}"


def _num(x, dec=1):
    return "—" if x is None else f"{x:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _tope_redondo(v):
    potencia = 10 ** (len(str(int(max(v, 1)))) - 1)
    return next(m * potencia for m in (1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10) if m * potencia >= v)


def _pill(texto, estilo):
    return '<span class="pill pill-' + estilo + '">' + _e(texto) + "</span>"


# =============================================================================
# Datos derivados de la evidencia (sin IA)
# =============================================================================
def _lunes_de(evid):
    f = _d(evid["consulta"]["fecha"])
    return f - timedelta(days=f.weekday())


def _diario_modo(evid, modo):
    return ((evid.get("diario") or {}).get("analisis_por_modo") or {}).get(modo, {})


def _destacados(evid):
    return [r["modo"] for r in evid.get("ranking_modos", []) if r["nivel"] in ("alto", "medio")]


def _modo_principal(evid):
    """El modo que cuenta el relato (grafico y linea de tiempo). Cojinetes y lubricacion juntos: cojinetes."""
    destacados = _destacados(evid)
    if "bearing_wear_risk" in destacados and "lubrication_failure_risk" in destacados:
        return "bearing_wear_risk"
    if destacados:
        return destacados[0]
    return next((r["modo"] for r in evid.get("ranking_modos", []) if r["nivel"] == "bajo"), None)


def _habitual(evid, modo):
    """(valor, texto) de referencia: nivel alto habitual diario o maximo habitual semanal."""
    base = _diario_modo(evid, modo).get("base_diaria") or {}
    diario = next((v for k, v in base.items() if k.startswith("p") and k[1:].isdigit()), None)
    if diario:
        return diario, "su nivel alto habitual"
    return (evid["analisis_por_metrica"].get(modo, {}).get("vs_unidad") or {}).get("base_max"), "su máximo habitual"


def _inicio(evid, modo):
    """Primer dia (diario) o lunes de la primera semana (semanal) en que el modo se salio de lo habitual."""
    d = _diario_modo(evid, modo)
    if d.get("inicio_episodio"):
        return d["inicio_episodio"]
    if d.get("dias_anomalos"):
        return d["dias_anomalos"][0]
    semanas = evid["analisis_por_metrica"].get(modo, {}).get("semanas_anomalas") or []
    return (_lunes_de(evid) + timedelta(weeks=semanas[0])).isoformat() if semanas else None


def _maximo(evid, modo):
    """(fecha, valor) del maximo del ultimo mes."""
    d = _diario_modo(evid, modo)
    if d.get("maximo_mes"):
        return d["maximo_mes"]["fecha"], d["maximo_mes"]["valor"]
    filas = [f for f in evid.get("trayectoria", []) if f["zona"] == "reciente" and f.get(modo) is not None]
    if not filas:
        return None, None
    f = max(filas, key=lambda x: x[modo])
    return (_lunes_de(evid) + timedelta(weeks=f["rel"])).isoformat(), f[modo]


def _racha_flota(evid, modos):
    """Maximo de semanas seguidas en que algun modo destacado estuvo en la parte alta de la flota."""
    mejor = 0
    for m in modos:
        racha = 0
        for p in (evid["analisis_por_metrica"].get(m, {}).get("vs_flota") or {}).get("por_semana", []):
            racha = racha + 1 if (p.get("percentil") or 0) >= PERCENTIL_FLOTA else 0
            mejor = max(mejor, racha)
    return mejor


def _linea_de_tiempo(evid):
    """Eventos ordenados por fecha: intervenciones previas, señales del Predictivo, brechas y la detencion."""
    eventos = []
    for p in evid.get("detenciones_previas") or []:
        if p.get("en_linea_de_tiempo"):
            eventos.append((p["fecha"], "previa", "Correctiva previa", _resumen_intervencion(p)))
    pm = (evid.get("antecedentes_mantencion") or {}).get("ultimo_pm")
    desde = (evid.get("cobertura_mantenciones") or {}).get("ventana_desde")
    if pm and desde and pm["fecha"] >= desde:
        eventos.append((pm["fecha"], "previa", "Último PM", "Mantención programada del sistema."))

    destacados = _destacados(evid)
    juntos = "bearing_wear_risk" in destacados and "lubrication_failure_risk" in destacados
    if juntos:                                               # misma linea de evidencia: un solo relato
        destacados = [m for m in destacados if m != "lubrication_failure_risk"]
    principal = _modo_principal(evid)
    destacados = sorted(destacados, key=lambda m: m != principal)
    estado = ((evid.get("dashboard_ultima_semana") or {}).get("estado") or "").lower()
    for i, m in enumerate(destacados[:2]):
        nombre = NOMBRE_MODO[m] + (" (junto con falla de lubricación)" if juntos and m == "bearing_wear_risk" else "")
        ini = _inicio(evid, m)
        if ini:
            eventos.append((ini, "predictivo", "Predictivo", nombre + ": el score supera por primera vez lo habitual de la unidad."))
        fecha_max, valor = _maximo(evid, m)
        base, nombre_base = _habitual(evid, m)
        if fecha_max and valor is not None and fecha_max != ini:
            texto = NOMBRE_MODO[m] + ": el score llega a " + _num(valor, 0)
            if base and valor / base >= 2:
                texto += f", {valor / base:.0f} veces {nombre_base} ({_num(base)})"
            texto += "."
            if i == 0 and estado == "normal":
                texto += " El estado del dashboard seguía en Normal."
            eventos.append((fecha_max, "predictivo", "Predictivo", texto))

    brechas_d = ((evid.get("diario") or {}).get("auditoria") or {}).get("brechas", [])
    for b in brechas_d:
        quien = "toda la flota" if b["tipo"] == "sin_datos_flota" else "la unidad"
        rango = _fecha_corta(b["desde"]) if b["desde"] == b["hasta"] else _fecha_corta(b["desde"]) + " al " + _fecha_corta(b["hasta"])
        eventos.append((b["desde"], "brecha", "Sin datos", f"Sin datos del Predictivo para {quien}: {rango}."))
    if not brechas_d:
        for b in evid["auditoria"].get("brechas", []):
            inicio = (_lunes_de(evid) + timedelta(weeks=b["semana_rel"])).isoformat()
            quien = "toda la flota" if b["tipo"] == "sin_particion" else "la unidad"
            eventos.append((inicio, "brecha", "Sin datos",
                            f"Semana del {_fecha_corta(inicio)}: sin datos nuevos del Predictivo para {quien}."))
    eventos.append((evid["consulta"]["fecha"], "detencion", "Detención", "La unidad entra a detención."))
    return sorted(eventos, key=lambda ev: (ev[0], ev[1] == "detencion"))


def _enumerar(modos):
    """'Turbocargador, desbalance térmico y combustión': el primero con mayuscula, el resto en minuscula."""
    nombres = [NOMBRE_MODO[m] if i == 0 else NOMBRE_MODO[m].lower() for i, m in enumerate(modos)]
    return nombres[0] if len(nombres) == 1 else ", ".join(nombres[:-1]) + " y " + nombres[-1]


def _otros_modos(evid, modo_grafico):
    otros = [r for r in evid.get("ranking_modos", []) if r["modo"] != modo_grafico]
    frases = []
    destacados = [r["modo"] for r in otros if r["nivel"] in ("alto", "medio")]
    if destacados:
        frases.append(_enumerar(destacados) + (" también se salieron" if len(destacados) > 1 else " también se salió")
                      + " de lo habitual.")
    bajos = [r["modo"] for r in otros if r["nivel"] == "bajo"]
    if bajos:
        frases.append(_enumerar(bajos) + ": leve alza, dentro de su variación habitual.")
    sin_cambios = sum(r["nivel"] == "ninguno" for r in otros)
    if sin_cambios:
        frases.append(f"Los otros {sin_cambios} modos, sin cambios." if sin_cambios > 1 else "El otro modo, sin cambios.")
    sin_datos = [r["modo"] for r in otros if r["nivel"] == "sin_datos"]
    if sin_datos:
        frases.append(_enumerar(sin_datos) + ": sin datos para la unidad.")
    return " ".join(frases)


# =============================================================================
# Grafico del modo principal (SVG, sin librerias)
# =============================================================================
def _grafico(evid, modo):
    diario = evid.get("diario") or {}
    serie = (diario.get("series") or {}).get(modo)
    fecha_det = _d(evid["consulta"]["fecha"])
    if serie:
        puntos = [(_d(p["fecha"]), p["valor"], p["anomalo"], p["zona"] == "reciente") for p in serie]
        base = _diario_modo(evid, modo).get("base_diaria") or {}
        habitual = next((v for k, v in base.items() if k.startswith("p") and k[1:].isdigit()), None)
        etiqueta, paso = "Nivel alto habitual de la unidad", 1
    else:
        anomalas = set(evid["analisis_por_metrica"].get(modo, {}).get("semanas_anomalas") or [])
        lunes0 = _lunes_de(evid)
        puntos = [(lunes0 + timedelta(weeks=f["rel"]), f[modo], f["rel"] in anomalas, f["zona"] == "reciente")
                  for f in evid.get("trayectoria", []) if f.get(modo) is not None and f.get("valida", True)]
        habitual = (evid["analisis_por_metrica"].get(modo, {}).get("vs_unidad") or {}).get("base_max")
        etiqueta, paso = "Máximo habitual de la unidad", 7
    if not puntos:
        return ""
    W, H, izq, der, arr, aba = 560, 175, 40, 30, 22, 26
    d0, d1 = puntos[0][0].toordinal(), fecha_det.toordinal()
    vmax = _tope_redondo(max([p[1] for p in puntos] + [habitual or 0, 1]) * 1.1)

    def x(d):
        return izq + (d.toordinal() - d0) / max(d1 - d0, 1) * (W - izq - der)

    def y(v):
        return H - aba - v / vmax * (H - arr - aba)

    s = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Score de {_e(NOMBRE_MODO[modo])} en los 3 meses previos">']
    recientes = [p[0] for p in puntos if p[3]]
    if recientes:
        x0 = x(recientes[0]) - (3 if paso == 1 else 10)
        s.append(f'<rect class="g-zona" x="{x0:.1f}" y="{arr}" width="{x(fecha_det) - x0:.1f}" height="{H - arr - aba}"/>')
        s.append(f'<text class="g-eje" x="{(x0 + x(fecha_det)) / 2:.1f}" y="{arr - 7}" text-anchor="middle">Último mes</text>')
    for t in (0, vmax / 2, vmax):
        s.append(f'<line class="g-grilla" x1="{izq}" x2="{W - der}" y1="{y(t):.1f}" y2="{y(t):.1f}"/>')
        s.append(f'<text class="g-eje" x="{izq - 6}" y="{y(t) + 4:.1f}" text-anchor="end">{t:g}</text>')
    if habitual is not None:
        s.append(f'<line class="g-ref" x1="{izq}" x2="{W - der}" y1="{y(habitual):.1f}" y2="{y(habitual):.1f}"/>')
        s.append(f'<text class="g-eje" x="{izq + 4}" y="{y(habitual) - 6:.1f}">{etiqueta}: {_num(habitual)}</text>')
    tramos, tramo, previo = [], [], None
    for d, v, _, _ in puntos:                 # la linea se corta donde faltan datos
        if previo is not None and (d - previo).days > paso and tramo:
            tramos.append(tramo)
            tramo = []
        tramo.append(f"{x(d):.1f},{y(v):.1f}")
        previo = d
    if tramo:
        tramos.append(tramo)
    for t in tramos:
        s.append('<polyline class="g-serie" points="' + " ".join(t) + '"/>')
    anomalos = [(d, v) for d, v, a, _ in puntos if a]
    for d, v in anomalos:
        s.append(f'<circle class="g-anomalo" cx="{x(d):.1f}" cy="{y(v):.1f}" r="{3.5 if paso == 1 else 4.5}">'
                 f'<title>{_fecha_corta(d.isoformat())}: {_num(v)}</title></circle>')
    for d, v in (anomalos if paso == 7 else [max(anomalos, key=lambda p: p[1])] if anomalos else []):
        s.append(f'<text class="g-valor" x="{x(d) - 7:.1f}" y="{y(v) - 6:.1f}" text-anchor="end">{_num(v, 0)}</text>')
    s.append(f'<line class="g-detencion" x1="{x(fecha_det):.1f}" x2="{x(fecha_det):.1f}" y1="{arr}" y2="{H - aba}"/>')
    s.append(f'<text class="g-eje" x="{izq}" y="{H - 6}">{_e(_fecha_media(puntos[0][0].isoformat()))}</text>')
    s.append(f'<text class="g-eje" x="{x(fecha_det):.1f}" y="{H - 6}" text-anchor="end">'
             f'Detención: {_e(_fecha_corta(fecha_det.isoformat()))}</text>')
    s.append("</svg>")
    svg = "".join(s)
    for clase, atributos in _SVG_ATRIBUTOS.items():
        svg = svg.replace(f'class="{clase}"', f'class="{clase}" {atributos}')
    return svg


# El renderizador SVG de WeasyPrint no aplica las clases de la hoja de estilos dentro del SVG:
# los colores de report.css (g-*) se repiten aqui como atributos de presentacion.
_SVG_ATRIBUTOS = {
    "g-eje": 'fill="#59636E" font-size="11"',
    "g-valor": 'fill="#1F5FAD" font-size="11" font-weight="600"',
    "g-grilla": 'stroke="#DCE0E6"',
    "g-ref": 'stroke="#59636E" stroke-dasharray="4 4"',
    "g-zona": 'fill="#EEF1F5"',
    "g-serie": 'fill="none" stroke="#9AA3AD" stroke-width="2"',
    "g-anomalo": 'fill="#1F5FAD"',
    "g-detencion": 'stroke="#B3362C" stroke-width="2"',
}


# =============================================================================
# Bloques del documento
# =============================================================================
def problemas(res) -> List[str]:
    """Controles automaticos que fallaron, en texto para el aviso del informe."""
    p = []
    if res.get("errores_esquema"):
        p.append(f"La respuesta de la IA no cumple el formato ({len(res['errores_esquema'])} diferencias).")
    if res.get("fuentes_no_encontradas"):
        p.append(f"{len(res['fuentes_no_encontradas'])} fuentes citadas en las hipótesis no existen en los datos.")
    if res.get("hipotesis_sin_respaldo"):
        p.append("Hipótesis 'más probables' sin respaldo del Predictivo: " + ", ".join(res["hipotesis_sin_respaldo"]) + ".")
    if res.get("terminos_internos"):
        p.append("Textos para el cliente con términos internos: " + ", ".join(res["terminos_internos"]) + ".")
    if res.get("afirmaciones_prohibidas"):
        p.append("Afirmaciones que los registros de mantención no permiten: " + ", ".join(res["afirmaciones_prohibidas"]) + ".")
    if res.get("verificaciones_fuera_de_lugar"):
        p.append(f"{len(res['verificaciones_fuera_de_lugar'])} pasos de inspección no corresponden a las hipótesis.")
    return p


def _filas_hipotesis(inf):
    filas = []
    for h in inf.get("hipotesis", []):
        texto, estilo = EVALUACION.get(h["evaluacion"], (h["evaluacion"], "neutra"))
        filas.append('<tr><td class="h-nombre">' + _e(h["nombre"]) + "</td><td>" + _e(h["a_favor"]) + "</td>"
                     '<td class="tenue">' + _e(h["en_contra"]) + "</td><td>" + _pill(texto, estilo) + "</td></tr>")
    return "".join(filas)


def _cadena(inf):
    items = []
    for i, p in enumerate(inf.get("cadena_causal", []), 1):
        marca = ' <span class="a-confirmar">A confirmar</span>' if p.get("a_confirmar") else ""
        items.append(f'<li><span class="paso-n">{i}</span><div><div class="paso-q">{_e(p["pregunta"])}</div>'
                     f'<div>{_e(p["respuesta"])}{marca}</div></div></li>')
    return "".join(items)


def _inspeccion(inf, evid):
    catalogo = {v["id"]: v for v in evid.get("acciones_previas", [])}
    for a in evid.get("analisis_por_metrica", {}).values():
        catalogo.update({v["id"]: v for v in a.get("verificaciones_sugeridas", [])})
    items = []
    for p in inf.get("inspeccion", []):
        if p["id"] in catalogo:
            aporta = p.get("nota") and not _repite(p["nota"], catalogo[p["id"]]["accion"])
            nota = ' <span class="nota-paso">' + _e(p["nota"]) + "</span>" if aporta else ""
            items.append("<li>" + _e(catalogo[p["id"]]["accion"]) + "." + nota + "</li>")
    return "".join(items)


def _resumen_intervencion(p: dict, largo: int = 110) -> str:
    texto = p.get("descripcion") or "Sin detalle"
    texto = texto if len(texto) <= largo else texto[:largo - 1].rstrip() + "…"
    return (p["subsistema"] + ": " if p.get("subsistema") else "") + texto


def nota_cobertura_mantenciones(evid) -> str:
    """Frase determinista cuando la cobertura de mantenciones no es completa (vacia si lo es o no hay fuente).

    La ausencia de registros solo se lee como "sin intervenciones" con cobertura completa.
    """
    cob = evid.get("cobertura_mantenciones") or {}
    unidad = evid["consulta"]["unidad"]
    estado = cob.get("estado")
    if estado == "unidad_sin_registros":
        return f"La fuente de mantenciones no tiene registros de {unidad}: no se puede saber si hubo intervenciones previas."
    if estado == "fuera_de_cobertura":
        return (f"Los registros de mantención disponibles van del {_fecha_media(cob['datos_desde'])} al "
                f"{_fecha_media(cob['datos_hasta'])} y no cubren el período analizado.")
    if estado == "parcial":
        desde = max(cob["ventana_desde"], cob["datos_desde"])
        hasta = min(cob["ventana_hasta"], cob["datos_hasta"])
        return (f"Los registros de mantención cubren solo parte del período analizado "
                f"(del {_fecha_media(desde)} al {_fecha_media(hasta)}).")
    return ""


def _repite(nota: str, accion: str) -> bool:
    """La nota de la IA solo repite el paso del catalogo (la mayoria de sus palabras ya estan en el)."""
    palabras = {w for w in re.findall(r"\w{4,}", nota.lower())}
    return bool(palabras) and len(palabras & set(re.findall(r"\w{4,}", accion.lower()))) / len(palabras) >= 0.7


def _tabla_previas(evid):
    """Tabla de intervenciones del sistema en la ventana, o el mensaje que corresponde a la cobertura."""
    cob = evid.get("cobertura_mantenciones") or {}
    previas = evid.get("detenciones_previas")
    if not cob or cob.get("estado") == "sin_fuente":
        return ""
    if previas is None:
        return f'<p class="nota">{_e(nota_cobertura_mantenciones(evid))}</p>'
    if not previas:
        texto = ("Sin intervenciones del sistema en el período analizado." if cob["estado"] == "completa"
                 else "Sin intervenciones registradas en el tramo cubierto.")
        return f"<p>{_e(texto)}</p>"
    filas = "".join(
        "<tr><td>" + _e(_fecha_media(p["fecha"])) + "</td><td>" + _e(p.get("tipo", ""))
        + (' <span class="a-confirmar">Días previos</span>' if p.get("cerca_de_la_detencion") else "")
        + "</td><td>" + _e(p.get("subsistema", "")) + "</td><td>" + _e(p.get("descripcion", ""))
        + "</td><td>" + _e(_num(p["horas_dia"]) if p.get("horas_dia") is not None else "—") + "</td></tr>"
        for p in previas)
    return ('<table class="previas"><thead><tr><th scope="col">Fecha</th><th scope="col">Tipo</th>'
            '<th scope="col">Subsistema</th><th scope="col">Qué se hizo</th><th scope="col">Horas del día</th>'
            "</tr></thead><tbody>" + filas + "</tbody></table>")


def _resumen_antecedentes(evid) -> list:
    """Lineas cortas bajo la tabla: ultimo PM, rellenos, recurrencia y lo que se omitio."""
    a = evid.get("antecedentes_mantencion") or {}
    if not a:
        return []
    lineas = []
    if a.get("ultimo_pm"):
        lineas.append(f"Último mantenimiento programado: {_fecha_media(a['ultimo_pm']['fecha'])} "
                      f"({a['ultimo_pm']['dias_antes']} días antes).")
    rellenos = [f"{v['n']} de {k}" for k, v in (a.get("rellenos") or {}).items() if v["n"] and k != "otro"]
    if rellenos:
        lineas.append("Rellenos en el período: " + ", ".join(rellenos) + ".")
    for r in a.get("recurrencia") or []:
        lineas.append(f"{r['subsistema']}: {r['correctivas']} correctivas en los últimos "
                      f"{a.get('ventana_extendida_dias', 180)} días.")
    extra = (a.get("omitidos") or {}).get("fuera_del_tope")
    if extra:
        lineas.append(f"Y {extra} registros más en el período.")
    return lineas


def _bloque_previas(evid):
    tabla = _tabla_previas(evid)
    if not tabla:
        return ""
    notas = "".join(f'<p class="nota">{_e(x)}</p>' for x in _resumen_antecedentes(evid))
    if (evid.get("cobertura_mantenciones") or {}).get("estado") == "parcial":
        notas += f'<p class="nota">{_e(nota_cobertura_mantenciones(evid))}</p>'
    return (f'<div class="tarjeta-int previas-bloque"><h3>Intervenciones previas del sistema (3 meses)</h3>'
            f'{tabla}{notas}</div>')


def _lista(items):
    return "".join("<li>" + _e(t) + "</li>" for t in items)


def _contexto_cliente(unidad, fecha, contexto):
    """Lo que el usuario entrego en el formulario: unidad, fecha y los textos que haya escrito."""
    bloques = [f'<div>Unidad {_e(unidad)} y fecha de la detención: {_e(_fecha_media(fecha))}.</div>']
    for clave, titulo in CAMPOS_CONTEXTO:
        if (contexto or {}).get(clave):
            bloques.append(f'<div><div class="etq">{_e(titulo)}</div><div class="texto">{_e(contexto[clave])}</div></div>')
    return '<div class="contexto">' + "".join(bloques) + "</div>"


def _fotos(imagenes, numero_seccion):
    """Anexo con las fotos del formulario. Solo data URIs de imagen (validadas al subirlas)."""
    figuras = []
    for img in imagenes or []:
        src = img.get("data") or ""
        if not src.startswith("data:image/"):
            continue
        pie = f'<figcaption>{_e(img["caption"])}</figcaption>' if img.get("caption") else ""
        figuras.append(f'<figure class="foto"><img src="{_e(src)}" alt="{_e(img.get("filename", ""))}">{pie}'
                       f'<div class="archivo">{_e(img.get("filename", ""))}</div></figure>')
    if not figuras:
        return ""
    return (f'<section class="tarjeta"><h2>{numero_seccion}. Registro fotográfico</h2>'
            f'<p class="tenue">Imágenes entregadas por el cliente.</p><div class="grid-fotos" style="margin-top:12px">'
            + "".join(figuras) + "</div></section>")


# =============================================================================
# Documento
# =============================================================================
def generar(res, cliente: str = "[Cliente]", numero: Optional[str] = None, version=None,
            contexto: Optional[dict] = None, imagenes: Optional[list] = None,
            emision: Optional[date] = None) -> str:
    """Cuerpo del informe (sin <html>): fragmento con la clase .informe_falla, estilos aparte (assets/report.css)."""
    evid, inf = res["evidencia"], res["informe"]
    consulta, aud, ventanas = evid["consulta"], evid["auditoria"], evid.get("ventanas", {})
    unidad, fecha = consulta["unidad"], consulta["fecha"]
    destacados = _destacados(evid)
    hay_diario = bool((evid.get("diario") or {}).get("analisis_por_modo"))
    numero = numero or numero_informe(unidad, fecha)
    emision = emision or date.today()

    modo_graf = _modo_principal(evid)
    if modo_graf:
        unidad_tiempo = "días" if hay_diario else "semanas"
        bloque_graf = (f'<div class="tarjeta-int"><h3>Predictivo: {_e(NOMBRE_MODO[modo_graf].lower())}</h3>'
                       f'{_grafico(evid, modo_graf)}<p class="nota">Puntos azules: {unidad_tiempo} sobre lo habitual '
                       f'de la unidad y en la parte alta de la flota.</p></div>')
    else:
        bloque_graf = ('<div class="tarjeta-int"><h3>Predictivo</h3><p>Ningún modo de falla se salió de lo habitual '
                       'de la unidad en el período analizado.</p></div>')

    conf = inf["confianza"]
    barras = "".join('<span class="barra barra-on"></span>' if i < NIVEL_CONFIANZA.get(conf, 0)
                     else '<span class="barra"></span>' for i in range(3))
    inicios = [i for i in (_inicio(evid, m) for m in destacados) if i]
    desde = _fecha_media(min(inicios)) if inicios else "—"
    racha = _racha_flota(evid, destacados)
    frente_flota = (f"Entre las más altas, {racha} semanas seguidas" if racha >= 2 else
                    "Entre las más altas, 1 semana" if racha == 1 else "Dentro de lo normal de la flota")
    estado_dash = ((evid.get("dashboard_ultima_semana") or {}).get("estado") or "sin datos").capitalize()
    ultimo = _fecha_media(aud["ultimo_dato_unidad"]) if aud.get("ultimo_dato_unidad") else "Sin datos"
    periodo = _fecha_media(ventanas["periodo_desde"]) + " al " + _fecha_media(ventanas["periodo_hasta"])
    clase = {"previa": "ev-previa", "predictivo": "ev-predictivo", "brecha": "ev-brecha", "detencion": "ev-detencion"}
    linea = "".join(f'<li class="{clase[tipo]}"><div class="lt-fecha">{_e(_fecha_corta(f))}</div>'
                    f'<div class="lt-marca"><span></span></div><div><div class="lt-tipo">{_e(etq)}</div>'
                    f'<div>{_e(texto)}</div></div></li>' for f, tipo, etq, texto in _linea_de_tiempo(evid))
    hay_previas = evid.get("detenciones_previas") is not None
    cob = evid.get("cobertura_mantenciones") or {}
    fuentes = ("Predictivo (score semanal y diario)" if hay_diario else "Predictivo (score semanal)") + \
              ", 3 meses previos a la detención." + \
              (f" Registros de mantención de la unidad (disponibles hasta el {_fecha_media(cob['datos_hasta'])})."
               if hay_previas else "")
    sub_linea = ("señales del Predictivo, brechas de datos e intervenciones previas" if hay_previas
                 else "señales del Predictivo y brechas de datos")
    limitaciones = list(inf.get("limitaciones", []))
    if nota_cobertura_mantenciones(evid):
        limitaciones.append(nota_cobertura_mantenciones(evid))

    return f"""
<div class="informe_falla">
<div class="contenedor">
<div class="barra-sup">
  <span class="marca">Informe preliminar de falla</span>
</div>

<header class="tarjeta cabecera">
  <div class="cab-unidad"><span class="tenue">Unidad</span><span class="unidad">{_e(unidad)}</span></div>
  <div class="cab-datos">
    <h1>Detención del {_e(_fecha_larga(fecha))}</h1>
    <p class="nota">{_e(ALCANCE)}</p>
    <div class="grid-datos">
      <div><div class="etq">Detención</div><div class="val">{_e(_fecha_media(fecha))}</div></div>
      <div><div class="etq">Solicitado por</div><div class="val">{_e(cliente)}</div></div>
      <div><div class="etq">Fecha de emisión</div><div class="val">{_e(_fecha_media(emision.isoformat()))}</div></div>
      <div><div class="etq">N.º de informe</div><div class="val">{_e(numero)}</div></div>
    </div>
  </div>
</header>

<section class="resumen">
  <h2>Resumen</h2>
  <div class="resumen-grid">
    <div><span class="r-etq">Causa más probable</span><span class="r-val">{_e(inf["causa_mas_probable"])}</span></div>
    <div><span class="r-etq">Qué mostró el Predictivo</span><span class="r-val">{_e(inf["que_mostro_el_predictivo"])}</span></div>
    <div><span class="r-etq">Recomendación principal</span><span class="r-val">{_e(inf["recomendacion_principal"])}</span></div>
  </div>
  <div class="confianza">
    <span class="r-etq">Confianza del análisis</span>
    <span class="barras" aria-label="Confianza {_e(conf)}">{barras}</span>
    <strong>{_e(conf.capitalize())}</strong>
    <span class="r-etq">{_e(inf.get("motivo_confianza", ""))}</span>
  </div>
</section>

<div class="dos">
  <div class="tarjeta chica"><div class="etq fuerte">Información entregada por el cliente</div>
    {_contexto_cliente(unidad, fecha, contexto)}</div>
  <div class="tarjeta chica"><div class="etq fuerte">Fuentes consultadas</div><div>{_e(fuentes)}</div></div>
</div>

<section class="tarjeta">
  <h2>1. Identificación del evento</h2>
  <div class="grid-datos amplia">
    <div><div class="etq">Unidad</div><div class="val">{_e(unidad)}</div></div>
    <div><div class="etq">Fecha de la detención</div><div class="val">{_e(_fecha_media(fecha))}</div></div>
    <div><div class="etq">Período analizado</div><div class="val">{_e(periodo)}</div></div>
    <div><div class="etq">Último dato del Predictivo</div><div class="val">{_e(ultimo)}</div></div>
    <div><div class="etq">Componente afectado</div><div class="val">No informado: se infiere del Predictivo</div></div>
  </div>
</section>

<section class="tarjeta">
  <h2>2. Estado de la unidad antes de la detención</h2>
  <p class="destacado">{_e(inf["estado_unidad"])}</p>
  <div class="grid-cajas">
    <div class="caja"><div class="etq">Modos fuera de lo habitual</div><div class="val">{len(destacados)} de {len(NOMBRE_MODO)}</div></div>
    <div class="caja"><div class="etq">Desde</div><div class="val">{_e(desde)}</div></div>
    <div class="caja"><div class="etq">Frente a la flota</div><div class="val">{_e(frente_flota)}</div></div>
    <div class="caja"><div class="etq">Estado del dashboard</div><div class="val">{_e(estado_dash)}</div></div>
  </div>
</section>

<section class="tarjeta">
  <h2>3. Línea de tiempo</h2>
  <p class="tenue">Los 3 meses previos a la detención: {sub_linea}.</p>
  <ol class="linea">{linea}</ol>
</section>

<section class="tarjeta">
  <h2>4. Evidencia</h2>
  <div class="grid-evidencia">
    {bloque_graf}
    <div class="columna">
      <div class="tarjeta-int"><h3>Otros modos del Predictivo</h3><p>{_e(_otros_modos(evid, modo_graf))}</p></div>
    </div>
  </div>
  {_bloque_previas(evid)}
</section>

<section class="tarjeta">
  <h2>5. Hipótesis evaluadas</h2>
  <div class="tabla-scroll"><table class="hipotesis">
    <thead><tr><th scope="col">Hipótesis</th><th scope="col">A favor</th><th scope="col">En contra</th><th scope="col">Evaluación</th></tr></thead>
    <tbody>{_filas_hipotesis(inf)}</tbody>
  </table></div>
</section>

<section class="tarjeta">
  <h2>6. Análisis de causa</h2>
  <h3>Cadena causal probable</h3>
  <p class="nota">Inferida del Predictivo. Los pasos marcados deben confirmarse en la inspección.</p>
  <ol class="cadena">{_cadena(inf)}</ol>
</section>

<section class="tarjeta">
  <h2>7. Causa probable</h2>
  <div class="grid-cajas dos-col">
    <div class="caja"><div class="etq fuerte">Causa física</div><div>{_e(inf["causa_fisica"])}</div></div>
    <div class="caja"><div class="etq fuerte">Causas contribuyentes</div><div>{_e(inf["causas_contribuyentes"])}</div></div>
  </div>
</section>

<section class="tarjeta">
  <h2>8. Recomendaciones</h2>
  <div class="grid-analisis">
    <div><h3>Para la inspección de la unidad</h3><ol class="lista">{_inspeccion(inf, evid)}</ol>
      <p class="nota">Los valores de especificación son los del manual del fabricante.</p></div>
    <div><h3>Para evitar que se repita</h3><ol class="lista">{_lista(inf.get("prevencion", []))}</ol></div>
  </div>
</section>

<section class="tarjeta">
  <h2>9. Limitaciones del análisis</h2>
  <ul class="lista">{_lista(limitaciones)}</ul>
</section>

<footer class="pie">{_e(ALCANCE)}</footer>

{_fotos(imagenes, 10)}
</div>
</div>"""


def documento(res, **kwargs) -> str:
    """HTML completo y autocontenido (estilos incluidos); las fuentes se resuelven contra ASSETS_DIR."""
    unidad, fecha = res["evidencia"]["consulta"]["unidad"], res["evidencia"]["consulta"]["fecha"]
    estilos = (ASSETS_DIR / "report.css").read_text(encoding="utf-8")
    return ('<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>Informe preliminar {_e(unidad)} {_e(fecha)}</title><style>{estilos}</style></head>"
            '<body style="margin:0">' + generar(res, **kwargs) + "</body></html>")
