"""PDF download of the selected oil report (Monitoreo > Aceite > Detalle de reporte).

`build_oil_report` turns the selected sample into the `OilReportPdf` that
dashboard/components/oil_report_pdf.py draws. It adds no calculation of its own: the status, the
critical tests, the AI text, the series, the critical limits and the default range all come from the
helpers the tab itself uses (reports_callbacks.py, oil_charts.py), so the PDF and the screen cannot say
different things about one report.

One list drives every count and name in the PDF: the tests the report stores as outside their limits
(`breached_essays`, the list the dashboard's "Ensayos críticos" reads), each with the severity and
direction stored with it. The header's count and names, the highlighted rows of the table, the comparison
with the previous sample and the out-of-limit marks in the charts' legends are all read from it; a
test's status is never re-derived from the limits file (the two disagree on thousands of tests).

The PDF always describes the *selected* report, not the latest one, and its time series always use
the default window (the last 6 months or last 3 samples, whichever reaches further back, ending on the
sample's date: the same rule and the same history as the dashboard), whatever range is set on screen.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import dash_bootstrap_components as dbc
import pandas as pd
from dash import Input, Output, State, dcc
from dash.exceptions import PreventUpdate

from config.settings import get_settings
from dashboard.callbacks.reports_callbacks import (
    _format_anomaly_type,
    _parse_oil_ai_sections,
    _split_actions,
    parse_breached_entries,
    resolve_breached_essays,
)
from dashboard.components.labels import display_component_name, essay_label
from dashboard.components.oil_charts import (
    TIME_SERIES_CHARTS,
    classify_four_limit_value,
    clip_history_to_window,
    collect_chart_series,
    default_time_series_window,
    get_essay_limits_four,
    unit_history,
)
from dashboard.components.oil_report_pdf import (
    AiMessage,
    ChartLimit,
    ChartSeries,
    ChartSpec,
    Classification,
    Comparison,
    HistoryRow,
    Identity,
    OilReportPdf,
    TableGroup,
    TableRow,
    UNIT_DECIMALS,
    ZeroStrip,
    format_number,
    render_oil_report_pdf,
)
from src.data.loaders import _data_path, load_essays_mapping, load_oil_classified, load_stewart_limits_four
from src.i18n import t, vocab
from src.i18n.data_text import localized_value
from src.utils.logger import get_logger

logger = get_logger(__name__)

# The logo of page 1 (top right) is an asset to be provided: drop it here and the slot appears.
# Without one the slot is omitted. PNG or JPEG.
LOGO_DIR = Path(__file__).resolve().parents[1] / "assets" / "pdf"
LOGO_NAMES = ("oil_report_logo.png", "oil_report_logo.jpg", "oil_report_logo.jpeg")

# History of samples: whichever is SHORTER of the examined sample plus its previous 5, and the samples of
# the last 6 calendar months (examined date included, boundary inclusive).
HISTORY_MAX_SAMPLES = 6
HISTORY_MONTHS = 6

# The values table's groups and members: (data column, element symbol). The additives continue with the
# remaining "Aditivo" elements of the team's mapping (essays_elements.xlsx); anything else that is
# neither here nor in those goes to "Otros ensayos".
ESSAY_GROUPS: Tuple[Tuple[str, Tuple[Tuple[str, Optional[str]], ...]], ...] = (
    ("oil_report_pdf.group_wear", (
        ("Hierro", "Fe"), ("Índice PQ", None), ("Cobre", "Cu"), ("Estaño", "Sn"),
        ("Cromo", "Cr"), ("Plomo", "Pb"), ("Níquel", "Ni"), ("Aluminio", "Al"),
    )),
    ("oil_report_pdf.group_contamination", (
        ("Silicio", "Si"), ("Sodio", "Na"), ("Potasio", "K"), ("Agua", None), ("Combustible", None),
    )),
    ("oil_report_pdf.group_additives", (("Boro", "B"), ("Magnesio", "Mg"), ("Calcio", "Ca"))),
    ("oil_report_pdf.group_condition", (("Viscocidad", None), ("Hollín", None), ("Oxidación", None))),
)
ADDITIVES_KEY = "oil_report_pdf.group_additives"
OTHERS_KEY = "oil_report_pdf.group_others"
# Mapping groups whose tests are elements, measured in ppm.
ELEMENT_MAPPING_GROUPS = frozenset({"Desgaste", "Contaminante", "Aditivo"})

# Units of the lab report, as the rest of the product states them (src/data/predictive_catalog.py
# OIL_LABELS: metals ppm, Hollín/Agua/Combustible %, Viscosidad cSt, Oxidación Abs/cm). The PQ index
# has no unit of its own: the table calls it "índice" (INDEX_UNIT_ESSAYS, translated when printed).
_PPM = "ppm"
ESSAY_UNITS = {
    "Hierro": _PPM, "Cobre": _PPM, "Estaño": _PPM, "Cromo": _PPM, "Plomo": _PPM, "Níquel": _PPM,
    "Aluminio": _PPM, "Silicio": _PPM, "Sodio": _PPM, "Potasio": _PPM, "Boro": _PPM, "Magnesio": _PPM,
    "Calcio": _PPM, "Agua": "%", "Combustible": "%", "Hollín": "%", "Viscocidad": "cSt", "Oxidación": "Abs/cm",
}
INDEX_UNIT_ESSAYS = frozenset({"Índice PQ"})

# Short names in the charts' limit labels ("PQ 131"): the element symbol, PQ for the index.
ESSAY_SYMBOLS = {name: symbol for _title, members in ESSAY_GROUPS for name, symbol in members if symbol}
ESSAY_SYMBOLS["Índice PQ"] = "PQ"

# Four-limit tiers -> table states. Only used for a report that stores just the NAMES of its out-of-limit
# tests (legacy list, or the dashboard's own recalculation): the severity then has no other source.
_STATE_BY_TIER = {
    "Normal": "normal",
    "Superior Condenatorio": "high",
    "Inferior Condenatorio": "low",
    "Superior Marginal": "marginal_high",
    "Inferior Marginal": "marginal_low",
}


class ReportNotFound(Exception):
    """The selected sample does not exist (any more) in the classified reports."""


def find_logo() -> Optional[Path]:
    for name in LOGO_NAMES:
        path = LOGO_DIR / name
        if path.is_file():
            return path
    return None


def _today_iso() -> str:
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/Santiago")).date().isoformat()
    except Exception:
        return date.today().isoformat()


def _number_or_none(value) -> Optional[float]:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(number) else number


# The data spells a few names without their accents. The PDF maps them to the right spelling (the
# source files keep theirs, other consumers index by them).
ESSAY_NAME_FIXES = {"Numero Total Basico": "Número total básico"}
WORD_FIXES = {"camion": "Camión", "numero": "Número", "basico": "básico"}


def _display_essay(name: str) -> str:
    shown = essay_label(vocab(name))
    return ESSAY_NAME_FIXES.get(shown, shown)


def _display_name(value) -> str:
    """A family or component name as a person writes it: the dashboard's accent/case rules (Transmisión,
    Sistema de Dirección) plus the few words the data spells without an accent (Camión)."""
    shown = display_component_name(value)
    return " ".join(WORD_FIXES.get(word.casefold(), word) for word in shown.split(" "))


def _hours_text(value) -> str:
    """A hour meter with the PDF's one number rule (hours: no decimals): "18.418 hrs"; N/A without one."""
    number = _number_or_none(value)
    return "N/A" if number is None else f"{format_number(number, UNIT_DECIMALS['hrs'])} hrs"


