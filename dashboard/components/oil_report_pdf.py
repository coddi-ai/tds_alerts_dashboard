"""PDF of one oil report (Monitoreo > Aceite > Detalle de reporte), A4 portrait.

This module only draws. Everything it prints arrives already resolved in an `OilReportPdf`
(dashboard/callbacks/oil_report_pdf_callbacks.py builds it from the same data, limits, statuses and
AI text the tab shows), so the PDF never calculates anything of its own.

Page flow (the number of pages is not fixed): header -> classification -> AI message -> values table ->
a two-column section (history on the left, about a third; trend charts on the right, two thirds) ->
footer. The table flows across pages between groups, never inside a row; the two-column section is
packed by `TwoColumn`, which splits between its blocks (a history entry, a row of chart cards, a strip)
and never inside one.

Rules the drawing follows:
  * Status is never carried by color alone: every status is its word plus a shape (circle = Normal,
    triangle = Alerta, diamond = Anormal for a report; ● Normal, △ Marginal, ▲ Crítico for a test), and the
    page stays legible in grayscale.
  * The two series of a chart differ by marker shape (circle / square), not only by color.
  * Pages after the first repeat a compact identification header; every page carries the footer
    "ID de reporte · Equipo · Muestra", the generation date and "Página X de Y".

Fonts are the PDF standard Helvetica family (nothing to embed or ship). It only reaches the Western
European character set, so `safe_text` maps the few typographic symbols an AI comment may carry and
anything else outside it becomes "?".
"""

from __future__ import annotations

import io
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence, Tuple
from xml.sax.saxutils import escape

