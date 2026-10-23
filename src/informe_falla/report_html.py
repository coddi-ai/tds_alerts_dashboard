"""
Informe preliminar de falla, paso 3: el informe para el cliente como HTML (pdf.py lo pasa a PDF).

Tres secciones, como la plantilla aprobada (Claude Design, "Informe preliminar de fallas"):
  1. Resumen: diagnostico, causa probable y acciones. Lo escribe la IA al final, integrando 2 y 3.
  2. Predictivo: estado actual semana a semana (unit_status_summary), puntajes por modo (risk_scores),
     estado del ciclo de vida (cumulative_risk_curve) y el diagnostico y la causa probable que el
     Predictivo publico para la unidad la semana previa (unit_failure_analisis).
  3. Detenciones: las intervenciones previas (mantenciones.py) en cifras, linea de tiempo y listado,
     con un diagnostico y una causa probable escritos por la IA.

Lo que se puede calcular sale de la evidencia, nunca de la IA. El PDF es para el cliente: no lleva
avisos internos de los controles ni el veredicto de las reglas (quedan en el registro JSON y en la
vista del dashboard). Lo que el usuario escribio en el formulario y sus fotos van tal cual, escapados.

Los estilos viven en assets/report.css (fuentes locales en assets/fonts/). Los SVG llevan sus colores
como atributos: el renderizador SVG de WeasyPrint no aplica las clases de la hoja de estilos.
"""

from __future__ import annotations

import html
from datetime import date, timedelta
from pathlib import Path
from typing import List, Optional

from src.informe_falla import catalog as c
from src.informe_falla.catalog import NOMBRE_MODO


ASSETS_DIR = Path(__file__).parent / "assets"

NIVEL_CONFIANZA = {"alta": 3, "media": 2, "baja": 1, "insuficiente": 0}
_MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
          "noviembre", "diciembre"]

# Alcance del informe: va al pie.
ALCANCE = ("Informe preliminar elaborado con los datos del Predictivo de los 3 meses previos a la detención. "
           "Indica la falla más probable; la causa debe confirmarse con la inspección de la unidad.")

# Colores (iguales a report.css; los SVG los necesitan como atributos).
AZUL, ROJO, GRIS, TINTA_2, LINEA = "#1F5FAD", "#B3362C", "#9AA3AD", "#59636E", "#DCE0E6"
COLOR_ESTADO = {"normal": "#DCEBE2", "alerta": "#F2C66D", "anormal": "#C9473C"}
ZONAS_CURVA = {"normal": "#E4F0E8", "alerta": "#FBF0CC", "anormal": "#F7DCD9"}
TIPO_DETENCION = {"Correctiva": ("No programada", "ambar", "#E0A82E"),
                  "Programada": ("Programada", "neutra", GRIS),
                  "Sin clasificar": ("Sin clasificar", "borde", "#FFFFFF")}


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


def _inicio(evid, modo):
    """Primer dia (diario) o lunes de la primera semana (semanal) en que el modo se salio de lo habitual."""
    d = _diario_modo(evid, modo)
    if d.get("inicio_episodio"):
        return d["inicio_episodio"]
    if d.get("dias_anomalos"):
        return d["dias_anomalos"][0]
    semanas = evid["analisis_por_metrica"].get(modo, {}).get("semanas_anomalas") or []
    return (_lunes_de(evid) + timedelta(weeks=semanas[0])).isoformat() if semanas else None


# =============================================================================
# Grafico de puntajes del modo principal
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
# Bloques reutilizados: mantenciones, contexto del cliente y fotos
# =============================================================================
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
# 2.1 Estado actual, semana a semana (unit_status_summary)
# =============================================================================
def _semanas(evid) -> list:
    """[(lunes, estado o None)] de las semanas del periodo; None = semana sin datos validos."""
    lunes0 = _lunes_de(evid)
    desde = _d(evid["ventanas"]["periodo_desde"])
    por_rel = {f["rel"]: f for f in evid.get("trayectoria", [])}
    salida = []
    for rel in range(-c.SEMANAS_ATRAS, 0):
        lunes = lunes0 + timedelta(weeks=rel)
        if lunes + timedelta(days=6) < desde:
            continue
        fila = por_rel.get(rel)
        estado = (fila.get("estado") or "").lower() if fila and fila.get("valida") else None
        salida.append((lunes, estado if estado in COLOR_ESTADO else None))
    return salida