def _essay_title(name: str, symbol: Optional[str]) -> str:
    return f"{_display_essay(name)} ({symbol})" if symbol else _display_essay(name)


def _as_text(value, default: str = "N/A") -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return default
    text = str(value).strip()
    return text or default


def pdf_filename(equipo: str, component: str, sample_day: pd.Timestamp) -> str:
    """`{Equipo}_{Componente}_{Fecha Muestra}.pdf`: CSL006_Mando-Final-Derecho_2026-11-14.pdf."""
    def clean(text: str) -> str:
        return re.sub(r"[^\w\-]+", "-", str(text).strip(), flags=re.UNICODE).strip("-") or "reporte"
    return f"{clean(str(equipo).upper())}_{clean(str(component).title())}_{sample_day.strftime('%Y-%m-%d')}.pdf"


# ---------------------------------------------------------------------------
# The list of out-of-limit tests: one source for header, table, legends and comparison
# ---------------------------------------------------------------------------


@dataclass
class Flag:
    """A test the report stores as outside its limits."""
    name: str
    state: str                       # high | low | marginal_high | marginal_low
    limit: Optional[float] = None    # the limit it crossed, as stored with the report
    value: Optional[float] = None    # its value, as stored with the report


def _table_state(value: Optional[float], limits: Optional[dict]) -> Optional[str]:
    """The four-limit tier of a value as a table state (only for names-only reports, see above)."""
    if value is None or not limits or limits.get("LSM") is None or limits.get("LSC") is None:
        return None
    tier = classify_four_limit_value(value, limits.get("LIC"), limits.get("LIM"), limits["LSM"], limits["LSC"])
    return _STATE_BY_TIER.get(tier)