import pandas as pd
from reportlab.graphics.shapes import Circle, Drawing, Line, Polygon, PolyLine, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import (
    BaseDocTemplate,
    CondPageBreak,
    Flowable,
    Frame,
    Image,
    NextPageTemplate,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from shared.severity import STATUS_TIERS, STATUS_TIER_BY_ESTADO
from src.i18n import current_language, t

# ---------------------------------------------------------------------------
# Page geometry and palette
# ---------------------------------------------------------------------------

PAGE_W, PAGE_H = A4
MARGIN_X = 14 * mm
MARGIN_BOTTOM = 16 * mm
MARGIN_TOP_FIRST = 13 * mm
MARGIN_TOP_LATER = 20 * mm
CONTENT_W = PAGE_W - 2 * MARGIN_X
FRAME_H = PAGE_H - MARGIN_TOP_LATER - MARGIN_BOTTOM          # the usable height of a page after the first

# Top-right logo slot of page 1 (maximum box; the image keeps its proportions).
LOGO_MAX_W = 35 * mm
LOGO_MAX_H = 12 * mm

INK = colors.HexColor("#111827")
MUTED = colors.HexColor("#5b6472")
RULE = colors.HexColor("#cfd6e0")
GRID = colors.HexColor("#e6e9ef")
HEAD_FILL = colors.HexColor("#f3f5f9")
GROUP_FILL = colors.HexColor("#e9edf4")
BOX_FILL = colors.HexColor("#f6f8fc")
BOX_BORDER = colors.HexColor("#d6dce8")
CARD_FILL = colors.HexColor("#fbfcfe")

# Report statuses -> the dashboard's own tiers (shared/severity.py), so a PDF badge cannot drift
# from the banner on screen. Alerta is the orange tier, Anormal the deep red one.
STATUS_SHAPES = {"Normal": "circle", "Alerta": "triangle", "Anormal": "diamond"}
# Surface of the classification box, tint of a status cell, and the status' own ink.
STATUS_STYLE = {
    "Normal": dict(box="#f0fdf4", border="#15803d", cell="#e3f4e8", text="#15803d"),
    "Alerta": dict(box="#fffbeb", border="#c2410c", cell="#fdeccd", text="#92400e"),
    "Anormal": dict(box="#fef2f2", border="#b91c1c", cell="#fde4e1", text="#b91c1c"),
}
NEUTRAL_STYLE = dict(box="#f6f8fc", border="#cfd6e0", cell="#eef0f4", text="#5b6472")

CRITICAL_TEXT = colors.HexColor("#b91c1c")
MARGINAL_TEXT = colors.HexColor("#92400e")
NORMAL_DOT = colors.HexColor("#15803d")
CRITICAL_FILL = colors.HexColor("#f9cfc9")          # a critical row is tinted more strongly ...
MARGINAL_FILL = colors.HexColor("#fdf3d6")          # ... than a marginal one

SERIES_COLORS = [colors.HexColor("#1d4ed8"), colors.HexColor("#b45309")]
SERIES_MARKERS = ["circle", "square"]
LIMIT_RED = colors.HexColor("#c0392b")

FONT = "Helvetica"
FONT_BOLD = "Helvetica-Bold"

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class Identity:
    equipo: str
    componente: str
    familia: str
    cliente: str
    fecha: str
    report_id: str
    componente_horas: str = "N/A"
    aceite_horas: str = "N/A"


@dataclass
class Classification:
    """The report status and, for a report that is not Normal, what is out of limit."""
    status: str                                  # raw: Normal / Alerta / Anormal
    anomaly: str = "—"
    out_of_limit: int = 0
    # every out-of-limit test as (name, state), critical (▲) first and then marginal (△), each in the table's
    # order: the same tests, in the same count, as the highlighted rows of the values table
    flagged: List[Tuple[str, str]] = field(default_factory=list)
    detailed: bool = False                       # False: the status alone (a Normal report)


@dataclass
class Comparison:
    """Examined report against the one before it ("Análisis de Cambios Respecto al Reporte Anterior")."""
    previous_date: str
    previous_status: str
    days: Optional[int]
    new_critical: List[str] = field(default_factory=list)      # ▲ now and not ▲ before
    resolved_count: int = 0
    new_marginal: List[str] = field(default_factory=list)      # △ now and not out of limit before


@dataclass
class AiMessage:
    diagnosis: str = ""
    actions: List[str] = field(default_factory=list)
    available: bool = True


@dataclass
class ChartSeries:
    name: str
    points: List[Tuple[pd.Timestamp, float]]     # (sample day, value), ascending
    current: Optional[float] = None              # its value in the examined sample (the legend shows it)
    state: Optional[str] = None                  # that value's state when out of limit: high | low | marginal_*
    decimals: Optional[int] = None               # fixed decimals of its unit (None: up to two, trimmed)


@dataclass
class ChartLimit:
    value: float
    kind: str                                    # 'upper' | 'lower'
    label: str                                   # short, already translated ("máx 9", "PQ 131")
    essay: str = ""                              # the test it belongs to (its table row carries the same value)


@dataclass
class ChartSpec:
    title: str
    series: List[ChartSeries]
    limits: List[ChartLimit] = field(default_factory=list)


@dataclass
class ZeroStrip:
    """A chart group that is zero in the whole range and within limits: one strip instead of a chart."""
    title: str
    items: List[Tuple[str, Optional[str]]]       # (test, its limit text such as "máx 0.3")


@dataclass
class TableRow:
    test: str
    unit: str = "—"
    value: str = "—"
    lower: str = "—"                             # critical lower limit
    upper: str = "—"                             # critical upper limit
    state: Optional[str] = None                  # normal | high | low | marginal_high | marginal_low | None
    previous: str = "—"
    lower_marginal: str = "—"
    upper_marginal: str = "—"
    essay: str = ""                              # the data name of the test


@dataclass
class TableGroup:
    title: str
    rows: List[TableRow] = field(default_factory=list)    # the tests with a value and a limit (or a flag)
    no_limit: List[str] = field(default_factory=list)     # "Cr 0", "Ba 0 (ant. 1)": valued, no limit, not out of limit
    no_data: List[str] = field(default_factory=list)      # the ones without a value, collapsed into one line


@dataclass
class HistoryRow:
    report_id: str
    date: str
    status: str
    anomaly: str
    comment: str                                 # the report's whole comment as stored
    diagnosis: str = ""                          # the examined sample's comment, split as in
    action: str = ""                             # "Historial de Comentarios"
    is_current: bool = False


@dataclass
class OilReportPdf:
    identity: Identity
    classification: Classification
    comparison: Optional[Comparison]
    ai: AiMessage
    charts: List[ChartSpec]
    window_start: pd.Timestamp
    window_end: pd.Timestamp
    groups: List[TableGroup]
    previous_date: Optional[str]                 # header of the "Anterior" column
    history: List[HistoryRow]                    # newest first, the examined report included
    generated_on: str
    strips: List[ZeroStrip] = field(default_factory=list)
    logo_path: Optional[Path] = None


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

_SYMBOL_FALLBACKS = {
    "≥": ">=", "≤": "<=", "→": "->", "←": "<-", "↑": "^", "↓": "v", "−": "-", "∼": "~", "≈": "~",
    "✓": "", "✔": "", " ": " ", " ": " ", "​": "", "‐": "-", "‑": "-", "′": "'",
    "″": '"', "Δ": "Delta ",
}


def safe_text(value) -> str:
    """Text the standard PDF fonts can draw: a few symbols mapped, anything beyond Latin-1/cp1252 -> '?'."""
    text = "" if value is None else str(value)
    out = []
    for char in text:
        char = _SYMBOL_FALLBACKS.get(char, char)
        for piece in char:
            try:
                piece.encode("cp1252")
                out.append(piece)
            except UnicodeEncodeError:
                out.append("?")
    return "".join(out)


def _markup(value) -> str:
    """Text for a Paragraph: escaped (it parses mini-HTML) with line breaks kept."""
    return escape(safe_text(value)).replace("\r\n", "\n").replace("\n", "<br/>")


def _one_line(value) -> str:
    return re.sub(r"\s+", " ", safe_text(value)).strip()


_DANGLING = re.compile(r"^(?:[\d.,]+|[A-Za-zÁÉÍÓÚáéíóúñÑ]{1,2}|\(.*)$")


def _ellipsize(text: str, width: float, font: str, size: float) -> str:
    """`text` cut at a word boundary (never inside a word or a number) so that it plus an ellipsis fits
    `width`. Trailing words that would dangle (a number, a one or two letter word such as "Al", "y", "de",
    an opening bracket) go too: "…(Al 2" is not a place to stop."""
    tokens = text.split(" ")
    while tokens:
        candidate = " ".join(tokens).rstrip(",;:.-–—") + "…"
        if stringWidth(candidate, font, size) <= width and not _DANGLING.match(tokens[-1]):
            return candidate
        tokens.pop()
    return "…"


def fit_one_line(text: str, width: float, font: str = FONT, size: float = 7.5) -> str:
    """`text` cut with an ellipsis so that it fits `width` points on one line."""
    text = _one_line(text)
    return text if stringWidth(text, font, size) <= width else _ellipsize(text, width, font, size)


def wrap_lines(text: str, width: float, font: str, size: float, max_lines: int) -> List[str]:
    """`text` word-wrapped to `width` and cut to `max_lines` lines. When there is more, the last line ends in
    an ellipsis placed at a word boundary."""
    words = _one_line(text).split(" ")
    lines: List[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if stringWidth(candidate, font, size) <= width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    if len(lines) > max_lines:
        kept = lines[:max_lines]
        kept[-1] = _ellipsize(kept[-1], width, font, size)
        if kept[-1] == "…" and len(kept) > 1:           # nothing worth keeping on the last line: end the one before
            kept.pop()
            kept[-1] = _ellipsize(kept[-1], width, font, size)
        return kept
    return [fit_one_line(line, width, font, size) for line in lines]


# Decimals of a unit, the same wherever a value in that unit is printed (table, legends, limits, and the
# numbers in the AI text): ppm 1, % 2, cSt 2, Abs/cm 1, the PQ index and hours 0. A unit not listed keeps
# up to two decimals.
UNIT_DECIMALS = {"ppm": 1, "%": 2, "cSt": 2, "Abs/cm": 1, "hrs": 0, "índice": 0, "index": 0}


def _to_locale(text: str) -> str:
    """`text`, written with "," for thousands and "." for decimals, in the language of the document:
    Spanish "1.234,5", English "1,234.5"."""
    if current_language() == "en":
        return text
    return text.replace(",", "\0").replace(".", ",").replace("\0", ".")


def format_number(value, decimals: Optional[int] = None) -> str:
    """A number as the whole PDF prints it: thousands separators and the decimal mark of the document's
    language, `decimals` fixed decimals (None: up to two, trailing zeros dropped); '—' when missing."""
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if math.isnan(number) or math.isinf(number):
        return "—"
    if decimals is None:
        text = f"{number:,.2f}"
        text = text.rstrip("0").rstrip(".") if "." in text else text
    else:
        text = f"{number:,.{decimals}f}"
    if text.startswith("-") and float(text.replace(",", "")) == 0:
        text = text[1:]
    return _to_locale(text)


_TEXT_NUMBER = re.compile(
    r"(?<![\w.,/-])(\d{1,3}(?:[.,]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)(\s*)(ppm|hrs?|horas|cSt|Abs/cm|%)?(?![\w-])")
_UNIT_KEY = {"ppm": "ppm", "hr": "hrs", "hrs": "hrs", "horas": "hrs", "cSt": "cSt", "Abs/cm": "Abs/cm", "%": "%"}


def _parse_text_number(token: str):
    """(value, decimals as written) of a number inside prose, in either convention ("3641,0", "1.234,5",
    "96.0", "3,641"); None when it is a plain integer (a year, a count) there is nothing to rewrite in."""
    thousands = "." if current_language() != "en" else ","
    if "," in token and "." in token:
        decimal = "," if token.rfind(",") > token.rfind(".") else "."
        integer, _, fraction = token.rpartition(decimal)
    else:
        separator = "," if "," in token else ("." if "." in token else None)
        if separator is None:
            return None
        integer, _, fraction = token.rpartition(separator)
        many = token.count(separator) > 1
        grouped = len(fraction) == 3 and 1 <= len(integer) <= 3 and not integer.startswith("0") and separator == thousands
        if many or grouped:
            integer, fraction = token.replace(separator, ""), ""
    digits = re.sub(r"[.,]", "", integer)
    return float(f"{digits}.{fraction}" if fraction else digits), len(fraction)


def localize_text_numbers(text) -> str:
    """Prose (the AI's diagnosis and actions, a history comment) with its numbers written by the one rule
    of the PDF: the document's separators and, for a number followed by a unit, that unit's decimals
    ("3641,0 ppm" -> "3.641,0 ppm"). Dates, report IDs and plain integers are left alone."""
    if text is None:
        return ""

    def replace(match):
        token, space, unit = match.group(1), match.group(2), match.group(3)
        key = _UNIT_KEY.get(unit) if unit else None
        parsed = _parse_text_number(token)
        if parsed is None and key is None:
            return match.group(0)
        value, written = parsed if parsed is not None else (float(token), 0)
        decimals = UNIT_DECIMALS.get(key, written) if key else written
        return format_number(value, decimals) + (space + unit if unit else "")

    return _TEXT_NUMBER.sub(replace, str(text))


def _canonical_status(status) -> Optional[str]:
    name = str(status or "").strip().casefold()
    for known in STATUS_TIER_BY_ESTADO:
        if known.casefold() == name:
            return known
    return None


def status_text(status) -> str:
    """The status word as the dashboard shows it (translated): Normal / Alerta / Anormal."""
    canonical = _canonical_status(status)
    if canonical is None:
        return safe_text(status) if status else "—"
    return t({"Normal": "status.normal", "Alerta": "status.alert", "Anormal": "status.abnormal"}[canonical])


def status_style(status) -> dict:
    return STATUS_STYLE.get(_canonical_status(status), NEUTRAL_STYLE)


# ---------------------------------------------------------------------------
# Shapes (drawn, not typed: the fonts have none of these glyphs)
# ---------------------------------------------------------------------------


def _shape_points(shape: str, cx: float, cy: float, r: float):
    if shape == "triangle":
        return [cx, cy + r * 1.15, cx - r * 1.1, cy - r * 0.8, cx + r * 1.1, cy - r * 0.8]
    if shape == "triangle_down":
        return [cx, cy - r * 1.15, cx - r * 1.1, cy + r * 0.8, cx + r * 1.1, cy + r * 0.8]
    if shape == "diamond":
        return [cx, cy + r * 1.25, cx + r * 1.25, cy, cx, cy - r * 1.25, cx - r * 1.25, cy]
    return None


def canvas_shape(canv, shape: str, cx: float, cy: float, r: float, *, fill=None, stroke=None, width: float = 0.8):
    """Draw a marker on a canvas: circle, square, diamond, triangle or triangle_down."""
    canv.saveState()
    canv.setLineWidth(width)
    if fill is not None:
        canv.setFillColor(fill)
    if stroke is not None:
        canv.setStrokeColor(stroke)
    flags = dict(stroke=1 if stroke is not None else 0, fill=1 if fill is not None else 0)
    if shape == "square":
        canv.rect(cx - r, cy - r, 2 * r, 2 * r, **flags)
    elif shape == "circle":
        canv.circle(cx, cy, r, **flags)
    else:
        points = _shape_points(shape, cx, cy, r)
        path = canv.beginPath()
        path.moveTo(points[0], points[1])
        for index in range(2, len(points), 2):
            path.lineTo(points[index], points[index + 1])
        path.close()
        canv.drawPath(path, **flags)
    canv.restoreState()


def drawing_marker(shape: str, cx: float, cy: float, r: float, *, fill=None, stroke=None, width: float = 0.7):
    """The same markers as a graphics shape (for the charts and the timeline)."""
    kwargs = dict(
        fillColor=fill, strokeColor=stroke if stroke is not None else None,
        strokeWidth=width if stroke is not None else 0,
    )
    if shape == "circle":
        return Circle(cx, cy, r, **kwargs)
    if shape == "square":
        return Rect(cx - r, cy - r, 2 * r, 2 * r, **kwargs)
    return Polygon(_shape_points(shape, cx, cy, r), **kwargs)


def status_colors(status):
    """(background, text, border) of a report status pill, from the dashboard's own tiers."""
    canonical = _canonical_status(status)
    if canonical is None:
        return HEAD_FILL, MUTED, RULE
    tier = STATUS_TIERS[STATUS_TIER_BY_ESTADO[canonical]]
    if canonical == "Normal":
        return colors.HexColor(tier["badge_bg"]), colors.HexColor(tier["badge_text"]), colors.HexColor(tier["badge_text"])
    return colors.HexColor(tier["bg"]), colors.white, colors.HexColor(tier["border"])


def status_pill_width(label: str, size: float) -> float:
    return stringWidth(safe_text(label), FONT_BOLD, size) + size * 2.7


def draw_status_pill(canv, x: float, y: float, status, label: str, size: float):
    """The status pill: a small-radius chip with its shape and word. (x, y) is its bottom-left corner."""
    background, text_color, border = status_colors(status)
    height = size * 1.75
    width = status_pill_width(label, size)
    canv.saveState()
    canv.setFillColor(background)
    canv.setStrokeColor(border)
    canv.setLineWidth(0.9)
    canv.roundRect(x, y, width, height, min(height * 0.2, 3.2), stroke=1, fill=1)
    shape = STATUS_SHAPES.get(_canonical_status(status), "circle")
    canvas_shape(canv, shape, x + size * 1.1, y + height / 2, size * 0.34, fill=text_color, stroke=None)
    canv.setFillColor(text_color)
    canv.setFont(FONT_BOLD, size)
    canv.drawString(x + size * 1.85, y + height / 2 - size * 0.34, safe_text(label))
    canv.restoreState()
    return width, height


class StatusPill(Flowable):
    """A status pill as a flowable (the headline of the classification box)."""

    def __init__(self, status, size: float = 8, label: Optional[str] = None):
        super().__init__()
        self.status = status
        self.size = size
        self.label = label if label is not None else status_text(status).upper()
        self.hAlign = "LEFT"

    def wrap(self, availWidth, availHeight):
        self.width = status_pill_width(self.label, self.size)
        self.height = self.size * 1.75
        return self.width, self.height

    def draw(self):
        draw_status_pill(self.canv, 0, 0, self.status, self.label, self.size)


# A test's own state in the values table (the report-level shapes above are for the whole report):
# ● Normal, △ Marginal (hollow), ▲ Crítico (filled); the arrow points the way it is out of limit.
TEST_STATES = {
    "normal": ("oil_report_pdf.state_normal", "circle", NORMAL_DOT),
    "high": ("oil_report_pdf.state_critical_high", "triangle", CRITICAL_TEXT),
    "low": ("oil_report_pdf.state_critical_low", "triangle_down", CRITICAL_TEXT),
    "marginal_high": ("oil_report_pdf.state_marginal_high", "triangle_open", MARGINAL_TEXT),
    "marginal_low": ("oil_report_pdf.state_marginal_low", "triangle_down_open", MARGINAL_TEXT),
}


def test_state_label(state: Optional[str]) -> str:
    return t(TEST_STATES[state][0]) if state in TEST_STATES else "—"


class TestStateMark(Flowable):
    """The Estado of one test: shape + word (never color alone). Critical states are bold + filled
    triangles, marginal ones outlined, normal a dot."""

    __test__ = False  # not a pytest class

    def __init__(self, state: Optional[str], size: float = 7.8):
        super().__init__()
        self.state = state
        self.size = size
        self.hAlign = "LEFT"
        self.label = test_state_label(state)

    def wrap(self, availWidth, availHeight):
        self.width = (stringWidth(self.label, FONT_BOLD, self.size) + self.size * 1.7) if self.state in TEST_STATES \
            else stringWidth(self.label, FONT, self.size)
        self.height = self.size * 1.3
        return self.width, self.height

    def draw(self):
        if self.state not in TEST_STATES:
            self.canv.setFillColor(MUTED)
            self.canv.setFont(FONT, self.size)
            self.canv.drawString(0, self.size * 0.2, self.label)
            return
        _key, shape, color = TEST_STATES[self.state]
        r = self.size * 0.36
        cy = self.size * 0.5
        if shape.endswith("_open"):
            canvas_shape(self.canv, shape[:-5], r * 1.1, cy, r, fill=colors.white, stroke=color, width=1.1)
        else:
            canvas_shape(self.canv, shape, r * 1.1, cy, r, fill=color, stroke=color)
        flagged = self.state != "normal"
        self.canv.setFillColor(color if flagged else INK)
        self.canv.setFont(FONT_BOLD if flagged else FONT, self.size)
        self.canv.drawString(self.size * 1.7, self.size * 0.2, self.label)


class Checkbox(Flowable):
    """The empty box in front of an action: something to tick on paper."""

    def __init__(self, side: float = 3.3 * mm):
        super().__init__()
        self.side = side

    def wrap(self, availWidth, availHeight):
        self.width, self.height = self.side, self.side
        return self.width, self.height

    def draw(self):
        self.canv.setStrokeColor(INK)
        self.canv.setLineWidth(0.8)
        self.canv.roundRect(0, 0, self.side, self.side, 0.6 * mm, stroke=1, fill=0)


# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------


def _style(name: str, **kwargs) -> ParagraphStyle:
    base = dict(fontName=FONT, fontSize=9, leading=12.2, textColor=INK, alignment=TA_LEFT)
    base.update(kwargs)
    return ParagraphStyle(name, **base)


STYLES = {
    "body": _style("body"),
    "small": _style("small", fontSize=8.4, leading=11.2),
    "muted": _style("muted", fontSize=8, leading=10.5, textColor=MUTED),
    "label": _style("label", fontSize=7.8, leading=9.6, textColor=MUTED),
    "value": _style("value", fontSize=10.8, leading=13, fontName=FONT_BOLD),
    "value_big": _style("value_big", fontSize=11.6, leading=14, fontName=FONT_BOLD),
    "eyebrow": _style("eyebrow", fontSize=8, leading=10, textColor=MUTED, fontName=FONT_BOLD),
    "title": _style("title", fontSize=29, leading=32, fontName=FONT_BOLD),
    "subtitle": _style("subtitle", fontSize=13.5, leading=16, textColor=colors.HexColor("#374151")),
    "section": _style("section", fontSize=13.5, leading=16, fontName=FONT_BOLD),
    "box_title": _style("box_title", fontSize=7.8, leading=10, fontName=FONT_BOLD, textColor=MUTED),
    "big_number": _style("big_number", fontSize=24, leading=26, fontName=FONT_BOLD),
    "cell": _style("cell", fontSize=8, leading=10),
    "cell_bold": _style("cell_bold", fontSize=8, leading=10, fontName=FONT_BOLD),
    "cell_muted": _style("cell_muted", fontSize=7.8, leading=10, textColor=MUTED),
    "cell_right": _style("cell_right", fontSize=8, leading=10, alignment=TA_RIGHT),
    "cell_right_bold": _style("cell_right_bold", fontSize=8, leading=10, alignment=TA_RIGHT, fontName=FONT_BOLD),
    "head": _style("head", fontSize=7.6, leading=9.2, fontName=FONT_BOLD, textColor=colors.HexColor("#374151")),
    "head_center": _style("head_center", fontSize=7.6, leading=9.2, fontName=FONT_BOLD, textColor=colors.HexColor("#374151"),
                          alignment=TA_CENTER),
    "head_right": _style("head_right", fontSize=7.6, leading=9.2, fontName=FONT_BOLD, textColor=colors.HexColor("#374151"),
                         alignment=TA_RIGHT),
    "group": _style("group", fontSize=7.8, leading=9.6, fontName=FONT_BOLD, textColor=colors.HexColor("#374151")),
    "entry": _style("entry", fontSize=7.6, leading=9.4, splitLongWords=0),
    "entry_muted": _style("entry_muted", fontSize=7.2, leading=9, textColor=MUTED, splitLongWords=0),
}


def _p(text, style="body") -> Paragraph:
    return Paragraph(_markup(text), STYLES[style])


def _section_heading(title: str, note: Optional[str] = None) -> list:
    """Section title with its muted note under it (no rule: the mockup has none)."""
    blocks = [_p(title, "section")]
    if note:
        blocks += [Spacer(1, 0.8 * mm), _p(note, "muted")]
    return blocks


# ---------------------------------------------------------------------------
# Header, classification, AI message
# ---------------------------------------------------------------------------


def _logo(path: Optional[Path]):
    """The logo scaled into its slot, or None when there is no (readable) asset: the slot is then omitted."""
    if not path or not Path(path).is_file():
        return None
    try:
        width, height = ImageReader(str(path)).getSize()
    except Exception:
        return None
    if not width or not height:
        return None
    scale = min(LOGO_MAX_W / width, LOGO_MAX_H / height)
    image = Image(str(path), width=width * scale, height=height * scale)
    image.hAlign = "RIGHT"
    return image


def _identity_block(report: OilReportPdf) -> list:
    ident = report.identity
    title_block = [
        _p(t("oil_report_pdf.eyebrow").upper(), "eyebrow"),
        Spacer(1, 1 * mm),
        _p(ident.equipo, "title"),
        Spacer(1, 1.2 * mm),
        _p(f"{ident.familia} · {ident.componente}", "subtitle"),
    ]
    logo = _logo(report.logo_path)
    if logo is None:
        head = Table([[title_block]], colWidths=[CONTENT_W])
    else:
        head = Table([[title_block, logo]], colWidths=[CONTENT_W - LOGO_MAX_W - 4 * mm, LOGO_MAX_W + 4 * mm])
    head.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))

    def field_cell(label, value):
        return [_p(label, "label"), Spacer(1, 0.6 * mm), _p(value, "value_big")]

    fields = [
        [field_cell(t("oil_report_pdf.cliente"), ident.cliente),
         field_cell(t("oil_report_pdf.fecha_muestra"), ident.fecha),
         field_cell(t("oil_report_pdf.id_reporte"), ident.report_id)],
        [field_cell(t("oil_report_pdf.familia"), ident.familia),
         field_cell(t("oil_report_pdf.horometro_componente"), ident.componente_horas),
         field_cell(t("oil_report_pdf.horometro_aceite"), ident.aceite_horas)],
    ]
    grid = Table(fields, colWidths=[CONTENT_W / 3] * 3)
    grid.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEABOVE", (0, 0), (-1, 0), 0.6, RULE),
        ("LINEBELOW", (0, -1), (-1, -1), 0.6, RULE),
    ]))
    return [head, Spacer(1, 3.5 * mm), grid]


