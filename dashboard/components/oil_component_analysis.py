"""Monitor de Aceite > Análisis por Componente: building the data and drawing it.

The rules (which sample is the latest, what counts as an essay out of limit, the age buckets, the
order of the matrix) live in `src/data/component_analysis.py`; this module turns the filters into a
plain, JSON-safe structure (kept client-side in a store) and that structure into the KPI tiles, the
three cards and the "Qué explica el estado" matrix.

Two stores feed the page:
  * `ca-source`: what the client + fleet + component produced (one record per unit + component, from
    its latest sample, with every essay out of limit). Built on the server, only when those change;
  * `ca-data` / `ca-view`: the matrix's own paging state (see oil_table.py). `ca-data` only says how
    many rows the "Mostrar" option lists, so changing "Mostrar" or the essay checkbox never reads
    the data file again.
The days since the last sample are worked out here, at render, from "today": nothing is stored.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from dash import html
import dash_bootstrap_components as dbc

from config.settings import get_settings
from dashboard.components.labels import display_component_name, essay_label, status_label
from dashboard.components.oil_table import DESC, PAGE_SIZE, new_revision, page_slice, pager, sortable_th
from dashboard.components.oil_ui import (
    estado_badge,
    is_preview_tab,
    kpi_tile,
    page_header,
    preview_pill,
    severity_style,
)
from src.data import component_analysis as ca
from src.data.loaders import load_oil_classified
from src.data.sampling_frequency import normalize_name
from src.i18n import t, t_or, vocab
from src.utils.dash_ids import id_text
from src.utils.logger import get_logger

logger = get_logger(__name__)

TAB_VALUE = "component-analysis"       # the value of this tab in the Monitor de Aceite tab bar (tab_oil.py)
TABLE = "ca"                           # prefix of the matrix's stores and pattern ids
SOURCE_ID = "ca-source"
COMPONENT_ID = "ca-component"          # the store holding the selected option
BUTTON_TYPE = "ca-component"           # pattern id type of the segmented control's buttons
OPEN_TYPE = f"{TABLE}-open"            # pattern id type of every cell that opens a report
TABLE_ID = "ca-table-container"
FALLBACK_COMPONENTS = ("motor", "transmision", "convertidor", "diferencial")

# First click on a header: unit and anomaly A-Z, everything else biggest / worst first.
FIRST_DIRS = {"unit": "asc", "anomaly": "asc", "*": DESC}

MISSING = "—"

# Fixed by the requirement: the stacked bars of the anomaly card (by estado) and the essay card (by level).
ESTADO_FILL = {ca.ANORMAL: "#dc2626", ca.ALERTA: "#f59e0b"}
LEVEL_FILL = {ca.CONDENATORIO: "#dc2626", ca.MARGINAL: "#f59e0b"}
# "Antigüedad de la Última Muestra": a blue ramp (dark to light) for the current buckets, amber for the stale one.
_BLUES = ("#1e40af", "#2563eb", "#3b82f6", "#60a5fa", "#93c5fd", "#bfdbfe")
STALE_FILL = "#f59e0b"

_TREND_TEXT = {ca.WORSENING: "component_analysis.tendencia_empeorando",
               ca.IMPROVING: "component_analysis.tendencia_mejorando",
               ca.UNCHANGED: "component_analysis.tendencia_sin_cambio"}


# ---------------------------------------------------------------------------------------------
# Words of each option
# ---------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Words:
    """The words of one option of the selector, from the i18n catalog (Spanish needs the article and
    the preposition to agree with the noun: "los motores" / "las transmisiones")."""
    key: str
    title: str           # Motor
    singular: str        # motor
    plural: str          # motores
    the_plural: str      # los motores
    of_singular: str     # del motor

    @property
    def plural_cap(self) -> str:
        return self.plural[:1].upper() + self.plural[1:]


def words(key: str) -> Words:
    """The words of an option; an option with no catalog entry falls back to its own key."""
    fallback = str(key).replace("_", " ")

    def pick(kind: str, default: str) -> str:
        return t_or(f"component_analysis.{kind}_{key}", default)

    return Words(
        key=key, title=pick("componente", fallback.title()), singular=pick("singular", fallback),
        plural=pick("plural", fallback), the_plural=pick("articulo_plural", fallback), of_singular=pick("del_singular", fallback),
    )


def criticality_text(config: ca.AnalysisConfig, key: str) -> str:
    level = t(f"component_analysis.criticidad_{config.spec(key).criticality}")
    return t("component_analysis.criticidad", nivel=level)


def group_label(group: Optional[str]) -> str:
    """The essay's group as a word (data: "Fisico Quimico"); a group with no catalog entry shows as it came."""
    if not group:
        return ""
    return t_or("component_analysis.grupo_" + normalize_name(group).replace(" ", "_"), group)