def _flag_state(entry: dict) -> str:
    """Table state of a stored entry: its threshold says Marginal or critical (Crítico / Condenatorio),
    its direction says above (alto) or below (bajo) the limit."""
    marginal = str(entry.get("threshold", "")).strip().casefold() == "marginal"
    below = str(entry.get("direction", "upper")).strip().casefold() in ("lower", "inferior", "low", "bajo")
    return ("marginal_" if marginal else "") + ("low" if below else "high")


def report_flags(sample, limits, client, familia, component, comp_limits=None) -> List[Flag]:
    """The tests `sample` has outside their limits, in the order the dashboard lists them: the stored
    `breached_essays` (or, when it is empty, the ones the dashboard recalculates from the limits), each
    with the severity and direction stored with it."""
    names, _count, _warning = resolve_breached_essays(sample, limits, client, familia, component)
    stored = {}
    for entry in parse_breached_entries(sample.get("breached_essays")):
        stored.setdefault(entry["essay"], entry)
    flags: List[Flag] = []
    for name in dict.fromkeys(names):
        entry = stored.get(name)
        if entry is not None and entry.get("threshold"):
            flags.append(Flag(name, _flag_state(entry), _number_or_none(entry.get("limit")), _number_or_none(entry.get("value"))))
            continue
        value = _number_or_none(sample.get(name))
        essay_limits = get_essay_limits_four(comp_limits, name, sample.get("oilHourRange", "UNKNOWN")) if comp_limits else None
        state = _table_state(value, essay_limits)
        flags.append(Flag(name, state if state not in (None, "normal") else "high", None, value))
    return flags


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def _find_sample(df: pd.DataFrame, familia, equipo, component, sample_date) -> pd.Series:
    """The selected sample, found the way the tab finds it (by calendar day)."""
    day = pd.to_datetime(sample_date).strftime("%Y-%m-%d")
    days = pd.to_datetime(df["sampleDate"]).dt.strftime("%Y-%m-%d")
    match = df[(df["machineName"] == familia) & (df["unitId"] == equipo)
               & (df["componentName"] == component) & (days == day)]
    if match.empty:
        raise ReportNotFound(f"{familia}/{equipo}/{component}/{day}")
    return match.iloc[0]


def _unit_key(name: str, mapping_groups: Dict[str, str]) -> Optional[str]:
    """The unit of a test (None: it has none we know), "índice" being the PQ index's."""
    if name in INDEX_UNIT_ESSAYS:
        return "índice"
    if name in ESSAY_UNITS:
        return ESSAY_UNITS[name]
    return _PPM if mapping_groups.get(name) in ELEMENT_MAPPING_GROUPS else None


def _unit_text(key: Optional[str]) -> str:
    return "—" if key is None else (t("oil_report_pdf.unit_index") if key == "índice" else key)


@dataclass
class Limits:
    """The thresholds of one test, the single source of both the table's limit columns and the charts'
    limit lines."""
    lower_marginal: Optional[float] = None
    lower_critical: Optional[float] = None
    upper_marginal: Optional[float] = None
    upper_critical: Optional[float] = None

    def any(self) -> bool:
        return any(v is not None for v in (self.lower_marginal, self.lower_critical, self.upper_marginal, self.upper_critical))


