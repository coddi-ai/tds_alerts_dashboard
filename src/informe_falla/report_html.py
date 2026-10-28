"""
Informe preliminar de falla, paso 3: el informe para el cliente como HTML (pdf.py lo pasa a PDF).

Tres secciones, como la plantilla aprobada (Claude Design, "Informe preliminar de fallas"):
  1. Resumen: diagnostico, causa probable y acciones. Lo escribe la IA al final, integrando 2 y 3.
  2. Predictivo: estado actual semana a semana (unit_status_summary), puntajes por modo (risk_scores),
     estado del ciclo de vida (cumulative_risk_curve) y el diagnostico y la causa probable que el
     Predictivo publico para la unidad la semana previa (unit_failure_analisis).
  Aceite (sin numero, entre 2 y 3): las muestras de aceite del sistema en los 3 meses previos (aceite.py):
     cuantas, cuantas fuera de lo normal y la ultima; linea de tiempo; las ultimas muestras con el nivel de los
     ensayos fuera de limite (sin concentraciones) y las observaciones del laboratorio en tres parrafos.
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
    graficados = [m for m in _modos_graficados(evid) if m in _destacados(evid)]
    orden = sorted(evid.get("ranking_modos", []),       # primero los modos graficados, en el mismo orden
                   key=lambda r: graficados.index(r["modo"]) if r["modo"] in graficados else len(graficados))
    for r in orden:
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


def _modos_graficados(evid) -> list:
    """Un grafico por cada modo "Sobre lo habitual" (alto o medio), el principal primero. Si no hay
    ninguno, el modo con alza leve (si existe), para que la seccion muestre algo de contexto."""
    destacados = _destacados(evid)
    principal = _modo_principal(evid)
    if not destacados:
        return [principal] if principal else []
    return sorted(destacados, key=lambda m: m != principal)


def _bloque_puntajes(evid) -> str:
    modos = _modos_graficados(evid)
    hay_diario = bool((evid.get("diario") or {}).get("analisis_por_modo"))
    if modos:
        unidad_t = "días" if hay_diario else "semanas"
        graficos = "".join(f'<div class="tarjeta-int"><div class="fuerte">{_e(NOMBRE_MODO[m])}</div>{_grafico(evid, m)}</div>'
                           for m in modos)
        graficos += f'<p class="nota">Puntos azules: {unidad_t} sobre lo habitual de la unidad.</p>'
    else:
        graficos = ('<div class="tarjeta-int"><p>Ningún modo de falla se salió de lo habitual de la unidad en el '
                    'período analizado.</p></div>')
    return f"""
  <div class="sub separada puntajes">
    <div class="sub-cabeza"><h3>Puntajes de riesgo por modo de falla</h3><span class="fuente">Fuente: puntajes de riesgo del Predictivo</span></div>
    <div class="dos-col grafico-tabla"><div class="graficos">{graficos}</div><div>{_tabla_modos(evid)}</div></div>
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


# Colores del grafico del dashboard: fondo por zona y linea por estado de cada unidad
FONDO_CURVA = {"Normal": "#DDEBE4", "Alerta": "#FBEFC9", "Anormal": "#F5CFCF"}
LINEA_CURVA = {"Normal": "#3F9C76", "Alerta": "#E2B23C", "Anormal": "#D2544E"}
# El resto de la flota va en gris: solo la unidad del informe lleva el color de su estado
LINEA_FLOTA = "#8E959D"
TINTA_ZONA = {"Normal": "#1F5E44", "Alerta": "#7A5A00", "Anormal": "#8C2A24"}


def _k(v: float) -> str:
    return f"{v / 1000:.0f}k" if v >= 1000 else f"{v:.0f}"