def _bloque_estado_actual(evid) -> str:
    semanas = _semanas(evid)
    celdas = []
    for lunes, estado in semanas:
        caja = (f'<span class="semana" style="background:{COLOR_ESTADO[estado]}"></span>' if estado
                else '<span class="semana semana-vacia"></span>')
        celdas.append(f'<div>{caja}<span class="semana-etq">{_e(_fecha_corta(lunes.isoformat()))}</span></div>')
    con_dato = [e for _, e in semanas if e]
    fuera = [e for e in con_dato if e != "normal"]
    ultimo = con_dato[-1] if con_dato else None
    desde = None
    for lunes, estado in reversed(semanas):          # tramo final continuo fuera de normal
        if estado in ("alerta", "anormal"):
            desde = lunes
        elif estado:
            break
    dash = evid.get("dashboard_ultima_semana") or {}
    peor = NOMBRE_MODO.get(dash.get("peor_modo"), "—") if dash else "—"
    estilo = {"normal": "normal", "alerta": "ambar", "anormal": "rojo"}
    estado_txt = _pill(ultimo.capitalize(), estilo[ultimo]) if ultimo else "Sin datos"
    return f"""
  <div class="sub">
    <div class="sub-cabeza"><h3>Estado actual de la unidad</h3><span class="fuente">Fuente: estado semanal del Predictivo</span></div>
    <p class="nota">Cada cuadro es una semana; la fecha indica el lunes en que empieza.</p>
    <div class="semanas" style="grid-template-columns:repeat({max(len(semanas), 1)},minmax(0,1fr))">{"".join(celdas)}</div>
    <div class="leyenda"><span><i style="background:{COLOR_ESTADO["normal"]}"></i>Normal</span>
      <span><i style="background:{COLOR_ESTADO["alerta"]}"></i>Alerta</span>
      <span><i style="background:{COLOR_ESTADO["anormal"]}"></i>Anormal</span>
      <span><i class="vacia"></i>Sin datos</span></div>
    <div class="cajas cuatro">
      <div class="caja"><div class="etq">Estado al último dato</div><div class="val">{estado_txt}</div></div>
      <div class="caja"><div class="etq">Fuera de lo normal desde</div><div class="val">{_e(_fecha_media(desde.isoformat())) if desde else "—"}</div></div>
      <div class="caja"><div class="etq">Modo más alto en la última semana</div><div class="val">{_e(peor)}</div></div>
      <div class="caja"><div class="etq">Semanas en alerta o anormal</div><div class="val">{len(fuera)} de {len(con_dato)}</div></div>
    </div>
  </div>"""


# =============================================================================
# 2.2 Puntajes de riesgo por modo (risk_scores)
# =============================================================================
def _tabla_modos(evid) -> str:
    filas = []
    for r in evid.get("ranking_modos", []):
        if r["nivel"] == "sin_datos" or r["modo"] not in NOMBRE_MODO:     # el cliente no publica ese modo
            continue
        if r["nivel"] in ("alto", "medio"):
            estado, inicio = _pill("Sobre lo habitual", "fuerte"), _inicio(evid, r["modo"])
            desde = _fecha_corta(inicio) if inicio else "—"
        elif r["nivel"] == "bajo":
            estado, desde = _pill("Leve alza", "ambar"), "—"
        else:
            estado, desde = '<span class="tenue">Sin cambios</span>', "—"
        clase = ' class="fuerte"' if r["nivel"] in ("alto", "medio") else ""
        filas.append(f'<tr><td{clase}>{_e(NOMBRE_MODO[r["modo"]])}</td><td>{estado}</td><td class="tenue">{_e(desde)}</td></tr>')
    return ('<table class="modos"><thead><tr><th scope="col">Modo de falla</th><th scope="col">Último mes</th>'
            '<th scope="col">Desde</th></tr></thead><tbody>' + "".join(filas) + "</tbody></table>")