def _comparison_line(comp: Comparison) -> Paragraph:
    """One sentence: previous sample (date, status, days elapsed), the tests that are new critical (▲, the only
    ones called "críticos"), the new marginal ones (△) when there are any, and the resolved tests."""
    days = ""
    if comp.days is not None:
        days = t("oil_report_pdf.cmp_days_one") if comp.days == 1 else t("oil_report_pdf.cmp_days_many", days=comp.days)
    context = f"({comp.previous_date} · {status_text(comp.previous_status)}{days})"
    count = len(comp.new_critical)
    new = t("oil_report_pdf.cmp_new_one" if count == 1 else "oil_report_pdf.cmp_new_many", count=count)
    if comp.new_critical:
        new += " — " + ", ".join(comp.new_critical)
    parts = [new]
    if comp.new_marginal:
        marginal = len(comp.new_marginal)
        parts.append(t("oil_report_pdf.cmp_marginal_one" if marginal == 1 else "oil_report_pdf.cmp_marginal_many", count=marginal)
                     + " — " + ", ".join(comp.new_marginal))
    parts.append(t("oil_report_pdf.cmp_resolved_one" if comp.resolved_count == 1 else "oil_report_pdf.cmp_resolved_many",
                   count=comp.resolved_count))
    return Paragraph(f"<b>{_markup(t('oil_report_pdf.cmp_lead'))}</b> {_markup(context)}: {_markup(' · '.join(parts))}.",
                     STYLES["small"])