def _etiquetas_libres(candidatos, ocupado):
    """Coloca etiquetas por prioridad y omite las que chocan con otra (como el dashboard)."""
    puestas = []
    for x, y, texto, extra in candidatos:
        ancho, alto = 6.2 * len(texto) + 6, 14
        caja = (x + 7, y - alto / 2, x + 7 + ancho, y + alto / 2)
        if any(not (caja[2] < o[0] or caja[0] > o[2] or caja[3] < o[1] or caja[1] > o[3]) for o in ocupado):
            continue
        ocupado.append(caja)
        puestas.append((caja, texto, extra))
    return puestas


def _grafico_curva(cv: dict, unidad: str) -> str:
    """
    Mismo lenguaje que el grafico del dashboard: fondo verde/amarillo/rojo con la banda de la flota (linea
    de alerta segmentada, umbral punteado), cada motor en gris con un punto al final con su nombre. La unidad
    del informe va con el color de su estado, mas gruesa y con su nombre destacado; las etiquetas que chocan se omiten.
    """
    puntos, banda = cv.get("puntos") or [], cv.get("banda") or []
    flota = [o for o in (cv.get("flota") or []) if isinstance(o, dict) and o.get("puntos")]
    if not puntos:
        return ""
    W, H, X0, X1, Y0, Y1 = 1000, 430, 70, 940, 12, 372
    hx = max([p[0] for p in puntos] + [p[0] for o in flota for p in o["puntos"]] + [1.0])
    vy = max([p[1] for p in puntos] + [p[1] for o in flota for p in o["puntos"]] + [1.0])
    paso_x, paso_y = _paso_redondo(hx, 6), _paso_redondo(vy, 7)
    xmax, ymax = hx * 1.04, vy * 1.06

    def x(h):
        return X0 + min(h, xmax) / xmax * (X1 - X0)

    def y(v):
        return Y1 - max(0.0, min(v, ymax)) / ymax * (Y1 - Y0)

    def linea(serie):
        return " ".join(f"{x(h):.1f},{y(v):.1f}" for h, v in serie)

    s = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Riesgo acumulado de los motores de la flota según '
         f'sus horas, con la banda de referencia de la flota. {_e(unidad)} destacada.">',
         f'<rect x="{X0}" y="{Y0}" width="{X1 - X0}" height="{Y1 - Y0}" fill="{FONDO_CURVA["Normal"]}"/>']

    zonas = []
    if banda:
        alerta = [(0.0, 0.0)] + [(b[0], b[2]) for b in banda] + [(xmax, banda[-1][2])]
        umbral = [(0.0, 0.0)] + [(b[0], b[3]) for b in banda] + [(xmax, banda[-1][3])]
        techo = [(xmax, ymax), (0.0, ymax)]
        s.append(f'<polygon points="{linea(umbral + techo)}" fill="{FONDO_CURVA["Anormal"]}"/>')
        s.append(f'<polygon points="{linea(alerta + list(reversed(umbral)))}" fill="{FONDO_CURVA["Alerta"]}"/>')
        zonas = [alerta, umbral]

    # Grilla
    for i in range(1, int(ymax / paso_y) + 1):
        s.append(f'<line x1="{X0}" x2="{X1}" y1="{y(i * paso_y):.1f}" y2="{y(i * paso_y):.1f}" stroke="#FFFFFF" '
                 f'stroke-opacity="0.6" stroke-width="1"/>')
    for i in range(1, int(xmax / paso_x) + 1):
        s.append(f'<line x1="{x(i * paso_x):.1f}" x2="{x(i * paso_x):.1f}" y1="{Y0}" y2="{Y1}" stroke="#FFFFFF" '
                 f'stroke-opacity="0.6" stroke-width="1"/>')
    if zonas:
        s.append(f'<polyline points="{linea(zonas[0])}" fill="none" stroke="#5F6670" stroke-width="1.3" '
                 f'stroke-dasharray="7 4"/>')
        s.append(f'<polyline points="{linea(zonas[1])}" fill="none" stroke="#B5655F" stroke-width="1.3" '
                 f'stroke-dasharray="2 3"/>')

    # Ejes
    for i in range(0, int(ymax / paso_y) + 1):
        s.append(f'<text x="{X0 - 8}" y="{y(i * paso_y) + 4:.1f}" text-anchor="end" font-size="12" '
                 f'fill="{TINTA_2}">{_k(i * paso_y)}</text>')
    for i in range(0, int(xmax / paso_x) + 1):
        s.append(f'<text x="{x(i * paso_x):.1f}" y="{Y1 + 18}" text-anchor="middle" font-size="12" '
                 f'fill="{TINTA_2}">{_k(i * paso_x)}</text>')
    s.append(f'<text x="{(X0 + X1) / 2:.0f}" y="{Y1 + 44}" text-anchor="middle" font-size="13" '
             f'fill="{TINTA_2}">Horas del motor</text>')
    s.append(f'<text x="18" y="{(Y0 + Y1) / 2:.0f}" text-anchor="middle" font-size="13" fill="{TINTA_2}" '
             f'transform="rotate(-90 18 {(Y0 + Y1) / 2:.0f})">Riesgo acumulado</text>')

    # Flota: linea y punto en gris, para que resalte la unidad del informe
    radio = {"Normal": 3.6, "Alerta": 4.6, "Anormal": 5.6}
    finales = []
    for o in flota:
        s.append(f'<polyline points="{linea(o["puntos"])}" fill="none" stroke="{LINEA_FLOTA}" stroke-width="1.3" '
                 f'stroke-opacity="0.75" stroke-linejoin="round"/>')
        hf, vf = o["puntos"][-1]
        finales.append((o.get("estado"), x(hf), y(vf), o.get("unidad") or ""))
    for est, cx, cy, _ in finales:
        s.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{radio.get(est, 3.6)}" '
                 f'fill="{LINEA_FLOTA}" stroke="#FFFFFF" stroke-width="0.8"/>')

    # Unidad del informe: mas gruesa, con borde blanco y punto grande
    estado = cv.get("estado_final") if cv.get("evaluable") else "Normal"
    col = LINEA_CURVA.get(estado, LINEA_CURVA["Normal"])
    s.append(f'<polyline points="{linea(puntos)}" fill="none" stroke="#FFFFFF" stroke-width="6" stroke-linejoin="round"/>')
    s.append(f'<polyline points="{linea(puntos)}" fill="none" stroke="{col}" stroke-width="3.5" stroke-linejoin="round"/>')
    hf, vf = puntos[-1]
    ux, uy = x(hf), y(vf)
    s.append(f'<circle cx="{ux:.1f}" cy="{uy:.1f}" r="8" fill="{col}" stroke="#FFFFFF" stroke-width="2.5"/>')

    # Etiquetas: primero la unidad (en una placa), luego las zonas, luego la flota por gravedad; se omiten las que chocan
    texto_u = unidad
    ancho_u = 9 * len(texto_u) + 16
    xu = ux + 12 if ux + 12 + ancho_u <= X1 else ux - 12 - ancho_u
    ocupado = [(xu, uy - 12, xu + ancho_u, uy + 12), (ux - 9, uy - 9, ux + 9, uy + 9)]
    ocupado += [(cx - r, cy - r, cx + r, cy + r) for est, cx, cy, _ in finales for r in [radio.get(est, 3.6)]]

    def caja_zona(texto, zx, zy, zona):
        ancho = 8.2 * len(texto) + 14
        ocupado.append((zx - ancho / 2, zy - 11, zx + ancho / 2, zy + 11))
        return (f'<rect x="{zx - ancho / 2:.1f}" y="{zy - 11:.1f}" width="{ancho:.0f}" height="22" rx="3" '
                f'fill="#FFFFFF" fill-opacity="0.6"/><text x="{zx:.1f}" y="{zy + 5:.1f}" text-anchor="middle" '
                f'font-size="14" fill="{TINTA_ZONA[zona]}">{texto}</text>')

    if zonas:
        def valor_en(serie, h):
            for (h0, v0), (h1, v1) in zip(serie, serie[1:]):
                if h0 <= h <= h1:
                    return v0 if h1 == h0 else v0 + (v1 - v0) * (h - h0) / (h1 - h0)
            return serie[-1][1]
        ha = xmax * 0.12
        s.append(caja_zona("Anormal", x(ha), (y(valor_en(zonas[1], ha)) + Y0) / 2, "Anormal"))
        hn = xmax * 0.85
        s.append(caja_zona("Normal", x(hn), (y(valor_en(zonas[0], hn)) + Y1) / 2 + 40, "Normal"))
        # Alerta: donde la franja amarilla es mas ancha dentro del grafico
        mejor = max((r for r in banda if r[3] < ymax * 0.95), key=lambda r: y(r[2]) - y(r[3]), default=None)
        if mejor:
            s.append(caja_zona("Alerta", x(mejor[0]), (y(mejor[2]) + y(mejor[3])) / 2, "Alerta"))

    prioridad = {"Anormal": 0, "Alerta": 1}
    candidatos = sorted(finales, key=lambda f: (prioridad.get(f[0], 2), -f[1]))
    for caja, texto, _ in _etiquetas_libres([(cx, cy, t, est) for est, cx, cy, t in candidatos if t], ocupado):
        s.append(f'<rect x="{caja[0]:.1f}" y="{caja[1]:.1f}" width="{caja[2] - caja[0]:.0f}" height="{caja[3] - caja[1]:.0f}" '
                 f'rx="2" fill="#FFFFFF" fill-opacity="0.55"/>'
                 f'<text x="{caja[0] + 3:.1f}" y="{caja[3] - 3.5:.1f}" font-size="10.5" fill="#3A424B">{_e(texto)}</text>')
    s.append(f'<rect x="{xu:.1f}" y="{uy - 12:.1f}" width="{ancho_u:.0f}" height="24" rx="4" fill="{col}" '
             f'stroke="#FFFFFF" stroke-width="1.5"/>')
    s.append(f'<text x="{xu + ancho_u / 2:.1f}" y="{uy + 5:.1f}" text-anchor="middle" font-size="14" font-weight="700" '
             f'fill="#FFFFFF">{_e(texto_u)}</text>')
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
    <p class="tenue">Riesgo acumulado de cada motor de la flota según sus horas de uso. La unidad {_e(unidad)} va
      destacada. Se evalúa desde las {_num(c.HORAS_MIN_CURVA, 0)} horas del motor.</p>
    <div class="tarjeta-int">{_grafico_curva(cv, unidad)}
      <p class="nota">En gris, el resto de la flota. La línea de {_e(unidad)} lleva el color de su estado: verde
        Normal, amarillo Alerta, rojo Anormal. El fondo es la referencia de la flota (verde dentro de lo habitual,
        amarillo sobre lo habitual, rojo muy sobre lo habitual) y puede no coincidir con el estado, que compara el
        último tramo del motor contra la flota. Donde hay muchas unidades juntas se omiten algunas etiquetas.</p>
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
# Aceite: muestras del sistema en los 3 meses previos (aceite.py)
# =============================================================================
MUESTRAS_EN_TABLA = 3   # las ultimas de cada componente; el texto de muestreo cubre toda la ventana