def _bloque_puntajes(evid) -> str:
    modo = _modo_principal(evid)
    hay_diario = bool((evid.get("diario") or {}).get("analisis_por_modo"))
    if modo:
        unidad_t = "días" if hay_diario else "semanas"
        grafico = (f'<div class="tarjeta-int"><div class="fuerte">{_e(NOMBRE_MODO[modo])}</div>{_grafico(evid, modo)}'
                   f'<p class="nota">Puntos azules: {unidad_t} sobre lo habitual de la unidad.</p></div>')
    else:
        grafico = ('<div class="tarjeta-int"><p>Ningún modo de falla se salió de lo habitual de la unidad en el '
                   'período analizado.</p></div>')
    return f"""
  <div class="sub separada">
    <div class="sub-cabeza"><h3>Puntajes de riesgo por modo de falla</h3><span class="fuente">Fuente: puntajes de riesgo del Predictivo</span></div>
    <div class="dos-col grafico-tabla">{grafico}<div>{_tabla_modos(evid)}</div></div>
  </div>"""


# =============================================================================
# 2.3 Estado del ciclo de vida (cumulative_risk_curve)
# =============================================================================
def _compacto(v: float) -> str:
    if v >= 1_000_000:
        return _num(v / 1_000_000, 1).replace(",0", "") + " M"
    if v >= 1_000:
        return _num(v / 1_000, 0) + " mil"
    return _num(v, 0)


def _paso_redondo(maximo: float, marcas: int = 5) -> float:
    crudo = maximo / marcas
    potencia = 10 ** (len(str(int(max(crudo, 1)))) - 1)
    return next(m * potencia for m in (1, 2, 2.5, 5, 10) if m * potencia >= crudo)


def _grafico_curva(cv: dict, unidad: str) -> str:
    puntos, banda, flota = cv.get("puntos") or [], cv.get("banda") or [], cv.get("flota") or []
    if not puntos:
        return ""
    W, H, X0, X1, Y0, Y1 = 1000, 400, 74, 980, 16, 350
    hx = max([p[0] for p in puntos] + [p[0] for o in flota for p in o] + [1.0])
    vy = max([p[1] for p in puntos] + [p[1] for o in flota for p in o] + [1.0])
    paso_x, paso_y = _paso_redondo(hx * 1.03), _paso_redondo(vy * 1.12, 4)
    xmax = paso_x * (int(hx * 1.03 / paso_x) + 1)
    ymax = paso_y * (int(vy * 1.12 / paso_y) + 1)

    def x(h):
        return X0 + min(h, xmax) / xmax * (X1 - X0)

    def y(v):
        return Y1 - max(0.0, min(v, ymax)) / ymax * (Y1 - Y0)    # se recorta al area del grafico

    def linea(serie):
        return " ".join(f"{x(h):.1f},{y(v):.1f}" for h, v in serie)

    s = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Riesgo acumulado de los motores de la flota según sus '
         f'horas, con las zonas Normal, Alerta y Anormal. {_e(unidad)} destacada.">',
         f'<rect x="{X0}" y="{Y0}" width="{X1 - X0}" height="{Y1 - Y0}" fill="{ZONAS_CURVA["normal"]}"/>']
    if banda:
        alerta = [(b[0], b[2]) for b in banda]
        umbral = [(b[0], b[3]) for b in banda]
        amarillo = alerta + list(reversed(umbral))
        rojo = umbral + [(umbral[-1][0], ymax), (0, ymax), (0, umbral[0][1])]
        s.append(f'<polygon points="{linea(amarillo)}" fill="{ZONAS_CURVA["alerta"]}"/>')
        s.append(f'<polygon points="{linea(rojo)}" fill="{ZONAS_CURVA["anormal"]}"/>')
        s.append(f'<polyline points="{linea(alerta)}" fill="none" stroke="#6E7781" stroke-width="1.2" stroke-dasharray="6 4"/>')
        s.append(f'<polyline points="{linea(umbral)}" fill="none" stroke="#6E7781" stroke-width="1.2" stroke-dasharray="2 3"/>')
    for i in range(1, int(ymax / paso_y) + 1):
        v = i * paso_y
        s.append(f'<line x1="{X0}" x2="{X1}" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke="#FFFFFF" stroke-opacity="0.7"/>')
    for i in range(0, int(ymax / paso_y) + 1):
        v = i * paso_y
        s.append(f'<text x="{X0 - 8}" y="{y(v) + 4:.1f}" text-anchor="end" font-size="12" fill="{TINTA_2}">{_compacto(v)}</text>')
    for i in range(0, int(xmax / paso_x) + 1):
        h = i * paso_x
        s.append(f'<text x="{x(h):.1f}" y="{Y1 + 18}" text-anchor="middle" font-size="12" fill="{TINTA_2}">{_num(h, 0)}</text>')
    for o in flota:
        s.append(f'<polyline points="{linea(o)}" fill="none" stroke="{GRIS}" stroke-width="1.2"/>')
    s.append(f'<polyline points="{linea(puntos)}" fill="none" stroke="{AZUL}" stroke-width="3.5" stroke-linejoin="round"/>')
    hf, vf = puntos[-1]
    ancho = 14 + 8 * len(unidad)
    xe = min(x(hf) + 12, X1 - ancho)
    s.append(f'<circle cx="{x(hf):.1f}" cy="{y(vf):.1f}" r="7" fill="{AZUL}" stroke="#FFFFFF" stroke-width="2"/>')
    s.append(f'<rect x="{xe:.1f}" y="{y(vf) - 30:.1f}" width="{ancho}" height="24" rx="4" fill="{AZUL}"/>')
    s.append(f'<text x="{xe + ancho / 2:.1f}" y="{y(vf) - 13:.1f}" text-anchor="middle" font-size="13" font-weight="700" fill="#FFFFFF">{_e(unidad)}</text>')
    s.append(f'<text x="{(X0 + X1) / 2:.0f}" y="{Y1 + 40}" text-anchor="middle" font-size="12" fill="{TINTA_2}">Horas del motor</text>')
    s.append(f'<text x="16" y="{(Y0 + Y1) / 2:.0f}" text-anchor="middle" font-size="12" fill="{TINTA_2}" '
             f'transform="rotate(-90 16 {(Y0 + Y1) / 2:.0f})">Riesgo acumulado</text>')
    s.append("</svg>")
    return "".join(s)