def resolve_limits(name: str, comp_limits: dict, oil_hour_range, flag: Optional[Flag]) -> Limits:
    """A test's thresholds: those of the limits file (LIM / LIC below, LSM / LSC above; the lower ones only
    when both exist, as on the dashboard), with the limit the report stored for its out-of-limit status
    taking the place of the matching one. The status comes from that stored limit (the report was
    classified against it), so the table shows the very value that explains it; the other threshold of the
    test and the limits of every test that is not out of limit stay those of the file."""
    limits = Limits()
    file = get_essay_limits_four(comp_limits, name, oil_hour_range) if comp_limits else None
    if file:
        if file.get("LIC") is not None and file.get("LIM") is not None:
            limits.lower_critical, limits.lower_marginal = file["LIC"], file["LIM"]
        limits.upper_marginal, limits.upper_critical = file.get("LSM"), file.get("LSC")
    if flag is not None and flag.limit is not None:
        marginal, below = flag.state.startswith("marginal"), flag.state.endswith("low")
        attribute = ("lower_" if below else "upper_") + ("marginal" if marginal else "critical")
        setattr(limits, attribute, flag.limit)
    return limits


def _unit_decimals(key: Optional[str]) -> Optional[int]:
    return UNIT_DECIMALS.get(key) if key else None


def _ordered_flags(groups: List[TableGroup]) -> List[Tuple[str, str]]:
    """(test, state) of every out-of-limit row of the table: critical (▲) first and then marginal (△),
    each in the table's order. The header's count and list are this list, the highlighted rows are its rows."""
    flagged = [(row.essay, row.state) for group in groups for row in group.rows if row.state not in (None, "normal")]
    return [f for f in flagged if f[1] in ("high", "low")] + [f for f in flagged if f[1] not in ("high", "low")]


def _classification(sample, ordered: List[Tuple[str, str]]) -> Classification:
    status = sample.get("report_status", "Normal")
    detailed = str(status).strip().casefold() in ("alerta", "anormal")
    if not detailed:
        return Classification(status=_as_text(status, "N/A"))
    return Classification(
        status=_as_text(status, "N/A"),
        anomaly=_format_anomaly_type(sample.get("anomalyType")),
        out_of_limit=len(ordered),
        flagged=[(_display_essay(name), state) for name, state in ordered],
        detailed=True,
    )


def _comparison(sample, previous, ordered, previous_flags) -> Optional[Comparison]:
    """Against the previous sample, on the same lists the header and the table use. "Critical" is ▲ only:
    a test is a new critical one when it is ▲ now and was not ▲ before; a new marginal one when it is △ now
    and was not out of limit before."""
    if previous is None:
        return None
    before = {flag.name: flag.state for flag in previous_flags}
    now = dict(ordered)
    critical = ("high", "low")
    days = _number_or_none(sample.get("daysSincePrevious"))
    if days is None:
        days = (pd.to_datetime(sample["sampleDate"]).normalize() - pd.to_datetime(previous["sampleDate"]).normalize()).days
    return Comparison(
        previous_date=pd.to_datetime(previous["sampleDate"]).strftime("%Y-%m-%d"),
        previous_status=_as_text(previous.get("report_status"), "N/A"),
        days=int(days),
        new_critical=[_display_essay(n) for n, st in ordered if st in critical and before.get(n) not in critical],
        new_marginal=[_display_essay(n) for n, st in ordered if st not in critical and n not in before],
        resolved_count=sum(1 for name in before if name not in now),
    )


def _ai_message(sample) -> AiMessage:
    text = localized_value(sample, "ai_recommendation", "")
    if text is None or (isinstance(text, float) and pd.isna(text)) or not isinstance(text, str) or text == "":
        return AiMessage(available=False)
    sections = _parse_oil_ai_sections(text)
    return AiMessage(
        diagnosis=sections["diagnostico"] or t("tab_alerts_detail.no_disponible"),
        actions=_split_actions(sections["accion"]),
        available=True,
    )