class SymbolList(Flowable):
    """Out-of-limit tests as a flowing list, each with its table symbol (▲ critical, △ marginal), so the
    reader sees the severity without opening the table."""

    def __init__(self, entries: Sequence[Tuple[str, str]], width: float, size: float = 9.6):
        super().__init__()
        self.entries, self.width, self.size = list(entries), width, size
        self.hAlign = "LEFT"

    def _layout(self):
        placed, x, row = [], 0.0, 0
        gap = 3.6 * mm
        for name, state in self.entries:
            w = 3.6 * mm + stringWidth(safe_text(name), FONT_BOLD, self.size)
            if x + w > self.width and x > 0:
                x, row = 0.0, row + 1
            placed.append((name, state, x, row))
            x += w + gap
        return placed, row + 1

    def wrap(self, availWidth, availHeight):
        _placed, rows = self._layout()
        self.height = rows * self.size * 1.5
        return self.width, self.height

    def draw(self):
        placed, _rows = self._layout()
        line = self.size * 1.5
        for name, state, x, row in placed:
            y = self.height - (row + 1) * line + self.size * 0.35
            _key, shape, color = TEST_STATES.get(state, TEST_STATES["high"])
            r = self.size * 0.34
            if shape.endswith("_open"):
                canvas_shape(self.canv, shape[:-5], x + r * 1.1, y + self.size * 0.3, r, fill=colors.white, stroke=color, width=1.1)
            else:
                canvas_shape(self.canv, shape, x + r * 1.1, y + self.size * 0.3, r, fill=color, stroke=color)
            self.canv.setFillColor(INK)
            self.canv.setFont(FONT_BOLD, self.size)
            self.canv.drawString(x + 3.6 * mm, y, safe_text(name))


def _classification_block(report: OilReportPdf) -> list:
    cls = report.classification
    style = status_style(cls.status)
    pad = 9
    inner_w = CONTENT_W - 2 * pad
    status_w = 56 * mm
    headline = [_p(t("oil_report_pdf.estado_reporte"), "label"), Spacer(1, 1.6 * mm), StatusPill(cls.status, size=15)]
    inner_style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]
    if cls.detailed:
        anomaly_w = 38 * mm
        out_w = inner_w - status_w - anomaly_w - 9 - 6          # the cell's own paddings
        count_w = 12 * mm
        listing = (SymbolList(cls.flagged, out_w - count_w - 4) if cls.flagged else _p(t("oil_report_pdf.none"), "value"))
        number_and_list = Table([[_p(str(cls.out_of_limit), "big_number"), listing]], colWidths=[count_w, out_w - count_w])
        number_and_list.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        top = Table([[
            headline,
            [_p(t("oil_report_pdf.anomalia_detectada"), "label"), Spacer(1, 0.8 * mm), _p(cls.anomaly, "value")],
            # the count and the list are one block: "Ensayos fuera de límite", N, then each test with its symbol
            [_p(t("oil_report_pdf.ensayos_fuera_de_limite"), "label"), Spacer(1, 0.8 * mm), number_and_list],
        ]], colWidths=[status_w, anomaly_w, inner_w - status_w - anomaly_w])
        top.setStyle(TableStyle(inner_style + [
            ("LINEAFTER", (0, 0), (0, 0), 0.7, RULE),
            ("LEFTPADDING", (1, 0), (-1, -1), 9),
        ]))
    else:
        top = Table([[headline]], colWidths=[inner_w])
        top.setStyle(TableStyle(inner_style))

    rows = [[top]]
    styles = [
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(style["box"])),
        ("BOX", (0, 0), (-1, -1), 1.1, colors.HexColor(style["border"])),
        ("ROUNDEDCORNERS", [4, 4, 4, 4]),
        ("LEFTPADDING", (0, 0), (-1, -1), pad), ("RIGHTPADDING", (0, 0), (-1, -1), pad),
        ("TOPPADDING", (0, 0), (0, 0), 9), ("BOTTOMPADDING", (0, 0), (0, 0), 9),
    ]
    if report.comparison is not None:
        rows.append([_comparison_line(report.comparison)])
        styles += [
            ("LINEABOVE", (0, 1), (-1, 1), 0.6, RULE),
            ("TOPPADDING", (0, 1), (-1, 1), 6), ("BOTTOMPADDING", (0, 1), (-1, 1), 7),
        ]
    box = Table(rows, colWidths=[CONTENT_W])
    box.setStyle(TableStyle(styles))
    return [box]