def _bloque_ciclo_vida(evid) -> str:
    cv = evid.get("ciclo_vida") or {}
    unidad = evid["consulta"]["unidad"]
    cabeza = ('<div class="sub-cabeza"><h3>Estado del ciclo de vida del motor</h3>'
              '<span class="fuente">Fuente: curva acumulada del Predictivo</span></div>')
    if not cv.get("disponible"):
        texto = ("La unidad no tiene curva acumulada antes de la detención." if cv.get("motivo") == "unidad_sin_curva"
                 else "La curva acumulada del Predictivo no está disponible para este informe.")
        return f'<div class="sub separada">{cabeza}<p class="tenue">{_e(texto)}</p></div>'
    if not cv.get("evaluable"):
        zona = _pill("No evaluable", "borde")
        nota_zona = f'<div class="nota">El motor tiene menos de {_num(c.HORAS_MIN_CURVA, 0)} horas: la curva aún no se evalúa.</div>'
    else:
        estilo = {"Normal": "normal", "Alerta": "ambar", "Anormal": "rojo"}.get(cv["estado_final"], "neutra")
        zona, nota_zona = _pill(cv["estado_final"], estilo), ""
    desde = _fecha_media(cv["fuera_de_normal_desde"]) if cv.get("fuera_de_normal_desde") else "—"
    horas = _num(cv["horas_motor"], 0) + " h" if cv.get("horas_motor") is not None else "—"
    r = cv.get("flota_resumen") or {}
    aviso = ('<p class="nota">La curva disponible se calculó después de la detención; las zonas pueden incluir '
             'datos posteriores.</p>' if cv.get("particion_posterior") else "")
    return f"""
  <div class="sub separada">
    {cabeza}
    <p class="tenue">Riesgo acumulado de cada motor de la flota según sus horas de uso. La línea azul es esta unidad.
      Se evalúa desde las {_num(c.HORAS_MIN_CURVA, 0)} horas del motor.</p>
    <div class="tarjeta-int">{_grafico_curva(cv, unidad)}
      <div class="leyenda"><span><i class="linea-azul"></i>Esta unidad</span><span><i class="linea-gris"></i>Resto de la flota</span>
        <span><i style="background:{ZONAS_CURVA["normal"]}"></i>Normal: dentro de lo habitual de la flota</span>
        <span><i style="background:{ZONAS_CURVA["alerta"]}"></i>Alerta: sobre lo habitual</span>
        <span><i style="background:{ZONAS_CURVA["anormal"]}"></i>Anormal: muy sobre lo habitual</span></div>
    </div>
    {aviso}
    <div class="cajas cuatro">
      <div class="caja"><div class="etq">Zona al final del período</div><div class="val">{zona}</div>{nota_zona}</div>
      <div class="caja"><div class="etq">Fuera de lo normal desde</div><div class="val">{_e(desde)}</div></div>
      <div class="caja"><div class="etq">Horas del motor</div><div class="val">{_e(horas)}</div></div>
      <div class="caja"><div class="etq">Unidades de la flota en alerta o anormal</div><div class="val">{r.get("alerta_o_anormal", 0)} de {r.get("total", 0)}</div></div>
    </div>
  </div>"""