def _limit_label(kind: str, essay: str, value: float, chart_essays: List[str], decimals: Optional[int]) -> str:
    """Label of a limit line, printed in the chart's right margin and always for ONE test: "máx 9" / "mín 5"
    when the chart plots a single test, "Fe 119" / "PQ mín 15" when it plots several."""
    word = t("oil_report_pdf.limit_max") if kind == "upper" else t("oil_report_pdf.limit_min")
    number = format_number(value, decimals)
    if len(chart_essays) > 1:
        name = ESSAY_SYMBOLS.get(essay) or _display_essay(essay)
        return f"{name} {number}" if kind == "upper" else f"{name} {word} {number}"
    return f"{word} {number}"


def _charts(window: pd.DataFrame, comp_limits: dict, sample, flags: List[Flag], limits_for, units) -> Tuple[List[ChartSpec], List[ZeroStrip]]:
    """The dashboard's chart groups for the window. A group with no data is left out; one whose series are
    all zero in the whole range and within limits becomes a strip instead of a chart.

    The limit lines are the critical thresholds of `limits_for` (the table's own), one line per test, drawn
    for the tests that have a value in the examined sample, i.e. a table row: so every line's value is a
    value printed in the table."""
    if window.empty:
        return [], []
    by_name = {flag.name: flag for flag in flags}
    oil_hour_range = window.iloc[-1].get("oilHourRange", "UNKNOWN")
    charts: List[ChartSpec] = []
    strips: List[ZeroStrip] = []

    def current_of(essay):
        value = _number_or_none(sample.get(essay))
        flag = by_name.get(essay)
        return flag.value if value is None and flag is not None else value

    for config in TIME_SERIES_CHARTS:
        data = collect_chart_series(window, config["essays"], comp_limits, oil_hour_range)
        if not data["series"]:
            continue
        title = essay_label(vocab(config["title"]))
        chart_essays = [item["essay"] for item in data["series"]]
        drawn = [(essay, limits_for(essay)) for essay in chart_essays if current_of(essay) is not None]
        all_zero = all((item["values"] == 0).all() for item in data["series"])
        within = all((lim.upper_critical is None or lim.upper_critical >= 0) and (lim.lower_critical is None or lim.lower_critical <= 0)
                     for _essay, lim in drawn)
        if all_zero and within and not any(e in by_name for e in chart_essays):
            items = []
            for essay in chart_essays:
                lim, dec = limits_for(essay), _unit_decimals(units(essay))
                texts = []
                if current_of(essay) is not None:
                    if lim.upper_critical is not None:
                        texts.append(f"{t('oil_report_pdf.limit_max')} {format_number(lim.upper_critical, dec)}")
                    if lim.lower_critical is not None:
                        texts.append(f"{t('oil_report_pdf.limit_min')} {format_number(lim.lower_critical, dec)}")
                items.append((_display_essay(essay), " · ".join(texts) or None))
            strips.append(ZeroStrip(title=title, items=items))
            continue
        series = []
        for item in data["series"]:
            essay = item["essay"]
            flag = by_name.get(essay)
            series.append(ChartSeries(
                name=_display_essay(essay),
                points=[(pd.Timestamp(day).normalize(), float(value)) for day, value in zip(item["dates"], item["values"])],
                current=current_of(essay),
                state=flag.state if flag is not None else None,
                decimals=_unit_decimals(units(essay)),
            ))
        lines = []
        for essay, lim in drawn:
            dec = _unit_decimals(units(essay))
            if lim.upper_critical is not None:
                lines.append(ChartLimit(lim.upper_critical, "upper", _limit_label("upper", essay, lim.upper_critical, chart_essays, dec), essay))
            if lim.lower_critical is not None:
                lines.append(ChartLimit(lim.lower_critical, "lower", _limit_label("lower", essay, lim.lower_critical, chart_essays, dec), essay))
        charts.append(ChartSpec(title=title, series=series, limits=lines))
    return charts, strips


def _essays_mapping() -> pd.DataFrame:
    """The team's essay mapping (element symbol and group per test); empty when it cannot be read."""
    try:
        path = _data_path("oil", "essays_elements.xlsx")
        if path.exists():
            return load_essays_mapping(path)
    except Exception:
        logger.warning("Could not read the essays mapping for the PDF report", exc_info=True)
    return pd.DataFrame(columns=["Element", "ElementNameSpanish", "GroupElement"])