def _y(nombres: list) -> str:
    return " y ".join([", ".join(nombres[:-1]), nombres[-1]]) if len(nombres) > 1 else "".join(nombres)


def _horas_texto(x) -> str:
    return "—" if x is None else _num(x, 0 if float(x).is_integer() else 1)


def _texto_muestreo(a, componente, muestras) -> str:
    """Cuantas muestras hubo en la ventana, cuantas fuera de lo normal y cuando fue la ultima."""
    rango = f"entre el {_fecha_media(a['ventana_desde'])} y el {_fecha_media(a['ventana_hasta'])}"
    if not muestras:
        return f"{componente}: no hay muestras de aceite {rango}."
    texto = f"{componente}: {len(muestras)} {'muestra' if len(muestras) == 1 else 'muestras'} de aceite {rango}"
    fuera = {estado: sum(1 for m in muestras if m["resultado"] == estado) for estado in ("Alerta", "Anormal")}
    if sum(fuera.values()):
        detalle = _y([f"{n} en {estado}" for estado, n in fuera.items() if n])
        texto += f"; {sum(fuera.values())} con resultado fuera de lo normal ({detalle})"
    else:
        texto += ", todas con resultado normal"
    ultima = muestras[-1]
    return (texto + f". La última se tomó el {_fecha_media(ultima['fecha'])}, {ultima['dias_antes']} días antes de la "
            f"detención, con resultado {ultima['resultado']}.")