def _ai_block(report: OilReportPdf) -> list:
    ai = report.ai
    blocks = _section_heading(t("oil_report_pdf.section_ai")) + [Spacer(1, 2.2 * mm)]
    if not ai.available:
        blocks.append(_p(t("reports_callbacks.no_hay_recomendacion_de_ia_disponible"), "muted"))
        return blocks

    half = CONTENT_W / 2
    box_w = half - 1.5 * mm
    diagnosis = [_p(t("reports_callbacks.diagnostico").upper(), "box_title"), Spacer(1, 1.6 * mm),
                 _p(localize_text_numbers(ai.diagnosis), "body")]
    if ai.actions:
        action_rows = [[Checkbox(), _p(localize_text_numbers(item), "body")] for item in ai.actions]
        actions_table = Table(action_rows, colWidths=[5.2 * mm, box_w - 2 * 9 - 5.2 * mm])
        actions_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 1.4), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.4),
        ]))
        actions = [_p(t("reports_callbacks.acciones").upper(), "box_title"), Spacer(1, 1.2 * mm), actions_table]
    else:
        actions = [_p(t("reports_callbacks.acciones").upper(), "box_title"), Spacer(1, 1.6 * mm),
                   _p(t("reports_callbacks.acciones_no_disponibles"), "muted")]

    # Two boxes with a gutter column between them. A row may split across pages, so a very long
    # diagnosis or action list flows on instead of failing to fit.
    boxes = Table([[diagnosis, "", actions]], colWidths=[box_w, 3 * mm, box_w], splitInRow=1)
    boxes.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (0, 0), BOX_FILL), ("BACKGROUND", (2, 0), (2, 0), BOX_FILL),
        ("BOX", (0, 0), (0, 0), 0.8, BOX_BORDER), ("BOX", (2, 0), (2, 0), 0.8, BOX_BORDER),
        ("LEFTPADDING", (0, 0), (0, 0), 9), ("RIGHTPADDING", (0, 0), (0, 0), 9),
        ("LEFTPADDING", (2, 0), (2, 0), 9), ("RIGHTPADDING", (2, 0), (2, 0), 9),
        ("LEFTPADDING", (1, 0), (1, 0), 0), ("RIGHTPADDING", (1, 0), (1, 0), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    blocks.append(boxes)
    return blocks


# ---------------------------------------------------------------------------
# Values and limits table
# ---------------------------------------------------------------------------

#            Grupo   Ensayo  Unidad  Valor   inf.m   inf.c   sup.m   sup.c   Estado  Anterior
TABLE_COLS = [24 * mm, 28 * mm, 13 * mm, 15 * mm, 13 * mm, 13 * mm, 13 * mm, 13 * mm, 30 * mm, 20 * mm]


class SymbolLegend(Flowable):
    """The key to the Estado symbols, printed above the table: ● Normal, △ Marginal, ▲ Crítico, — sin límite o sin valor."""

    def __init__(self, width: float, size: float = 7.4):
        super().__init__()
        self.width, self.size = width, size

    def _items(self):
        return [("normal", t("oil_report_pdf.legend_normal")), ("marginal_high", t("oil_report_pdf.legend_marginal")),
                ("high", t("oil_report_pdf.legend_critical")), (None, t("oil_report_pdf.legend_none"))]

    def _layout(self):
        placed, x, row = [], 0.0, 0
        for state, text in self._items():
            w = 3.8 * mm + stringWidth(safe_text(text), FONT, self.size)
            if x + w > self.width and x > 0:
                x, row = 0.0, row + 1
            placed.append((state, text, x, row))
            x += w + 5 * mm
        return placed, row + 1

    def wrap(self, availWidth, availHeight):
        self.height = self._layout()[1] * self.size * 1.6
        return self.width, self.height

    def draw(self):
        c = self.canv
        for state, text, x, row in self._layout()[0]:
            y = self.height - (row + 1) * self.size * 1.6 + self.size * 0.45
            if state is None:
                c.setFillColor(MUTED)
                c.setFont(FONT, self.size)
                c.drawString(x, y, safe_text(text))
                continue
            _key, shape, color = TEST_STATES[state]
            r = self.size * 0.36
            if shape.endswith("_open"):
                canvas_shape(c, shape[:-5], x + r * 1.1, y + self.size * 0.32, r, fill=colors.white, stroke=color, width=1.1)
            else:
                canvas_shape(c, shape, x + r * 1.1, y + self.size * 0.32, r, fill=color, stroke=color)
            c.setFillColor(INK)
            c.setFont(FONT, self.size)
            c.drawString(x + 3.8 * mm, y, safe_text(text))


def _values_block(report: OilReportPdf) -> list:
    flagged_rows = sum(1 for g in report.groups for r in g.rows if r.state not in (None, "normal"))
    previous_header = _markup(t("oil_report_pdf.col_previous"))
    if report.previous_date:
        previous_header += f"<br/>{escape(report.previous_date)}"
    head = lambda key, style="head": Paragraph(_markup(t(key)), STYLES[style])
    header = [
        [head("oil_report_pdf.col_group"), head("oil_report_pdf.col_test"), head("oil_report_pdf.col_unit"),
         head("oil_report_pdf.col_value", "head_right"), head("oil_report_pdf.col_lower_limit", "head_center"), "",
         head("oil_report_pdf.col_upper_limit", "head_center"), "", head("oil_report_pdf.col_state"),
         Paragraph(previous_header, STYLES["head_right"])],
        ["", "", "", "", head("oil_report_pdf.col_marginal", "head_right"), head("oil_report_pdf.col_critical", "head_right"),
         head("oil_report_pdf.col_marginal", "head_right"), head("oil_report_pdf.col_critical", "head_right"), "", ""],
    ]
    rows = list(header)
    style = [
        ("BACKGROUND", (0, 0), (-1, 1), HEAD_FILL),
        ("LINEABOVE", (0, 0), (-1, 0), 0.8, MUTED),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2.6), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.6),
        ("LINEBELOW", (0, 1), (-1, -1), 0.3, RULE),
        ("LINEBELOW", (4, 0), (7, 0), 0.3, RULE),
        # the header: every column but the limits spans its two header rows; the limits read "inferior /
        # superior" over "marginal / crítico"
        *[("SPAN", (col, 0), (col, 1)) for col in (0, 1, 2, 3, 8, 9)],
        ("SPAN", (4, 0), (5, 0)), ("SPAN", (6, 0), (7, 0)),
        ("TOPPADDING", (0, 1), (-1, 1), 0.5),
        # the Estado column follows right-aligned numbers: keep its mark off the previous column
        ("LEFTPADDING", (8, 0), (8, -1), 10),
    ]
    for group in report.groups:
        first = len(rows)
        for row in group.rows:
            flagged = row.state not in (None, "normal")
            body = "cell_bold" if flagged else "cell"
            numeric = "cell_right_bold" if flagged else "cell_right"
            rows.append([
                "",
                Paragraph(_markup(row.test), STYLES[body]),
                Paragraph(_markup(row.unit), STYLES["cell"]),
                Paragraph(_markup(row.value), STYLES[numeric]),
                Paragraph(_markup(row.lower_marginal), STYLES["cell_right"]),
                Paragraph(_markup(row.lower), STYLES["cell_right"]),
                Paragraph(_markup(row.upper_marginal), STYLES["cell_right"]),
                Paragraph(_markup(row.upper), STYLES["cell_right"]),
                TestStateMark(row.state),
                Paragraph(_markup(row.previous), STYLES["cell_right"]),
            ])
            if flagged:
                fill = CRITICAL_FILL if row.state in ("high", "low") else MARGINAL_FILL
                style.append(("BACKGROUND", (1, len(rows) - 1), (-1, len(rows) - 1), fill))
        for text in ([t("oil_report_pdf.no_limit_line", items=" · ".join(group.no_limit))] if group.no_limit else []) \
                + ([t("oil_report_pdf.no_data_line", names=" · ".join(group.no_data))] if group.no_data else []):
            # one line each for the valued tests that have no limit, and for the ones without a value
            rows.append(["", Paragraph(_markup(text), STYLES["cell_muted"])] + [""] * 8)
            style.append(("SPAN", (1, len(rows) - 1), (-1, len(rows) - 1)))
        last = len(rows) - 1
        rows[first][0] = Paragraph(_markup(group.title), STYLES["group"])
        if last > first:
            style.append(("SPAN", (0, first), (0, last)))
        # the group name sits in the left column over all of its rows; a group never splits across pages
        style += [
            ("BACKGROUND", (0, first), (0, last), GROUP_FILL),
            ("VALIGN", (0, first), (0, last), "TOP"),
            ("LINEABOVE", (0, first), (-1, first), 0.8, MUTED),
            ("NOSPLIT", (0, first), (-1, last)),
        ]
    table = Table(rows, colWidths=TABLE_COLS, repeatRows=2)
    table.setStyle(TableStyle(style))
    return _section_heading(t("oil_report_pdf.section_values"), t("oil_report_pdf.values_note", count=flagged_rows)) \
        + [Spacer(1, 1.6 * mm), SymbolLegend(CONTENT_W), Spacer(1, 1.6 * mm), table]


# ---------------------------------------------------------------------------
# The two-column section: history (left) and trend charts (right)
# ---------------------------------------------------------------------------

COL_GAP = 6 * mm
LEFT_W = (CONTENT_W - COL_GAP) / 3                  # about a third for the history ...
RIGHT_W = CONTENT_W - LEFT_W - COL_GAP              # ... and two thirds for the charts
CARD_GAP = 3.5 * mm
CARD_W = (RIGHT_W - CARD_GAP) / 2
BLOCK_GAP = 3 * mm
PLOT_H = 21 * mm