def _mapping_groups(mapping: pd.DataFrame) -> Dict[str, str]:
    named = mapping.dropna(subset=["ElementNameSpanish"]) if len(mapping) else mapping
    return {str(r["ElementNameSpanish"]): str(r.get("GroupElement", "")) for _, r in named.iterrows()}


def _group_definitions(mapping: pd.DataFrame, columns, flags: List[Flag]) -> List[Tuple[str, List[Tuple[str, Optional[str]]]]]:
    """(title key, [(test, symbol)]) per group: the fixed groups, the additives completed from the mapping,
    and "Otros ensayos" with every other test of the mapping the data has, plus any out-of-limit test the
    mapping does not know."""
    named = mapping.dropna(subset=["ElementNameSpanish"]) if len(mapping) else mapping
    symbols = {}
    groups_of = {}
    for _, row in named.iterrows():
        name = str(row["ElementNameSpanish"])
        groups_of[name] = str(row.get("GroupElement", ""))
        element = str(row.get("Element", "") or "")
        if groups_of[name] in ELEMENT_MAPPING_GROUPS and element.isalpha() and len(element) <= 2:
            symbols[name] = element
    definitions: List[Tuple[str, List[Tuple[str, Optional[str]]]]] = []
    placed = set()
    for key, members in ESSAY_GROUPS:
        members = list(members)
        if key == ADDITIVES_KEY:
            members += [(name, symbols.get(name)) for name, group in groups_of.items()
                        if group == "Aditivo" and name not in {m[0] for m in members}]
        placed.update(name for name, _s in members)
        definitions.append((key, members))
    others = [(name, symbols.get(name)) for name in groups_of if name not in placed and name in columns]
    known = {name for name, _s in others}
    others += [(flag.name, symbols.get(flag.name)) for flag in flags if flag.name not in placed and flag.name not in known]
    definitions.append((OTHERS_KEY, others))
    return definitions


def _table_group_rows(members, sample, previous, flags_by_name, limits_for, units) -> Tuple[List[TableRow], List[str], List[str]]:
    """(rows, no_limit entries, no_data names) of a group.

    A test with a value gets a row, except one that has no limit at all and is not out of limit: those
    collapse into one "Sin límite definido" entry carrying its value (and the previous one when it differs).
    A test without a value collapses into the no-data line. Its status is the stored one: out of limit as
    stored, otherwise Normal when it has limits and "—" when it has none."""
    rows: List[TableRow] = []
    no_limit: List[str] = []
    no_data: List[str] = []
    for name, symbol in members:
        flag = flags_by_name.get(name)
        value = _number_or_none(sample.get(name))
        if value is None and flag is not None:
            value = flag.value
        if value is None and flag is None:
            no_data.append(_essay_title(name, symbol))
            continue
        limits = limits_for(name)
        before = _number_or_none(previous.get(name)) if previous is not None else None
        unit = units(name)
        dec = _unit_decimals(unit)
        if flag is None and not limits.any():
            entry = f"{symbol or _display_essay(name)} {format_number(value, dec)}"
            if before is not None and format_number(before, dec) != format_number(value, dec):
                entry += f" ({t('oil_report_pdf.previous_short')} {format_number(before, dec)})"
            no_limit.append(entry)
            continue
        rows.append(TableRow(
            test=_essay_title(name, symbol),
            unit=_unit_text(unit),
            value=format_number(value, dec),
            lower_marginal=format_number(limits.lower_marginal, dec),
            lower=format_number(limits.lower_critical, dec),
            upper_marginal=format_number(limits.upper_marginal, dec),
            upper=format_number(limits.upper_critical, dec),
            state=flag.state if flag is not None else "normal",
            previous=format_number(before, dec),
            essay=name,
        ))
    return rows, no_limit, no_data