# ---------------------------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------------------------

def _message(key: str, component: Optional[str] = None, as_of: Optional[str] = None, **extra) -> dict:
    return {"rev": new_revision(), "message": key, "component": component, "as_of": as_of, "rows": [], **extra}


def build_source(client, fleet, component_key) -> dict:
    """What the tab shows for a client, a fleet and an option of the selector.

    `rows` are the latest samples of every unit + component of that option in the fleet (see
    `ca.build_component_rows`). With no Flota selected nothing is displayed (as in the other tabs), but
    the data date still is. `message` is the i18n key of an empty-state text; `as_of` is the client's
    latest reportDate.
    """
    try:
        config = ca.load_config()
    except ca.ComponentAnalysisConfigError as exc:
        logger.error("Component analysis configuration: %s", exc)
        return _message("component_analysis.error_de_configuracion", detail=str(exc))
    spec = config.spec(component_key)
    if not client:
        return _message("fleet_overview.select_client", spec.key)
    if not get_settings().get_classified_reports_path(client.lower()).exists():
        return _message("lab_compliance_callbacks.sin_datos_disponibles", spec.key)
    try:
        classified = load_oil_classified(client)
        as_of = ca.latest_report_text(classified)
        if not fleet:
            return _message("component_analysis.seleccione_una_flota", spec.key, as_of)
        rows = ca.build_component_rows(classified, spec, fleet)
        if not rows:
            return _message("component_analysis.sin_componentes", spec.key, as_of, fleet=fleet)
        return {"rev": new_revision(), "message": None, "component": spec.key, "as_of": as_of, "fleet": fleet,
                "rows": rows}
    except Exception:
        logger.exception("Component analysis error")
        return _message("component_analysis.error_al_cargar", spec.key)


def filter_options(client) -> List[str]:
    """The fleets (machine types) of the client."""
    if not client or not get_settings().get_classified_reports_path(client.lower()).exists():
        return []
    try:
        return ca.fleets_of(load_oil_classified(client))
    except Exception:
        logger.exception("Component analysis filter options error")
        return []


def control_data(source: Optional[dict], show: Optional[str]) -> dict:
    """The matrix's paging store: how many rows the "Mostrar" option lists. A new `rev` on every call
    sends the matrix back to page 1 (it keeps its sort)."""
    rows = (source or {}).get("rows") or []
    return {"rev": new_revision(), "n_rows": len(ca.shown_rows(rows, show or ca.SHOW_ALERTA_ANORMAL))}


def default_component() -> str:
    """The option the tab opens on: the first one of the configuration (the first of the standard four
    when the configuration cannot be read; the tab then says why)."""
    try:
        return ca.load_config().default_component()
    except ca.ComponentAnalysisConfigError:
        return FALLBACK_COMPONENTS[0]


def _words_of(source: Optional[dict]) -> Words:
    return words((source or {}).get("component") or default_component())


# ---------------------------------------------------------------------------------------------
# Header, KPI tiles
# ---------------------------------------------------------------------------------------------

def render_header(source: Optional[dict]) -> html.Div:
    """Page title (with the Preview pill), subtitle and the data-freshness line."""
    w = _words_of(source)
    as_of = (source or {}).get("as_of")
    caption = (t("component_analysis.frescura_con_fecha", fecha=as_of, singular=w.singular) if as_of
               else t("component_analysis.frescura_sin_fecha", singular=w.singular))
    return page_header(
        t("component_analysis.titulo", componente=w.title),
        subtitle=t("component_analysis.subtitulo", articulo_plural=w.the_plural),
        caption=caption,
        badge=preview_pill() if is_preview_tab(TAB_VALUE) else None,
    )


def pct_text(count: int, total: int) -> str:
    """A whole percent; "<1" for a non-zero share that would round to nothing."""
    if not total:
        return "0"
    pct = count * 100.0 / total
    return "<1" if count and pct < 0.5 else str(int(pct + 0.5))