class Stack(Flowable):
    """Flowables one under the other, as a single block (heading + first block stay together)."""

    def __init__(self, items: Sequence[Flowable], width: float):
        super().__init__()
        self.items = list(items)
        self.width = width

    def wrap(self, availWidth, availHeight):
        self.height = sum(item.wrap(self.width, 1e6)[1] for item in self.items)
        return self.width, self.height

    def draw(self):
        y = self.height
        for item in self.items:
            _w, h = item.wrap(self.width, 1e6)
            item.drawOn(self.canv, 0, y - h)
            y -= h


class TwoColumn(Flowable):
    """Two columns of blocks side by side that flow across pages together.

    Each column is a list of (block, space_after). A block is never split: when the page is full the
    blocks that fit stay and the rest continue on the next page, in the same two columns. So a history
    entry, a row of chart cards or a strip is always whole on one page."""

    def __init__(self, left, left_w, right, right_w, gap):
        super().__init__()
        self.left, self.right = list(left), list(right)
        self.left_w, self.right_w, self.gap = left_w, right_w, gap

    @staticmethod
    def _height(blocks, width) -> float:
        total = 0.0
        for index, (block, after) in enumerate(blocks):
            total += block.wrap(width, 1e6)[1] + (after if index < len(blocks) - 1 else 0)
        return total

    def wrap(self, availWidth, availHeight):
        self.width = self.left_w + self.gap + self.right_w
        self.height = max(self._height(self.left, self.left_w), self._height(self.right, self.right_w))
        return self.width, self.height

    @staticmethod
    def _fit(blocks, width, avail) -> int:
        used, taken = 0.0, 0
        for block, after in blocks:
            h = block.wrap(width, 1e6)[1]
            if used + h > avail:
                break
            used += h + after
            taken += 1
        return taken

    def split(self, availWidth, availHeight):
        left_n = self._fit(self.left, self.left_w, availHeight)
        right_n = self._fit(self.right, self.right_w, availHeight)
        if left_n == 0 and right_n == 0:
            if availHeight < FRAME_H * 0.95:
                return []                        # not even one block fits here: start on the next page
            left_n, right_n = min(1, len(self.left)), min(1, len(self.right))     # a fresh page: never loop
        head = TwoColumn(self.left[:left_n], self.left_w, self.right[:right_n], self.right_w, self.gap)
        rest_left, rest_right = self.left[left_n:], self.right[right_n:]
        if not rest_left and not rest_right:
            return [head]
        return [head, TwoColumn(rest_left, self.left_w, rest_right, self.right_w, self.gap)]

    def draw(self):
        for blocks, x, width in ((self.left, 0, self.left_w), (self.right, self.left_w + self.gap, self.right_w)):
            y = self.height
            for block, after in blocks:
                _w, h = block.wrap(width, 1e6)
                block.drawOn(self.canv, x, y - h)
                y -= h + after


# --- history ---------------------------------------------------------------

MAX_COMMENT_CHARS = 1800          # a comment longer than this is cut: an entry never spans a page
HISTORY_COMMENT_LINES = 3         # the other entries show their comment cut at a word boundary after 3 lines