def _groups(sample, previous, flags: List[Flag], mapping, limits_for, units) -> List[TableGroup]:
    flags_by_name = {flag.name: flag for flag in flags}
    groups: List[TableGroup] = []
    for key, members in _group_definitions(mapping, set(sample.index), flags):
        rows, no_limit, no_data = _table_group_rows(members, sample, previous, flags_by_name, limits_for, units)
        if key == OTHERS_KEY and not rows and not no_limit:
            continue                                   # nothing outside the groups: no "Otros ensayos"
        groups.append(TableGroup(title=t(key), rows=rows, no_limit=no_limit, no_data=no_data))
    return groups


def select_history(history: pd.DataFrame, sample_day: pd.Timestamp) -> pd.DataFrame:
    """The samples the history shows, newest first: the examined one and the earlier ones of the same unit
    and component, as `min(last 6 samples, last 6 months)` - whichever of the two candidates is shorter.
    A is the examined sample plus up to 5 previous ones; B is every sample dated on or after (examined
    date - 6 calendar months), the boundary included."""
    days = pd.to_datetime(history["sampleDate"]).dt.normalize()
    upto = history[days <= sample_day].assign(_day=days).sort_values("_day", ascending=False)
    last_samples = upto.head(HISTORY_MAX_SAMPLES)
    last_months = upto[upto["_day"] >= sample_day - pd.DateOffset(months=HISTORY_MONTHS)]
    return last_samples if len(last_samples) <= len(last_months) else last_months


def _history(history: pd.DataFrame, sample_day: pd.Timestamp) -> List[HistoryRow]:
    out = []
    for _, row in select_history(history, sample_day).iterrows():
        comment = localized_value(row, "ai_recommendation")
        current = row["_day"] == sample_day
        text = _as_text(comment, "")
        sections = _parse_oil_ai_sections(text) if current and text else {"diagnostico": "", "accion": ""}
        out.append(HistoryRow(
            report_id=_as_text(row.get("sampleNumber"), "—"),
            date=row["_day"].strftime("%Y-%m-%d"),
            status=_as_text(row.get("report_status"), "—"),
            anomaly=_format_anomaly_type(row.get("anomalyType")),
            comment=text or "—",
            diagnosis=sections["diagnostico"],
            action=sections["accion"],
            is_current=bool(current),
        ))
    return out


def build_oil_report(df: pd.DataFrame, limits, client, familia, equipo, component, sample_date, *,
                     logo_path: Optional[Path] = None, today: Optional[str] = None) -> OilReportPdf:
    """The PDF model of one sample. `df` is the client's classified reports; `limits` the four-limit
    Stewart structure (None when the client has none). Raises `ReportNotFound` for an unknown sample."""
    sample = _find_sample(df, familia, equipo, component, sample_date)
    sample_day = pd.to_datetime(sample["sampleDate"]).normalize()
    if limits:
        # The limits are keyed by the client as the selector spells it ("CAPSTONE"); a different
        # casing would otherwise find none and print every limit as missing without a word.
        client = next((key for key in limits if str(key).casefold() == str(client).casefold()), client)

    history = unit_history(df, equipo, component)
    earlier = history[history["sampleDate"].dt.normalize() < sample_day]
    previous = earlier.iloc[-1] if not earlier.empty else None

    comp_limits = {}
    if limits:
        key = sample.get("componentNameNormalized") or component
        comp_limits = limits.get(client, {}).get(familia, {}).get(key, {})

    flags = report_flags(sample, limits, client, familia, component, comp_limits)
    previous_flags = report_flags(previous, limits, client, familia, component, comp_limits) if previous is not None else []
    flags_by_name = {flag.name: flag for flag in flags}
    mapping = _essays_mapping()
    mapping_groups = _mapping_groups(mapping)
    oil_hour_range = sample.get("oilHourRange", "UNKNOWN")
    limit_cache: Dict[str, Limits] = {}

    def limits_for(name: str) -> Limits:
        if name not in limit_cache:
            limit_cache[name] = resolve_limits(name, comp_limits, oil_hour_range, flags_by_name.get(name))
        return limit_cache[name]

    def units(name: str) -> Optional[str]:
        return _unit_key(name, mapping_groups)

    window_start, window_end = default_time_series_window(sample_day, history["sampleDate"])
    window = clip_history_to_window(history, window_start, window_end)
    charts, strips = _charts(window, comp_limits, sample, flags, limits_for, units)
    groups = _groups(sample, previous, flags, mapping, limits_for, units)
    ordered = _ordered_flags(groups)

    identity = Identity(
        equipo=str(sample.get("unitId", "N/A")).upper(),
        componente=_display_name(_as_text(sample.get("componentName"))),
        familia=_display_name(_as_text(sample.get("machineName"))),
        cliente=_as_text(sample.get("client")).upper(),
        fecha=sample_day.strftime("%Y-%m-%d"),
        report_id=_as_text(sample.get("sampleNumber")),
        componente_horas=_hours_text(sample.get("componentHours")),
        aceite_horas=_hours_text(sample.get("oilMeter")),
    )
    return OilReportPdf(
        identity=identity,
        classification=_classification(sample, ordered),
        comparison=_comparison(sample, previous, ordered, previous_flags),
        ai=_ai_message(sample),
        charts=charts,
        strips=strips,
        window_start=window_start,
        window_end=window_end,
        groups=groups,
        previous_date=previous["sampleDate"].strftime("%Y-%m-%d") if previous is not None else None,
        history=_history(history, sample_day),
        generated_on=today or _today_iso(),
        logo_path=logo_path if logo_path is not None else find_logo(),
    )