def _share(count: int, total: int) -> float:
    return count * 100.0 / total if total else 0.0


def render_kpis(source: dict, today=None) -> dbc.Row:
    """Five tiles over every component of the fleet: how many there are, Anormal, Alerta, Normal, and the
    ones whose last sample is older than the stale threshold."""
    config = ca.load_config()
    rows = source["rows"]
    w = _words_of(source)
    total = len(rows)
    counts = ca.estado_counts(rows)
    stale = ca.stale_count(rows, config, today)
    of_total = lambda n: t("component_analysis.kpi_porcentaje", pct=pct_text(n, total), articulo_plural=w.the_plural)

    tiles = [
        dict(label=w.plural_cap, value=total, tier=None, chip=t("component_analysis.kpi_con_muestra"),
             pct=100.0 if total else 0.0, caption=t("component_analysis.kpi_en_la_flota"), icon="fa-cubes"),
        dict(label=status_label(ca.ANORMAL), value=counts[ca.ANORMAL], tier="alto", chip=status_label(ca.ANORMAL),
             pct=_share(counts[ca.ANORMAL], total), caption=of_total(counts[ca.ANORMAL]), icon="fa-exclamation-circle"),
        dict(label=status_label(ca.ALERTA), value=counts[ca.ALERTA], tier="atencion", chip=status_label(ca.ALERTA),
             pct=_share(counts[ca.ALERTA], total), caption=of_total(counts[ca.ALERTA]), icon="fa-exclamation-triangle"),
        dict(label=status_label(ca.NORMAL), value=counts[ca.NORMAL], tier="bajo", chip=status_label(ca.NORMAL),
             pct=_share(counts[ca.NORMAL], total), caption=of_total(counts[ca.NORMAL]), icon="fa-check-circle"),
        dict(label=t("component_analysis.kpi_desactualizado"), value=stale, tier=None,
             chip=t("component_analysis.kpi_revisar"), pct=_share(stale, total), icon="fa-clock",
             caption=t("component_analysis.kpi_desactualizado_caption", dias=config.stale_days)),
    ]
    cols = [
        dbc.Col(
            kpi_tile(tile["label"], str(int(tile["value"])), icon=tile["icon"], tier=tile["tier"], chip=tile["chip"],
                     gauge_pct=tile["pct"], caption=tile["caption"]),
            xs=12, sm=6, lg=True, className="mb-3",
        )
        for tile in tiles
    ]
    return dbc.Row(cols, className="g-3 oil-kpis--aligned")


# ---------------------------------------------------------------------------------------------
# Cards
# ---------------------------------------------------------------------------------------------

def _legend(entries) -> html.Ul:
    """Color key: a swatch and its word per entry."""
    return html.Ul(
        [html.Li([html.Span(className="oil-legend__swatch", style={"background": fill}, **{"aria-hidden": "true"}),
                  html.Span(text)], className="oil-legend__item") for text, fill in entries],
        className="oil-legend",
    )


def _card(title: str, subtitle: Optional[str], body: list) -> dbc.Card:
    return dbc.Card(dbc.CardBody([
        html.H5(title, className="fw-bold mb-1"),
        html.P(subtitle, className="oil-caption mb-3") if subtitle else None,
        *body,
    ]), className="shadow-sm mb-4 h-100")


def _ramp(n: int) -> List[str]:
    """`n` blues from dark to light."""
    if n <= 0:
        return []
    if n == 1:
        return [_BLUES[1]]
    step = (len(_BLUES) - 2) / (n - 1)
    return [_BLUES[min(len(_BLUES) - 1, int(round(i * step)))] for i in range(n)]


def age_label(bucket: dict, config: ca.AnalysisConfig) -> str:
    if bucket["hi"] is None:
        return t("component_analysis.edad_mas_de", dias=config.stale_days)
    if bucket["lo"] == 0:
        return t("component_analysis.edad_hasta", hasta=bucket["hi"])
    return t("component_analysis.edad_rango", desde=bucket["lo"], hasta=bucket["hi"])