# =============================================================================
# 2.4 Diagnostico y causa probable del Predictivo (unit_failure_analisis)
# =============================================================================
def _textos_predictivo(evid) -> tuple:
    """(diagnostico, causa probable, nota de fecha) del analisis publicado; textos fijos si no lo hay."""
    a = evid.get("analisis_unidad") or {}
    if a.get("disponible") and a.get("con_texto"):
        nota = "Análisis del Predictivo del " + _fecha_media(a["fecha"])
        if a.get("antiguo"):
            nota += f", {a['dias_antes']} días antes de la detención"
        return a["diagnostico"], a.get("causa_probable") or "—", nota + "."
    if a.get("disponible"):
        return ("El Predictivo no mostraba señales fuera de lo normal en la semana previa a la detención.",
                "Sin una causa identificada por el Predictivo.", "Análisis del Predictivo del " + _fecha_media(a["fecha"]) + ".")
    return ("No hay un análisis del Predictivo para esta unidad antes de la detención.",
            "Sin una causa identificada por el Predictivo.", "")


def _cierre(diagnostico: str, causa: str, nota: str = "", pendiente: bool = False) -> str:
    clase = " tenue" if pendiente else ""
    return (f'<div class="cierre"><div class="caja-diag"><h3>Diagnóstico</h3><p class="mensaje{clase}">{_e(diagnostico)}</p>'
            + (f'<p class="nota">{_e(nota)}</p>' if nota else "") +
            f'</div><div class="caja-causa"><h3>Causa probable</h3><p class="mensaje{clase}">{_e(causa)}</p></div></div>')