def _linea_muestras(a, fecha_det) -> str:
    """Linea de tiempo de las muestras, con el estilo de _linea_detenciones: un carril por componente, un
    punto por muestra con el color de su resultado y los cambios de aceite bajo la linea."""
    desde, fin = _d(a["ventana_desde"]), _d(fecha_det)
    total = max((fin - desde).days, 1)
    componentes = a["componentes"]
    varios = len(componentes) > 1
    W, X0, X1, Y0, ALTO_CARRIL = 1000, (170 if varios else 20), 960, 62, 64
    H = Y0 + ALTO_CARRIL * (len(componentes) - 1) + 74

    def x(d):
        return X0 + (_d(d) - desde).days / total * (X1 - X0)

    s = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Muestras de aceite de {_e(a["sistema"])} entre el '
         f'{_e(_fecha_larga(desde.isoformat()))} y la detención">']
    mes = date(desde.year, desde.month, 1)
    while mes <= fin:
        if mes >= desde:
            s.append(f'<line x1="{x(mes):.1f}" x2="{x(mes):.1f}" y1="{Y0 - 34}" y2="{H - 26}" stroke="{LINEA}"/>')
            s.append(f'<text x="{x(mes):.1f}" y="{H - 8}" text-anchor="middle" font-size="13" fill="{TINTA_2}">'
                     f'{_MESES[mes.month - 1][:3]}</text>')
        mes = date(mes.year + mes.month // 12, mes.month % 12 + 1, 1)
    for i, comp in enumerate(componentes):
        y = Y0 + i * ALTO_CARRIL
        propias = [m for m in a["muestras"] if m["componente"] == comp]
        s.append(f'<line x1="{X0}" x2="{X1}" y1="{y}" y2="{y}" stroke="#C9CFD6" stroke-width="2"/>')
        if varios:
            s.append(f'<text x="{X0 - 14}" y="{y + 5}" text-anchor="end" font-size="13" font-weight="600" '
                     f'fill="{TINTA_2}">{_e(comp)}</text>')
        for m in propias:
            if m["cambio_de_aceite"]:
                xm = x(m["fecha"])
                s.append(f'<polygon points="{xm:.1f},{y + 11} {xm - 5:.1f},{y + 19} {xm + 5:.1f},{y + 19}" fill="{GRIS}">'
                         f'<title>Cambio de aceite antes del {_fecha_corta(m["fecha"])}</title></polygon>')
        for m in propias:
            s.append(f'<circle cx="{x(m["fecha"]):.1f}" cy="{y}" r="6" fill="{LINEA_CURVA.get(m["resultado"], GRIS)}" '
                     f'stroke="#FFFFFF" stroke-width="1.5"><title>{_fecha_corta(m["fecha"])}: {_e(m["resultado"])}</title></circle>')
        if propias:
            s.append(f'<text x="{x(propias[-1]["fecha"]):.1f}" y="{y + 36}" text-anchor="middle" font-size="12" '
                     f'font-weight="600" fill="{TINTA_2}">Última: {_fecha_corta(propias[-1]["fecha"])}</text>')
    xf, y_fin = x(fin), Y0 + ALTO_CARRIL * (len(componentes) - 1)
    s.append(f'<line x1="{xf:.1f}" x2="{xf:.1f}" y1="{Y0 - 34}" y2="{y_fin + 12}" stroke="{ROJO}" stroke-width="2"/>')
    s.append(f'<text x="{xf - 6:.1f}" y="{Y0 - 40}" text-anchor="end" font-size="13" font-weight="700" fill="{ROJO}">'
             f'Detención {_fecha_corta(fin.isoformat())}</text>')
    s.append("</svg>")
    return "".join(s)


def _leyenda_muestras() -> str:
    puntos = "".join(f'<span><i style="background:{color};border-radius:50%"></i>{estado}</span>'
                     for estado, color in LINEA_CURVA.items())
    return (f'<div class="leyenda">{puntos}'
            f'<span><i style="width:0;height:0;border-radius:0;background:none;border-left:5px solid transparent;'
            f'border-right:5px solid transparent;border-bottom:8px solid {GRIS}"></i>Cambio de aceite</span>'
            f'<span><i style="width:3px;border-radius:0;background:{ROJO}"></i>Detención</span></div>')


def _bloque_aceite(evid) -> str:
    """Tarjeta Aceite: muestreo por componente, linea de tiempo, ultimas muestras y observaciones del laboratorio.

    Sin fuente de aceite para el cliente (o sistema sin componentes de aceite) no se muestra.
    """
    a = evid.get("aceite") or {}
    if not a.get("disponible"):
        return ""
    fecha = evid["consulta"]["fecha"]
    if not a["muestras"]:
        return (f'<section class="tarjeta"><h2>Aceite</h2>'
                f'<p>{_e(_texto_muestreo(a, a["sistema"].capitalize(), []))}</p></section>')
    textos = "".join(f"<p>{_e(_texto_muestreo(a, comp, [m for m in a['muestras'] if m['componente'] == comp]))}</p>"
                     for comp in a["componentes"])
    ultimas = []
    for comp in a["componentes"]:
        ultimas += [m for m in a["muestras"] if m["componente"] == comp][-MUESTRAS_EN_TABLA:]
    ultimas.sort(key=lambda m: m["fecha"])
    varios = len(a["componentes"]) > 1
    filas = "".join(
        f"<tr><td>{_e(_fecha_media(m['fecha']))}</td>" + (f"<td>{_e(m['componente'])}</td>" if varios else "")
        + f"<td>{m['dias_antes']}</td><td>{_e(_horas_texto(m['horas_motor']))}</td>"
        f"<td>{_e(_horas_texto(m['horas_aceite']))}</td><td>{_e(m['resultado'])}</td>"
        f"<td>{_e(', '.join(f'{k} ({v})' for k, v in m['fuera_de_limite'].items()) or '—')}</td></tr>"
        for m in ultimas)
    cabecera = ("<th>Fecha</th>" + ("<th>Componente</th>" if varios else "")
                + "<th>Días antes</th><th>Horas motor</th><th>Horas aceite</th><th>Resultado</th><th>Fuera de límite</th>")
    obs = a.get("observaciones") or {}
    parrafos = [obs[p] for p in ("condiciones", "recomendaciones", "seguimiento") if obs.get(p)]
    observaciones = ("<h3>Observaciones del laboratorio en los 3 meses</h3>" + "".join(f"<p>{_e(p)}</p>" for p in parrafos)
                     if parrafos else "")
    return f'''
<section class="tarjeta">
  <h2>Aceite</h2>
  {textos}
  <div class="tarjeta-int">{_linea_muestras(a, fecha)}{_leyenda_muestras()}</div>
  <table class="modos"><thead><tr>{cabecera}</tr></thead><tbody>{filas}</tbody></table>
  {observaciones}
</section>'''


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
    controles_aceite = (((res.get("evidencia") or {}).get("aceite") or {}).get("observaciones") or {}).get("controles")
    if controles_aceite:
        p.append("Observaciones del laboratorio: " + "; ".join(controles_aceite) + ".")
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

{_bloque_aceite(evid)}

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