def render_age_card(source: dict, today=None) -> dbc.Card:
    """"Antigüedad de la Última Muestra": every component of the fleet in one stacked bar by days since
    its last sample. The last bucket is the one the "Estado desactualizado" tile counts."""
    config = ca.load_config()
    rows = source["rows"]
    w = _words_of(source)
    total = len(rows)
    buckets = ca.age_buckets(rows, config, today)
    fills = [*_ramp(len(buckets) - 1), STALE_FILL]
    segments, legend = [], []
    for bucket, fill in zip(buckets, fills):
        label = age_label(bucket, config)
        segments.append(html.Span(className="oil-agebar__seg", style={
            "width": f"{_share(bucket['count'], total):.2f}%", "background": fill}))
        legend.append((t("component_analysis.edad_leyenda", etiqueta=label, n=bucket["count"],
                         pct=pct_text(bucket["count"], total)), fill))
    # The legend carries every figure as text, so the bar itself is decoration for assistive technology.
    return _card(
        t("component_analysis.edad_titulo"),
        t("component_analysis.edad_subtitulo", singular=w.singular),
        [html.Div(segments, className="oil-agebar", **{"aria-hidden": "true"}),
         _legend(legend),
         html.P(t("component_analysis.edad_nota", dias=config.stale_days, del_singular=w.of_singular),
                className="oil-footnote mb-0")],
    )


def _hbar(name, figures: str, parts, top: int, chip=None) -> html.Li:
    """One horizontal bar of a ranking: its name (and chip), its figures spelled out and the stacked bar,
    scaled so the biggest total fills the track. `parts` is `[(count, fill)]`."""
    segments = [html.Span(className="oil-hbar__seg", style={"width": f"{_share(count, top):.2f}%", "background": fill})
                for count, fill in parts if count]
    return html.Li([
        html.Div([html.Span([name, chip] if chip is not None else name, className="oil-hbar__name"),
                  html.Span(figures, className="oil-hbar__figures")], className="oil-hbar__head"),
        html.Div(segments, className="oil-hbar__track", **{"aria-hidden": "true"}),
    ], className="oil-hbar")


def render_anomaly_card(source: dict) -> dbc.Card:
    """"Tipos de Anomalía más Frecuentes", over the components in Alerta or Anormal."""
    w = _words_of(source)
    entries = ca.anomaly_counts(source["rows"], unclassified=t("component_analysis.sin_clasificar"))
    if not entries:
        body = [html.P(t("component_analysis.anomalias_vacio", plural=w.plural), className="text-muted mb-0")]
    else:
        top = max(e["total"] for e in entries)
        items = []
        for e in entries:
            abnormal = (t("component_analysis.n_anormal_uno", n=e["anormal"]) if e["anormal"] == 1
                        else t("component_analysis.n_anormales", n=e["anormal"]))
            figures = t("component_analysis.anomalia_figuras", total=e["total"], anormal=abnormal,
                        alerta=t("component_analysis.n_alerta", n=e["alerta"]))
            items.append(_hbar(vocab(e["type"]), figures,
                               [(e["anormal"], ESTADO_FILL[ca.ANORMAL]), (e["alerta"], ESTADO_FILL[ca.ALERTA])], top))
        body = [html.Ul(items, className="oil-hbars"),
                _legend([(status_label(ca.ANORMAL), ESTADO_FILL[ca.ANORMAL]),
                         (status_label(ca.ALERTA), ESTADO_FILL[ca.ALERTA])])]
    return _card(t("component_analysis.anomalias_titulo"),
                 t("component_analysis.alcance_alerta_anormal", plural=w.plural_cap), body)


def render_essay_card(source: dict, include_all: bool = False) -> dbc.Card:
    """"Ensayos Fuera de Límite más Frecuentes", over the components in Alerta or Anormal."""
    w = _words_of(source)
    entries = ca.essay_counts(source["rows"], include_all)
    if not entries:
        body = [html.P(t("component_analysis.ensayos_vacio"), className="text-muted mb-0")]
    else:
        top = max(e["n"] for e in entries)
        items = []
        for e in entries:
            key = "component_analysis.ensayo_figuras_uno" if e["n"] == 1 else "component_analysis.ensayo_figuras"
            group = group_label(e["group"])
            items.append(_hbar(
                essay_label(e["essay"]), t(key, n=e["n"], cond=e["cond"], marg=e["marg"]),
                [(e["cond"], LEVEL_FILL[ca.CONDENATORIO]), (e["marg"], LEVEL_FILL[ca.MARGINAL])], top,
                chip=html.Span(group, className="kpi-chip oil-neutral-chip ms-2") if group else None))
        body = [html.Ul(items, className="oil-hbars"),
                _legend([(t("component_analysis.nivel_condenatorio"), LEVEL_FILL[ca.CONDENATORIO]),
                         (t("component_analysis.nivel_marginal"), LEVEL_FILL[ca.MARGINAL])]),
                html.P(t("component_analysis.ensayos_leyenda_nota"), className="oil-footnote mb-0")]
    return _card(t("component_analysis.ensayos_titulo"),
                 t("component_analysis.alcance_alerta_anormal", plural=w.plural_cap), body)