# =============================================================================
# 3. Detenciones (mantenciones.py)
# =============================================================================
def _linea_detenciones(evid, previas) -> str:
    desde, fecha = _d(evid["ventanas"]["periodo_desde"]), _d(evid["consulta"]["fecha"])
    total = max((fecha - desde).days, 1)
    W, X0, X1, YL = 1000, 20, 960, 50

    def x(d):
        return X0 + (d - desde).days / total * (X1 - X0)

    s = [f'<svg viewBox="0 0 {W} 100" role="img" aria-label="Detenciones previas de la unidad entre el '
         f'{_e(_fecha_larga(desde.isoformat()))} y la detención">',
         f'<line x1="{X0}" x2="{X1}" y1="{YL}" y2="{YL}" stroke="#C9CFD6" stroke-width="2"/>']
    mes = date(desde.year, desde.month, 1)
    while mes <= fecha:
        if mes >= desde:
            s.append(f'<line x1="{x(mes):.1f}" x2="{x(mes):.1f}" y1="{YL - 6}" y2="{YL + 6}" stroke="{GRIS}"/>')
            s.append(f'<text x="{x(mes):.1f}" y="{YL + 26}" text-anchor="middle" font-size="13" fill="{TINTA_2}">{_MESES[mes.month - 1][:3]}</text>')
        mes = date(mes.year + mes.month // 12, mes.month % 12 + 1, 1)
    ultima_x, arriba = -999.0, True
    for p in sorted(previas, key=lambda q: q["fecha"]):
        _, _, color = TIPO_DETENCION.get(p.get("tipo"), TIPO_DETENCION["Sin clasificar"])
        xp = x(_d(p["fecha"]))
        arriba = not arriba if xp - ultima_x < 70 else True      # alterna la etiqueta si estan juntas
        ultima_x = xp
        borde = GRIS if color == "#FFFFFF" else "#FFFFFF"
        s.append(f'<circle cx="{xp:.1f}" cy="{YL}" r="8" fill="{color}" stroke="{borde}" stroke-width="2"/>')
        s.append(f'<text x="{xp:.1f}" y="{YL - 16 if arriba else YL + 44}" text-anchor="middle" font-size="12" '
                 f'font-weight="600" fill="{TINTA_2}">{_e(_fecha_corta(p["fecha"]))}</text>')
    s.append(f'<circle cx="{x(fecha):.1f}" cy="{YL}" r="10" fill="{ROJO}" stroke="#FFFFFF" stroke-width="2"/>')
    s.append(f'<text x="{x(fecha):.1f}" y="{YL - 18}" text-anchor="end" font-size="13" font-weight="700" fill="{ROJO}">'
             f'{_e(_fecha_corta(fecha.isoformat()))}</text>')
    s.append("</svg>")
    return "".join(s)


def _fila_detencion(fecha, titulo, pill, detalle, duracion) -> str:
    return (f'<li><span class="fuerte">{_e(fecha)}</span><div><div class="det-titulo"><span class="fuerte">{_e(titulo)}</span>'
            f'{pill}</div><div class="tenue chica">{_e(detalle)}</div></div><span class="tenue chica">{_e(duracion)}</span></li>')


def _bloque_detenciones(evid, inf) -> str:
    cob = evid.get("cobertura_mantenciones") or {}
    previas = evid.get("detenciones_previas")
    intro = '<p class="tenue">Detenciones relevantes de la unidad en los 3 meses previos.</p>'
    if previas is None:
        texto = nota_cobertura_mantenciones(evid) or "No hay una fuente de registros de mantención para este cliente."
        return (f'<section class="tarjeta"><h2>3. Detenciones</h2>{intro}<p>{_e(texto)}</p>'
                + _cierre("No hay registros de mantención de la unidad para este período.",
                          "Las detenciones no permiten orientar la causa.", pendiente=True) + "</section>")
    no_programadas = sum(1 for p in previas if p.get("tipo") == "Correctiva")
    horas = [p["horas_dia"] for p in previas if p.get("horas_dia") is not None]
    filas = []
    for p in sorted(previas, key=lambda q: q["fecha"]):
        texto, estilo, _ = TIPO_DETENCION.get(p.get("tipo"), TIPO_DETENCION["Sin clasificar"])
        pill = _pill(texto, estilo) + (_pill("Días previos", "ambar") if p.get("cerca_de_la_detencion") else "")
        detalle = p.get("descripcion") or "Sin detalle"
        if p.get("componentes"):
            detalle += " Componentes: " + p["componentes"] + "."
        filas.append(_fila_detencion(_fecha_corta(p["fecha"]), p.get("subsistema") or "Intervención", pill, detalle,
                                     _num(p["horas_dia"]) + " h" if p.get("horas_dia") is not None else "—"))
    filas.append(_fila_detencion(_fecha_corta(evid["consulta"]["fecha"]), "Detención actual", _pill("Detención analizada", "rojo"),
                                 "Motivo por confirmar en la inspección.", "—"))
    notas = "".join(f'<p class="nota">{_e(x)}</p>' for x in _resumen_antecedentes(evid))
    if cob.get("estado") == "parcial":
        notas += f'<p class="nota">{_e(nota_cobertura_mantenciones(evid))}</p>'
    d = inf.get("detenciones") or {}
    leyenda = "".join(f'<span><i class="punto" style="background:{color};{"border:1px solid " + GRIS if color == "#FFFFFF" else ""}"></i>{_e(t)}</span>'
                      for t, _, color in TIPO_DETENCION.values())
    return f"""
<section class="tarjeta">
  <h2>3. Detenciones</h2>
  {intro}
  <div class="cajas tres">
    <div class="caja"><div class="etq">Detenciones relevantes</div><div class="val">{len(previas)} en los 3 meses previos</div></div>
    <div class="caja"><div class="etq">No programadas</div><div class="val">{no_programadas}</div></div>
    <div class="caja"><div class="etq">Horas de intervención</div><div class="val">{_e(_num(sum(horas)) + " h" if horas else "—")}</div></div>
  </div>
  <div class="tarjeta-int">{_linea_detenciones(evid, previas)}
    <div class="leyenda">{leyenda}<span><i class="punto" style="background:{ROJO}"></i>Detención analizada</span></div></div>
  <ol class="detenciones">{"".join(filas)}</ol>
  {notas}
  {_cierre(d.get("diagnostico", ""), d.get("causa_probable", ""))}
</section>"""


# =============================================================================
# 1. Resumen
# =============================================================================
def _bloque_resumen(evid, inf) -> str:
    r = inf.get("resumen") or {}
    conf = inf.get("confianza", "insuficiente")
    barras = "".join('<span class="barra barra-on"></span>' if i < NIVEL_CONFIANZA.get(conf, 0)
                     else '<span class="barra"></span>' for i in range(3))
    acciones = "".join(f"<li>{_e(a)}</li>" for a in (r.get("acciones") or [])[:c.MAX_ACCIONES])
    riesgo = f'<span class="r-riesgo">{_e(r["riesgo_si_no_se_hace"])}</span>' if r.get("riesgo_si_no_se_hace") else ""
    detenciones = evid.get("detenciones_previas") is not None
    chip_det = ('<span class="chip-on">Detenciones: incorporado</span>' if detenciones
                else '<span class="chip-off">Detenciones: sin registros</span>')
    return f"""
<section class="resumen">
  <h2>1. Resumen</h2>
  <p class="r-sub">Conclusión que integra lo que muestran el Predictivo y las detenciones de la unidad.</p>
  <div class="resumen-grid">
    <div><span class="r-etq">Diagnóstico</span><span class="r-val">{_e(r.get("diagnostico", ""))}</span></div>
    <div><span class="r-etq">Causa probable</span><span class="r-val">{_e(r.get("causa_probable", ""))}</span></div>
    <div><span class="r-etq">Acciones</span><ol class="r-acciones">{acciones}</ol>{riesgo}</div>
  </div>
  <div class="confianza">
    <span class="r-etq">Confianza</span><span class="barras" aria-label="Confianza {_e(conf)}">{barras}</span>
    <strong>{_e(conf.capitalize())}</strong><span class="r-etq">{_e(inf.get("motivo_confianza", ""))}</span>
  </div>
  <div class="basado"><span class="r-etq">Basado en</span><span class="chip-on">Predictivo: incorporado</span>{chip_det}</div>
</section>"""


# =============================================================================
# Controles y pie
# =============================================================================
def problemas(res) -> List[str]:
    """Controles automaticos que fallaron, en texto (registro JSON y vista del dashboard; no van al PDF)."""
    p = []
    if res.get("errores_esquema"):
        p.append(f"La respuesta de la IA no cumple el formato ({len(res['errores_esquema'])} diferencias).")
    if res.get("terminos_internos"):
        p.append("Textos para el cliente con términos internos: " + ", ".join(res["terminos_internos"]) + ".")
    if res.get("lenguaje_prohibido"):
        p.append("Textos con palabras que los lineamientos prohíben: " + ", ".join(res["lenguaje_prohibido"]) + ".")
    if res.get("afirmaciones_prohibidas"):
        p.append("Afirmaciones que los registros de mantención no permiten: " + ", ".join(res["afirmaciones_prohibidas"]) + ".")
    if res.get("largo_excedido"):
        p.append("Mensajes más largos que lo que piden los lineamientos: " + "; ".join(res["largo_excedido"]) + ".")
    return p


def _brechas(evid) -> List[str]:
    """Frases del pie con los dias sin datos del Predictivo para la unidad (vacio si no hubo)."""
    brechas = [b for b in ((evid.get("diario") or {}).get("auditoria") or {}).get("brechas", [])
               if b.get("tipo") == "unidad_sin_datos"]
    rangos = [_fecha_corta(b["desde"]) if b["desde"] == b["hasta"] else _fecha_corta(b["desde"]) + " al " + _fecha_corta(b["hasta"])
              for b in brechas[:3]]
    return ["Faltan datos del Predictivo de la unidad: " + ", ".join(rangos) + "."] if rangos else []


# =============================================================================
# Documento
# =============================================================================
def generar(res, cliente: str = "[Cliente]", numero: Optional[str] = None, version=None,
            contexto: Optional[dict] = None, imagenes: Optional[list] = None,
            emision: Optional[date] = None) -> str:
    """Cuerpo del informe (sin <html>): fragmento con la clase .informe_falla, estilos aparte (assets/report.css)."""
    evid, inf = res["evidencia"], res["informe"]
    consulta, ventanas = evid["consulta"], evid.get("ventanas", {})
    unidad, fecha = consulta["unidad"], consulta["fecha"]
    numero = numero or numero_informe(unidad, fecha)
    emision = emision or date.today()
    periodo = _fecha_media(ventanas["periodo_desde"]) + " al " + _fecha_media(ventanas["periodo_hasta"])
    fuentes = ("Predictivo y detenciones" if evid.get("detenciones_previas") is not None else "Predictivo") + \
              f" de la unidad, del {periodo}."
    diag_p, causa_p, nota_p = _textos_predictivo(evid)
    pie = [ALCANCE, "El Predictivo no mide fallas eléctricas, estructurales ni de montaje."] + _brechas(evid)

    return f"""
<div class="informe_falla">
<div class="contenedor">
<div class="barra-sup"><span class="marca">Informe preliminar de fallas</span></div>

<header class="tarjeta cabecera">
  <div class="cab-unidad"><span class="tenue">Informe preliminar de fallas</span><span class="unidad">{_e(unidad)}</span></div>
  <div class="cab-datos">
    <h1>Detención del {_e(_fecha_larga(fecha))}</h1>
    <div class="cajas cuatro sin-fondo">
      <div><div class="etq">Detención</div><div class="val">{_e(_fecha_media(fecha))}</div></div>
      <div><div class="etq">Solicitado por</div><div class="val">{_e(cliente)}</div></div>
      <div><div class="etq">Fecha de emisión</div><div class="val">{_e(_fecha_media(emision.isoformat()))}</div></div>
      <div><div class="etq">N.º de informe</div><div class="val">{_e(numero)}</div></div>
    </div>
  </div>
</header>

<div class="dos-col">
  <div class="tarjeta chica"><div class="etq fuerte">Información entregada por el cliente</div>{_contexto_cliente(unidad, fecha, contexto)}</div>
  <div class="tarjeta chica"><div class="etq fuerte">Fuentes consultadas</div><div>{_e(fuentes)}</div></div>
</div>

{_bloque_resumen(evid, inf)}

<section class="tarjeta">
  <h2>2. Predictivo</h2>
  <p class="tenue">Lo que el sistema predictivo mostró de la unidad en los 3 meses previos a la detención.</p>
  {_bloque_estado_actual(evid)}
  {_bloque_puntajes(evid)}
  {_bloque_ciclo_vida(evid)}
  <div class="sub separada">{_cierre(diag_p, causa_p, nota_p)}</div>
</section>

{_bloque_detenciones(evid, inf)}

<footer class="pie">{"".join(f"<p>{_e(t)}</p>" for t in pie)}</footer>

{_fotos(imagenes, "Anexo")}
</div>
</div>"""


def documento(res, **kwargs) -> str:
    """HTML completo y autocontenido (estilos incluidos); las fuentes se resuelven contra ASSETS_DIR."""
    unidad, fecha = res["evidencia"]["consulta"]["unidad"], res["evidencia"]["consulta"]["fecha"]
    estilos = (ASSETS_DIR / "report.css").read_text(encoding="utf-8")
    return ('<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>Informe preliminar de fallas {_e(unidad)} {_e(fecha)}</title><style>{estilos}</style></head>"
            '<body style="margin:0">' + generar(res, **kwargs) + "</body></html>")