def generate_oil_report_pdf(client, familia, equipo, component, sample_date) -> Tuple[bytes, str]:
    """(PDF bytes, suggested file name) for the selected sample, read from the client's data."""
    settings = get_settings()
    limits_file = settings.get_stewart_limits_four_path(client)
    df = load_oil_classified(client)
    limits = load_stewart_limits_four(limits_file) if limits_file.exists() else None
    report = build_oil_report(df, limits, client, familia, equipo, component, sample_date)
    return render_oil_report_pdf(report), pdf_filename(equipo, component, pd.to_datetime(report.identity.fecha))


# ---------------------------------------------------------------------------
# Dash wiring
# ---------------------------------------------------------------------------


def register_oil_report_pdf_callbacks(app):
    @app.callback(
        Output("reports-pdf-button", "disabled"),
        [Input("reports-familia-selector", "value", allow_optional=True),
         Input("reports-equipo-selector", "value", allow_optional=True),
         Input("reports-component-selector", "value", allow_optional=True),
         Input("reports-date-selector", "value", allow_optional=True)],
        prevent_initial_call=True,
    )
    def toggle_pdf_button(familia, equipo, component, sample_date):
        """The download is available only while a report is loaded: all four filters chosen."""
        return not all([familia, equipo, component, sample_date])

    @app.callback(
        [Output("reports-pdf-download", "data"),
         Output("reports-pdf-feedback", "children")],
        Input("reports-pdf-button", "n_clicks"),
        [State("reports-familia-selector", "value", allow_optional=True),
         State("reports-equipo-selector", "value", allow_optional=True),
         State("reports-component-selector", "value", allow_optional=True),
         State("reports-date-selector", "value", allow_optional=True),
         State("client-selector", "value", allow_optional=True)],
        running=[
            (Output("reports-pdf-button", "disabled"), True, False),
            (Output("reports-pdf-loading", "style"), {"display": "inline-flex", "alignItems": "center"}, {"display": "none"}),
        ],
        prevent_initial_call=True,
    )
    def download_report_pdf(n_clicks, familia, equipo, component, sample_date, client):
        """Generate the selected report's PDF and hand it to the browser; on failure say so."""
        if not n_clicks:
            raise PreventUpdate
        if not all([familia, equipo, component, sample_date, client]):
            return None, _error(t("tab_reports.pdf_seleccione_reporte"))
        try:
            pdf, filename = generate_oil_report_pdf(client, familia, equipo, component, sample_date)
        except Exception:
            logger.exception("Could not generate the oil report PDF: client=%s familia=%s equipo=%s component=%s date=%s",
                             client, familia, equipo, component, sample_date)
            return None, _error(t("tab_reports.error_al_generar_el_pdf"))
        return dcc.send_bytes(pdf, filename, type="application/pdf"), None


def _error(message: str):
    # dbc.Alert renders role="alert" itself, so a screen reader announces the failure.
    return dbc.Alert(message, color="danger", className="py-2 mb-2 small")