# ---------------------------------------------------------------------------------------------
# Matrix
# ---------------------------------------------------------------------------------------------

# A table of 30 rows x ~26 columns is ~1,700 Dash components if every cell wraps its text in a span or
# a div, and Dash's renderer gets slow (a multi-second freeze) as the component count grows. So a cell
# is a bare <td> holding a string wherever it can be: a dash carries its meaning in `aria-label` on the
# cell itself, and a two-line cell is one string with a line break (`white-space: pre`) whose
# second line is styled apart from the first (`::first-line`, see oil_monitor.css).


def _dash_cell(label: str, align: str = "center") -> html.Td:
    """A cell with nothing to show: a dash, named for assistive technology, with nothing to click."""
    return html.Td(MISSING, className=f"oil-col-{align} oil-cell-empty", **{"aria-label": label})


def two_lines(first: str, second: str) -> str:
    return f"{first}\n{second}"


def hours_cell(value: Optional[float]) -> html.Td:
    """"12,345 h", or a dash when the component has no hours."""
    if value is None:
        return _dash_cell(t("component_analysis.sin_dato"))
    return html.Td(t("component_analysis.horas", horas=f"{value:,.0f}"), className="oil-col-center")


def _opener(unit: str, component: str, cell: str) -> dict:
    """The id of a button that opens the report of one row. The unit and component written here, not the
    row's position in the page, say which report: page 2, a re-sorted or a filtered table open the right one.
    The parts are written with `id_text` (plain ASCII, see src/utils/dash_ids.py) and read back with `from_id_text`."""
    return {"type": OPEN_TYPE, "unit": id_text(unit), "component": id_text(component), "cell": id_text(cell)}


def _level_cell(row: dict, essay: str):
    level = row["levels"].get(essay)
    if level is None:
        # Not out of limit: a plain dash, neither clickable nor focusable.
        return _dash_cell(t("component_analysis.ensayo_dentro_de_limite"))
    condenatorio = level == ca.CONDENATORIO
    word = t("component_analysis.nivel_condenatorio" if condenatorio else "component_analysis.nivel_marginal")
    tone = severity_style("alto" if condenatorio else "atencion")
    return html.Td(html.Button(
        t("component_analysis.nivel_cond_abrev" if condenatorio else "component_analysis.nivel_marg_abrev"),
        id=_opener(row["unit_id"], row["component"], essay), className="oil-level-pill", type="button", n_clicks=0,
        style=tone,
        **{"aria-label": t("component_analysis.celda_ensayo", ensayo=essay_label(essay), nivel=word,
                           unidad=row["unit_id"], componente=display_component_name(row["component"]))},
    ), className="oil-col-center")


def _trend_cell(row: dict) -> html.Td:
    trend = row["trend"]
    if trend is None:
        return html.Td(t("component_analysis.sin_muestra_anterior"), className="oil-col-center oil-trend oil-trend--none")
    before = (t("component_analysis.estado_actual", estado=status_label(row["estado"])) if trend == ca.UNCHANGED
              else t("component_analysis.antes", estado=status_label(row["prev_estado"])))
    return html.Td(two_lines(t(_TREND_TEXT[trend]), before),
                   className=f"oil-col-center oil-two-line oil-trend oil-trend--{trend}")