class HistoryEntry(Flowable):
    """One sample of the vertical timeline: the status marker on the line, the date, the status word
    (and "actual" for the examined sample), the report ID (a word: it is never broken across lines), the
    anomaly when abnormal and the comment: the examined sample's in full (Diagnóstico / Acción), the
    others cut to two lines."""

    def __init__(self, row: HistoryRow, width: float, first: bool, last: bool):
        super().__init__()
        self.row, self.width, self.first, self.last = row, width, first, last
        self.text_x = 6.5 * mm
        self._parts: List[Paragraph] = []

    def _build(self):
        row = self.row
        ink = status_style(row.status)["text"]
        text_w = self.width - self.text_x
        head = f"<b>{escape(row.date)}</b>  <font color='{ink}'><b>{_markup(status_text(row.status))}"
        if row.is_current:
            head += f" · {_markup(t('oil_report_pdf.current'))}"
        head += "</b></font>"
        parts = [Paragraph(head, STYLES["entry"]),
                 Paragraph(f"{_markup(t('oil_report_pdf.id_short'))} <b>{escape(safe_text(row.report_id))}</b>", STYLES["entry"])]
        if _canonical_status(row.status) != "Normal" and row.anomaly not in ("—", "", None):
            parts.append(Paragraph(_markup(row.anomaly), STYLES["entry"]))
        if row.is_current:
            diagnosis, action = row.diagnosis, row.action
            if not diagnosis and not action:
                diagnosis = row.comment if row.comment != "—" else ""
            diagnosis, action = localize_text_numbers(diagnosis), localize_text_numbers(action)
            if len(diagnosis) + len(action) > MAX_COMMENT_CHARS:
                diagnosis = _one_line(diagnosis)[:MAX_COMMENT_CHARS * 2 // 3]
                action = _one_line(action)[:MAX_COMMENT_CHARS // 3]
            lines = []
            if diagnosis:
                lines.append(f"<b>{_markup(t('reports_callbacks.diagnostico'))}</b> {_markup(diagnosis)}")
            if action:
                lines.append(f"<b>{_markup(t('oil_report_pdf.action_singular'))}</b> {_markup(action)}")
            if lines:
                parts.append(Paragraph("<br/>".join(lines), STYLES["entry"]))
        elif row.comment and row.comment != "—":
            cut = wrap_lines(localize_text_numbers(row.comment), text_w, FONT, 7.2, HISTORY_COMMENT_LINES)
            parts.append(Paragraph("<br/>".join(escape(line) for line in cut), STYLES["entry_muted"]))
        self._parts = parts
        self._text_w = text_w

    def wrap(self, availWidth, availHeight):
        self._build()
        self._heights = [p.wrap(self._text_w, 1e6)[1] for p in self._parts]
        self.height = sum(self._heights) + 0.6 * mm * (len(self._parts) - 1) + 3.2 * mm
        return self.width, self.height

    def draw(self):
        canv = self.canv
        marker_x = 2.4 * mm
        dot_y = self.height - 2.5 * mm
        canv.saveState()
        canv.setStrokeColor(RULE)
        canv.setLineWidth(1.4)
        top = dot_y if self.first else self.height
        bottom = dot_y if self.last else 0
        if top > bottom:
            canv.line(marker_x, top, marker_x, bottom)
        canv.restoreState()
        ink = colors.HexColor(status_style(self.row.status)["text"])
        shape = STATUS_SHAPES.get(_canonical_status(self.row.status), "circle")
        if self.row.is_current:
            canv.saveState()
            canv.setStrokeColor(ink)
            canv.setLineWidth(0.8)
            canv.circle(marker_x, dot_y, 3.3 * mm * 0.75, stroke=1, fill=0)
            canv.restoreState()
        canvas_shape(canv, shape, marker_x, dot_y, (1.9 if self.row.is_current else 1.4) * mm, fill=ink, stroke=ink, width=0.6)
        y = self.height - 0.4 * mm
        for part, h in zip(self._parts, self._heights):
            part.drawOn(canv, self.text_x, y - h)
            y -= h + 0.6 * mm


class StatusKey(Flowable):
    """The report statuses and their symbols, as the dashboard draws them: ● Normal (green circle),
    ▲ Alerta (orange triangle), ◆ Anormal (red diamond). Word + shape + color, so it reads in grayscale."""

    def __init__(self, width: float, size: float = 7.2):
        super().__init__()
        self.width, self.size = width, size

    def wrap(self, availWidth, availHeight):
        self.height = self.size * 1.6
        return self.width, self.height

    def draw(self):
        x = 0.0
        for status in ("Normal", "Alerta", "Anormal"):
            ink = colors.HexColor(status_style(status)["text"])
            canvas_shape(self.canv, STATUS_SHAPES[status], x + 1.3 * mm, self.size * 0.55, 1.15 * mm, fill=ink, stroke=ink, width=0.5)
            word = safe_text(status_text(status))
            self.canv.setFillColor(ink)
            self.canv.setFont(FONT_BOLD, self.size)
            self.canv.drawString(x + 3.4 * mm, self.size * 0.2, word)
            x += 3.4 * mm + stringWidth(word, FONT_BOLD, self.size) + 3.5 * mm


def _history_blocks(report: OilReportPdf):
    heading = _section_heading(t("oil_report_pdf.section_history"), t("oil_report_pdf.history_note")) \
        + [Spacer(1, 1.2 * mm), StatusKey(LEFT_W)]
    head = Stack(heading, LEFT_W)
    entries = [HistoryEntry(row, LEFT_W, first=i == 0, last=i == len(report.history) - 1)
               for i, row in enumerate(report.history)]
    if not entries:
        return [(Stack(heading + [_p(t("reports_callbacks.sin_comentarios_disponibles"), "muted")], LEFT_W), 0)]
    blocks = [(Stack([head] + [Spacer(1, 2 * mm), entries[0]], LEFT_W), 0)]
    blocks += [(entry, 0) for entry in entries[1:]]
    return blocks


# --- charts ----------------------------------------------------------------


def _axis3(lo: float, hi: float):
    """(ymin, ymax, step) of an axis with exactly two intervals (three gridlines) that covers [lo, hi]."""
    if hi - lo < 1e-9:
        if lo >= 0:
            # a constant, non-negative series (all zeros is common): the axis starts at zero
            lo, hi = 0.0, (hi * 1.5 if hi > 0 else 1.0)
        else:
            pad = abs(hi) * 0.1 or 1.0
            lo, hi = lo - pad, hi + pad
    raw = (hi - lo) / 2
    magnitude = 10 ** math.floor(math.log10(raw))
    for factor in (1, 2, 2.5, 5, 10, 20, 25, 50, 100):
        step = factor * magnitude
        ymin = math.floor(lo / step + 1e-9) * step
        if ymin + 2 * step >= hi - 1e-9:
            return ymin, ymin + 2 * step, step
    return lo, hi, (hi - lo) / 2


def _tick_label(value: float, step: float) -> str:
    decimals = 0 if step >= 1 else min(3, int(math.ceil(-math.log10(step))))
    return format_number(value, decimals)


def _month_names() -> List[str]:
    names = t("oil_report_pdf.months_short").split(",")
    return names if len(names) == 12 else [str(i) for i in range(1, 13)]


def month_ticks(start: pd.Timestamp, end: pd.Timestamp, max_labels: int = 5) -> List[Tuple[pd.Timestamp, str]]:
    """(day, label) of the month ticks of a range: the first day of each month inside it (every 2nd, 3rd...
    when there are more than `max_labels`), labelled with the month's short name, plus the year when the
    range is longer than a year."""
    first = pd.Timestamp(start.year, start.month, 1)
    if first < start:
        first += pd.DateOffset(months=1)
    firsts = []
    while first <= end:
        firsts.append(first)
        first += pd.DateOffset(months=1)
    if not firsts:
        firsts = [start]
    stride = max(1, math.ceil(len(firsts) / max_labels))
    with_year = (end - start).days > 366
    names = _month_names()
    return [(day, names[day.month - 1] + (f" {day.year % 100:02d}" if with_year else "")) for day in firsts[::stride]]


def _legend_rows(spec: ChartSpec, avail: float):
    """The legend entries (marker, name, value) of a card, in as many rows as they need."""
    entries = []
    for index, series in enumerate(spec.series):
        value = format_number(series.current, series.decimals) if series.current is not None else "—"
        flagged = series.state in TEST_STATES and series.state != "normal"
        width = 3.4 * mm + stringWidth(safe_text(series.name), FONT, 6.6) + 1.6 * mm + stringWidth(value, FONT_BOLD, 6.6) \
            + (3.2 * mm if flagged else 0)
        entries.append((index, series, value, flagged, width))
    total = sum(e[4] for e in entries) + 3 * mm * (len(entries) - 1)
    return [entries] if total <= avail else [[e] for e in entries]


def chart_card(spec: ChartSpec, start: pd.Timestamp, end: pd.Timestamp, width: float = CARD_W) -> Drawing:
    """One chart card: the title, a legend with each series' value in the examined sample (▲ / △ and red
    when it is out of limit), and a plot with three light gridlines, month ticks, the series as thin
    lines with small dots (the examined sample a larger dot with a halo) and each critical limit as a thin
    dashed red line whose value is printed in the right margin. The Y axis always includes the limits."""
    pad = 2 * mm
    left, right = 7.3 * mm, 11.5 * mm
    legend = _legend_rows(spec, width - 2 * pad)
    height = pad + 3.8 * mm + 3.4 * mm * len(legend) + 2.2 * mm + PLOT_H + 5.2 * mm + 1.2 * mm
    drawing = Drawing(width, height)
    drawing.add(Rect(0, 0, width, height, rx=1.6 * mm, ry=1.6 * mm, fillColor=CARD_FILL, strokeColor=RULE, strokeWidth=0.6))

    y1 = height - pad - 3.8 * mm - 3.4 * mm * len(legend) - 2.2 * mm       # plot top
    y0 = y1 - PLOT_H
    x0, x1 = left, width - right
    span_days = max((end - start).days, 1)
    xa, xb = x0 + 1.6 * mm, x1 - 1.8 * mm

    def x_of(day: pd.Timestamp) -> float:
        return xa + ((day - start).days / span_days) * (xb - xa)

    # the axis covers the data and every critical limit
    values = [v for s in spec.series for _d, v in s.points] + [limit.value for limit in spec.limits]
    ymin, ymax, step = _axis3(min(values), max(values))

    def y_of(value: float) -> float:
        return y0 + ((value - ymin) / (ymax - ymin)) * (y1 - y0)

    # title and legend
    drawing.add(String(pad + 0.5 * mm, height - pad - 2.7 * mm, safe_text(spec.title), fontName=FONT_BOLD, fontSize=8.2, fillColor=INK))
    row_y = height - pad - 3.8 * mm - 2.4 * mm
    for row in legend:
        x = pad + 0.5 * mm
        for index, series, value, flagged, _w in row:
            color = SERIES_COLORS[index % len(SERIES_COLORS)]
            shape = SERIES_MARKERS[index % len(SERIES_MARKERS)]
            drawing.add(drawing_marker(shape, x + 1.2 * mm, row_y + 0.8 * mm, 0.95 * mm, fill=color, stroke=color))
            drawing.add(String(x + 3.4 * mm, row_y, safe_text(series.name), fontName=FONT, fontSize=6.6, fillColor=INK))
            x += 3.4 * mm + stringWidth(safe_text(series.name), FONT, 6.6) + 1.6 * mm
            if flagged:
                critical = series.state in ("high", "low")
                shape_name = "triangle" if series.state.endswith("high") else "triangle_down"
                drawing.add(drawing_marker(shape_name, x + 1.0 * mm, row_y + 0.9 * mm, 0.75 * mm,
                                           fill=CRITICAL_TEXT if critical else colors.white, stroke=CRITICAL_TEXT, width=0.8))
                x += 2.6 * mm
            drawing.add(String(x, row_y, value, fontName=FONT_BOLD, fontSize=6.6, fillColor=CRITICAL_TEXT if flagged else INK))
            x += stringWidth(value, FONT_BOLD, 6.6) + 3 * mm
        row_y -= 3.4 * mm

    # three light gridlines with their values at the left
    for position in range(3):
        value = ymin + position * step
        y = y_of(value)
        drawing.add(Line(x0, y, x1, y, strokeColor=GRID, strokeWidth=0.5))
        drawing.add(String(x0 - 1.1 * mm, y - 1.9, _tick_label(value, step), fontName=FONT, fontSize=5.6, fillColor=MUTED, textAnchor="end"))

    # month ticks
    for day, label in month_ticks(start, end):
        x = x_of(day)
        drawing.add(Line(x, y0, x, y0 - 1 * mm, strokeColor=MUTED, strokeWidth=0.5))
        drawing.add(String(x, y0 - 3.5 * mm, safe_text(label), fontName=FONT, fontSize=5.6, fillColor=MUTED, textAnchor="middle"))

    # critical limits: thin dashed red lines, the value printed in the right margin (labels pushed apart)
    labels = []
    for limit in spec.limits:
        y = y_of(limit.value)
        drawing.add(Line(x0, y, x1, y, strokeColor=LIMIT_RED, strokeWidth=0.7, strokeDashArray=[2.6, 1.8]))
        labels.append([y - 1.7, limit.label])
    labels.sort(key=lambda item: -item[0])
    gap = 6.6
    for previous, item in zip(labels, labels[1:]):
        item[0] = min(item[0], previous[0] - gap)
    for y, label in labels:
        drawing.add(String(x1 + 1.1 * mm, y, safe_text(label), fontName=FONT_BOLD, fontSize=5.6, fillColor=LIMIT_RED))

    # series: ~1.75 px lines with small dots; the examined sample a larger dot with a halo
    for index, series in enumerate(spec.series):
        color = SERIES_COLORS[index % len(SERIES_COLORS)]
        shape = SERIES_MARKERS[index % len(SERIES_MARKERS)]
        coords = [(x_of(day), y_of(value)) for day, value in series.points]
        if len(coords) > 1:
            drawing.add(PolyLine([c for pair in coords for c in pair], strokeColor=color, strokeWidth=1.3))
        for (day, _value), (cx, cy) in zip(series.points, coords):
            if day == end:
                drawing.add(Circle(cx, cy, 2.5 * mm, fillColor=color, fillOpacity=0.22, strokeColor=None, strokeWidth=0))
                drawing.add(drawing_marker(shape, cx, cy, 1.25 * mm, fill=color, stroke=colors.white, width=0.7))
            else:
                drawing.add(drawing_marker(shape, cx, cy, 0.6 * mm, fill=color, stroke=color, width=0.3))
    return drawing


class ZeroStripBlock(Flowable):
    """"Sin detección en el período": a chart group that is zero throughout and within limits, as one
    strip listing its tests (with their limits) as chips."""

    CHIP_H = 4.3 * mm

    def __init__(self, strip: ZeroStrip, width: float):
        super().__init__()
        self.strip, self.width = strip, width

    def _layout(self):
        pad = 2.6 * mm
        chips, row, x = [], 0, pad
        for name, limit in self.strip.items:
            text = f"{name} · {limit}" if limit else name
            w = stringWidth(safe_text(text), FONT, 6.8) + 3.6 * mm
            if x + w > self.width - pad and x > pad:
                row, x = row + 1, pad
            chips.append((text, x, row, w))
            x += w + 1.6 * mm
        return chips, row + 1

    def wrap(self, availWidth, availHeight):
        _chips, rows = self._layout()
        self.height = 2.6 * mm + 4.2 * mm + rows * (self.CHIP_H + 1.4 * mm) + 1.2 * mm
        return self.width, self.height

    def draw(self):
        c = self.canv
        chips, rows = self._layout()
        c.saveState()
        c.setFillColor(BOX_FILL)
        c.setStrokeColor(RULE)
        c.setDash(2, 2)
        c.setLineWidth(0.7)
        c.roundRect(0, 0, self.width, self.height, 1.6 * mm, stroke=1, fill=1)
        c.setDash()
        title_y = self.height - 2.6 * mm - 2.6 * mm
        c.setFillColor(INK)
        c.setFont(FONT_BOLD, 7.6)
        title = safe_text(self.strip.title)
        c.drawString(2.6 * mm, title_y, title)
        c.setFillColor(MUTED)
        c.setFont(FONT, 7.2)
        c.drawString(2.6 * mm + stringWidth(title, FONT_BOLD, 7.6) + 2.5 * mm, title_y, safe_text(t("oil_report_pdf.zero_strip")))
        top = self.height - 2.6 * mm - 4.2 * mm
        for text, x, row, w in chips:
            y = top - (row + 1) * (self.CHIP_H + 1.4 * mm) + 1.4 * mm
            c.setFillColor(colors.white)
            c.setStrokeColor(RULE)
            c.setLineWidth(0.6)
            c.roundRect(x, y, w, self.CHIP_H, self.CHIP_H / 2, stroke=1, fill=1)
            c.setFillColor(INK)
            c.setFont(FONT, 6.8)
            c.drawString(x + 1.8 * mm, y + 1.35 * mm, safe_text(text))
        c.restoreState()


def _chart_blocks(report: OilReportPdf):
    start, end = report.window_start.strftime("%Y-%m-%d"), report.window_end.strftime("%Y-%m-%d")
    heading = _section_heading(t("oil_report_pdf.section_series"),
                               t("oil_report_pdf.series_note", date=end, start=start, end=end))
    cards = [chart_card(spec, report.window_start, report.window_end) for spec in report.charts]
    rows = []
    for i in range(0, len(cards), 2):
        pair = cards[i:i + 2]
        cells = [pair[0], "", pair[1] if len(pair) > 1 else ""]
        row = Table([cells], colWidths=[CARD_W, CARD_GAP, CARD_W])
        row.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        rows.append(row)
    blocks = rows + [ZeroStripBlock(strip, RIGHT_W) for strip in report.strips]
    if not blocks:
        blocks = [_p(t("oil_charts.sin_datos_de_ensayos_disponibles"), "muted")]
    out = [(Stack(heading + [Spacer(1, 2 * mm), blocks[0]], RIGHT_W), BLOCK_GAP)]
    out += [(block, BLOCK_GAP) for block in blocks[1:]]
    return out


# ---------------------------------------------------------------------------
# Page furniture (compact header from page 2, footer on every page) and the document
# ---------------------------------------------------------------------------


class _ReportCanvas(pdfcanvas.Canvas):
    """Canvas that draws each page's furniture once the page count is known ("Página X de Y")."""

    report: Optional[OilReportPdf] = None

    def __init__(self, *args, report=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.report = report
        self._saved_pages = []

    def showPage(self):
        self._saved_pages.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved_pages)
        for state in self._saved_pages:
            self.__dict__.update(state)
            self._draw_furniture(self._pageNumber, total)
            super().showPage()
        super().save()

    def _draw_furniture(self, page: int, total: int):
        report = self.report
        if report is None:
            return
        ident = report.identity
        if page > 1:
            self._draw_compact_header(report)
        # footer: identification, generation date, page count
        y = 9.5 * mm
        self.saveState()
        self.setStrokeColor(RULE)
        self.setLineWidth(0.6)
        self.line(MARGIN_X, y + 4 * mm, PAGE_W - MARGIN_X, y + 4 * mm)
        self.setFillColor(MUTED)
        self.setFont(FONT, 7.4)
        self.drawString(MARGIN_X, y, safe_text(t("oil_report_pdf.footer_ident", id=ident.report_id, equipo=ident.equipo, date=ident.fecha)))
        self.drawCentredString(PAGE_W / 2 + 28 * mm, y, safe_text(t("oil_report_pdf.generated", date=report.generated_on)))
        self.drawRightString(PAGE_W - MARGIN_X, y, safe_text(t("oil_report_pdf.page", page=page, total=total)))
        self.restoreState()

    def _draw_compact_header(self, report: OilReportPdf):
        """One line: unit, then component / family / client; sample date and report ID and the
        status badge at the right."""
        ident = report.identity
        base = PAGE_H - 13.5 * mm
        label = status_text(report.classification.status).upper()
        pill_size = 8.4
        pill_w = status_pill_width(label, pill_size)
        self.saveState()
        self.setFillColor(INK)
        self.setFont(FONT_BOLD, 17)
        equipo = safe_text(ident.equipo)
        self.drawString(MARGIN_X, base, equipo)
        left_end = MARGIN_X + stringWidth(equipo, FONT_BOLD, 17) + 3.5 * mm

        right_edge = PAGE_W - MARGIN_X
        draw_status_pill(self, right_edge - pill_w, base - 1.8, report.classification.status, label, pill_size)
        sample = safe_text(t("oil_report_pdf.header_sample", date=ident.fecha, id=ident.report_id))
        self.setFillColor(MUTED)
        self.setFont(FONT, 8.6)
        sample_right = right_edge - pill_w - 4 * mm
        self.drawRightString(sample_right, base, sample)
        sample_left = sample_right - stringWidth(sample, FONT, 8.6)

        detail = f"{ident.componente} · {ident.familia} · {ident.cliente}"
        detail = fit_one_line(detail, max(sample_left - 4 * mm - left_end, 20 * mm), FONT, 8.6)
        self.drawString(left_end, base, detail)
        self.setStrokeColor(RULE)
        self.setLineWidth(0.8)
        self.line(MARGIN_X, base - 4.6 * mm, right_edge, base - 4.6 * mm)
        self.restoreState()


def _story(report: OilReportPdf) -> list:
    story: list = [NextPageTemplate("later")]
    story += _identity_block(report)
    story += [Spacer(1, 5 * mm)] + _classification_block(report)
    story += [Spacer(1, 6 * mm)] + _ai_block(report)
    # The values table follows the AI message; it flows onto the next page between groups (never inside
    # a row), and the break is only taken when too little of the page is left for the heading, the
    # header row and a first group.
    story += [Spacer(1, 6 * mm), CondPageBreak(60 * mm)]
    story += _values_block(report)
    # Then the two-column section: history (a third) and trend charts (two thirds).
    story += [Spacer(1, 7 * mm)]
    story += [TwoColumn(_history_blocks(report), LEFT_W, _chart_blocks(report), RIGHT_W, COL_GAP)]
    return story


def render_oil_report_pdf(report: OilReportPdf, *, compress: bool = True) -> bytes:
    """The report as PDF bytes. `compress=False` leaves the page streams readable (tests)."""
    buffer = io.BytesIO()
    ident = report.identity
    doc = BaseDocTemplate(
        buffer, pagesize=A4, leftMargin=MARGIN_X, rightMargin=MARGIN_X,
        topMargin=MARGIN_TOP_FIRST, bottomMargin=MARGIN_BOTTOM,
        title=safe_text(f"{t('oil_report_pdf.eyebrow')} {ident.equipo} {ident.componente} {ident.fecha}"),
        author="", pageCompression=1 if compress else 0,
    )
    first = Frame(MARGIN_X, MARGIN_BOTTOM, CONTENT_W, PAGE_H - MARGIN_TOP_FIRST - MARGIN_BOTTOM,
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0, id="first")
    later = Frame(MARGIN_X, MARGIN_BOTTOM, CONTENT_W, FRAME_H,
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0, id="later")
    doc.addPageTemplates([PageTemplate(id="first", frames=[first]), PageTemplate(id="later", frames=[later])])

    def make_canvas(*args, **kwargs):
        return _ReportCanvas(*args, report=report, **kwargs)

    doc.build(_story(report), canvasmaker=make_canvas)
    return buffer.getvalue()