def _matrix_row(row: dict, essays: List[str]) -> html.Tr:
    unit, component = row["unit_id"], row["component"]
    if row["anomaly"]:
        anomaly = html.Td(vocab(row["anomaly"]), className="oil-col-left")
    elif row["estado"] == ca.NORMAL:
        anomaly = _dash_cell(t("component_analysis.sin_anomalia"), "left")
    else:
        anomaly = html.Td(t("component_analysis.sin_clasificar"), className="oil-col-left")
    n_key = "component_analysis.n_ensayo_uno" if row["n_essays"] == 1 else "component_analysis.n_ensayos"
    when = t("component_analysis.fecha_dias", fecha=row["sample_date"], dias=row["days"])
    last = (html.Td(two_lines(when, t("component_analysis.desactualizada")),
                    className="oil-col-center oil-two-line oil-two-line--stale")
            if row["stale"] else html.Td(when, className="oil-col-center"))
    return html.Tr([
        html.Th([
            html.Button(unit, id=_opener(unit, component, "unit"), className="oil-unit-btn", type="button", n_clicks=0,
                        title=t("component_analysis.abrir_reporte", unidad=unit, componente=display_component_name(component))),
            html.Div(display_component_name(component), className="oil-subline", title=display_component_name(component)),
        ], scope="row", className="oil-col-left oil-frozen oil-frozen--unit"),
        html.Td(estado_badge(row["estado"], solid=True), className="oil-estado-cell oil-frozen oil-frozen--estado"),
        anomaly,
        html.Td(two_lines(t(n_key, n=row["n_essays"]),
                          t("component_analysis.ensayos_niveles", cond=row["n_cond"], marg=row["n_marg"])),
                className="oil-col-center oil-two-line"),
        last,
        _trend_cell(row),
        hours_cell(row["component_hours"]),
        hours_cell(row["oil_hours"]),
        *[_level_cell(row, essay) for essay in essays],
    ])


def _matrix_header(essays: List[str], view: Optional[dict]) -> html.Tr:
    fixed = [
        ("unit", t("component_analysis.col_unidad"), "left", "oil-frozen oil-frozen--unit"),
        ("estado", t("component_analysis.col_estado"), "center", "oil-frozen oil-frozen--estado"),
        ("anomaly", t("component_analysis.col_anomalia"), "left", ""),
        ("essays", t("component_analysis.col_ensayos"), "center", ""),
        ("last", t("component_analysis.col_ultima_muestra"), "center", ""),
        ("trend", t("component_analysis.col_anterior"), "center", ""),
        ("component_hours", t("component_analysis.col_horas_componente"), "center", ""),
        ("oil_hours", t("component_analysis.col_horas_aceite"), "center", ""),
    ]
    return html.Tr(
        [sortable_th(TABLE, col, label, view, align=align, extra_class=extra) for col, label, align, extra in fixed]
        + [sortable_th(TABLE, ca.essay_column(essay), essay_label(essay), view) for essay in essays]
    )


def matrix_title(source: Optional[dict]) -> str:
    return t("component_analysis.matriz_titulo", componente=_words_of(source).title)


def render_matrix(source: Optional[dict], view: Optional[dict], show: Optional[str], include_all: bool, today=None):
    """`(title, rows chip, matrix block)` for the stored data, the view (sort, page) and the controls."""
    title = matrix_title(source)
    if not source:
        return title, "", html.Div()
    if source.get("message"):
        text = t(source["message"], plural=_words_of(source).plural) + (f" {source['detail']}" if source.get("detail") else "")
        return title, "", html.P(text, className="text-muted text-center py-4")

    config = ca.load_config()
    w = _words_of(source)
    rows = source["rows"]
    shown = ca.shown_rows(rows, show or ca.SHOW_ALERTA_ANORMAL)
    chip = html.Span(t("component_analysis.matriz_chip", n=len(shown), m=len(rows), plural=w.plural),
                     className="kpi-chip oil-neutral-chip ms-2")
    if not shown:
        return title, chip, html.P(t("component_analysis.sin_filas_mostrar", plural=w.plural),
                                   className="text-muted text-center py-4")

    essays = [e["essay"] for e in ca.essay_counts(rows, include_all)]       # the columns: the essay card's order
    ordered = ca.matrix_rows(shown, config, include_all=include_all, today=today)
    sort = (view or {}).get("sort") or {}
    ordered = ca.sort_matrix(ordered, sort.get("col"), sort.get("dir") == DESC)
    page_rows, page, _ = page_slice(ordered, view)

    table = html.Div(
        html.Table([html.Thead(_matrix_header(essays, view)),
                    html.Tbody([_matrix_row(row, essays) for row in page_rows])],
                   className="oil-table oil-table--frozen oil-table--frozen-2", **{"aria-label": title}),
        className="oil-table-wrap",
    )
    return title, chip, html.Div([table, pager(TABLE, page=page, total_rows=len(ordered), page_size=PAGE_SIZE)])
