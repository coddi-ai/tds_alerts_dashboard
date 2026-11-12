"""
Alert summary report builder (02_alert_summary_email_template.md).

`build_alert_summary(request)` turns a client's alerts inside a period into the email
subject + HTML. The alerts are loaded and prepared with the very same functions the Alertas
page uses (`load_alerts_data`, `prepare_alert_rows`, `filter_prepared_rows`), so counts match
the page for the same client and range. The email is always in Spanish, whatever language the
requesting admin's browser uses, so the preview equals the scheduled send.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import List, Optional

import jinja2
import pandas as pd

from src.i18n import forced_language
from src.utils.logger import get_logger

from . import alert_stats as stats
from . import config, periods
from .errors import MailingError
from .report import ALERT_SUMMARY, ReportContent, ReportRequest, register_report_builder

logger = get_logger(__name__)

TEMPLATE_DIR = Path(__file__).parent / "templates"

SOURCE_CHIPS = {  # label -> (background, text)
    "Telemetría": ("#dbeafe", "#1e40af"),
    "Tribología": ("#fef3c7", "#92400e"),
    "Multitécnica": ("#ede9fe", "#5b21b6"),
}
DEFAULT_CHIP = ("#f1f5f9", "#334155")

_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=jinja2.select_autoescape(["html"]),  # every alert text is escaped
    undefined=jinja2.StrictUndefined,
)


# --------------------------------------------------------------------------- data


def system_colors(names: List[str]) -> dict:
    """Bar color per system label, exactly as the Alertas page assigns them: known systems keep
    the shared `SISTEMA_COLORS`; any other (e.g. Emin's own names) cycles the dashboard's
    qualitative palette in sorted-label order."""
    from dashboard.components.alerts_charts import _treemap_root_colors

    return _treemap_root_colors(names)


def load_period_records(client: str, start: date, end: date) -> List[stats.AlertRecord]:
    """The client's alerts with a Chile date in `[start, end]`, as plain records.

    Same pipeline as the Alertas page: `load_alerts_data` -> `prepare_alert_rows` ->
    `filter_prepared_rows` (Chile calendar days, both ends inclusive).
    """
    # Imported here: the dashboard components are heavy and only the builder needs them.
    from dashboard.components.alerts_report import filter_prepared_rows, prepare_alert_rows
    from src.data.loaders import load_alerts_data

    with forced_language("es"):
        alerts = load_alerts_data(client)
        if alerts is None or alerts.empty:
            return []
        frame = filter_prepared_rows(prepare_alert_rows(alerts), start_date=start, end_date=end)
    if frame.empty:
        return []

    local = (
        pd.to_datetime(frame["Timestamp"]).dt.tz_localize("UTC").dt.tz_convert(config.MAILING_TIMEZONE)
    )
    records: List[stats.AlertRecord] = []
    for position, (_, row) in enumerate(frame.iterrows()):
        if pd.isna(local.iloc[position]):
            continue
        records.append(stats.AlertRecord(
            unit=str(row["UnitId"]).strip(),
            when=local.iloc[position].to_pydatetime(),
            system=_text(row.get("system_display")),
            component=_text(row.get("component_display")),
            source=_text(row.get("source_display")),
            is_multi=str(row.get("Trigger_type", "")).strip() == "Mixto",
            diagnosis=_text(row.get("diagnosis_display")),
        ))
    return records


def _text(value) -> str:
    if value is None or (not isinstance(value, (list, tuple, dict)) and pd.isna(value)):
        return ""
    return str(value).strip()


# --------------------------------------------------------------------------- rendering


def client_display_name(client: str) -> str:
    return config.client_display_name(client)


def _period_texts(period: periods.Period, frequency: str, schedule: dict):
    start, end = periods.format_date(period.start), periods.format_date(period.end)
    if period.days == 1:
        subtitle_period, footer_period = f"Período {start}", f"el {start}"
    else:
        subtitle_period, footer_period = f"Período {start} – {end}", f"entre el {start} y el {end}"
    if frequency == periods.WEEKLY:
        day = periods.WEEKDAY_ES[schedule["weekday"].lower()]
        cadence = f"cada {day}"
    else:
        cadence = "todos los días"
    when = periods.parse_time(schedule["time"]).strftime("%H:%M")
    footer = (
        f"Este resumen se genera automáticamente {cadence} a las {when} (hora de Chile) "
        f"y cubre las alertas registradas {footer_period}."
    )
    return subtitle_period, footer


def render_alert_summary(
    client: str,
    schedule: dict,
    period: periods.Period,
    send_date: date,
    records: List[stats.AlertRecord],
    button_url: Optional[str] = None,
) -> ReportContent:
    """Pure rendering: records in, `ReportContent` out (no I/O)."""
    frequency = schedule["frequency"]
    subject = periods.build_subject(send_date)
    subtitle_period, footer = _period_texts(period, frequency, schedule)
    total = len(records)
    units = len(stats.unit_counts(records))

    context = {
        "subject": subject,
        "title": periods.report_title(frequency),
        "subtitle": f"Flota {client_display_name(client)} · {subtitle_period}",
        "headline": stats.headline(total, units),
        "empty": total == 0,
        "sentence": stats.summary_sentence(records) if total else "",
        "total": total,
        "button_url": button_url,
        "footer": footer,
        "kpis": [], "unit_rows": [], "unit_note": False, "system_rows": [], "featured": [],
    }

    meta = {"report": ALERT_SUMMARY, "variant": frequency, "total_alerts": total, "affected_units": units}
    if total:
        systems = [
            {"name": r.name, "count": r.count, "bar_pct": r.bar_pct, "pct": r.pct, "color": ""}
            for r in stats.system_rows(records)
        ]
        palette = system_colors([row["name"] for row in systems])
        for row in systems:
            row["color"] = palette[row["name"]]
        main = systems[0]
        unit_rows = stats.unit_rows(records)
        context.update(
            kpis=[
                {"label": "Total de Alertas", "value": total, "size": 26,
                 "caption": "últimos 7 días" if frequency == periods.WEEKLY else "último día",
                 "bg": "#fee2e2", "fg": "#b91c1c"},
                {"label": "Unidades Afectadas", "value": units, "size": 26,
                 "caption": "con al menos 1 alerta", "bg": "#dbeafe", "fg": "#1d4ed8"},
                {"label": "Sistema Principal", "value": main["name"], "size": 16,
                 "caption": f"{main['count']} alertas · {main['pct']}%" if main["count"] != 1
                 else f"1 alerta · {main['pct']}%", "bg": "#f1f5f9", "fg": "#1e3a5f"},
            ],
            unit_rows=[r.__dict__ for r in unit_rows],
            unit_note=stats.has_compressed_rows(unit_rows),
            system_rows=systems,
            featured=[_featured_row(r) for r in stats.featured_alerts(records)],
        )
    html = _env.get_template("alert_summary.html").render(**context)
    return ReportContent(subject=subject, html=html, meta=meta)


def _featured_row(record: stats.AlertRecord) -> dict:
    chip_bg, chip_fg = SOURCE_CHIPS.get(record.source, DEFAULT_CHIP)
    return {
        "date": record.when.strftime("%d/%m"),
        "unit": record.unit,
        "source": record.source or stats.MISSING,
        "chip_bg": chip_bg,
        "chip_fg": chip_fg,
        "system": record.system or stats.MISSING,
        "component": record.component or stats.MISSING,
        "diagnosis": stats.truncate_diagnosis(record.diagnosis),
    }


# --------------------------------------------------------------------------- builder


ALERTS_PAGE_PATH = "/monitoring/alerts"  # dashboard/pages/monitoring_alerts.py


def get_dashboard_alerts_url() -> Optional[str]:
    """Button target: `config.DASHBOARD_URL` (public base, prefix included) + the Alertas page."""
    base = config.DASHBOARD_URL
    return f"{base.rstrip('/')}{ALERTS_PAGE_PATH}" if base else None


def build_alert_summary(request: ReportRequest) -> ReportContent:
    """Report builder registered for the mailing service."""
    schedule = config.get_schedule(request.client)
    if schedule is None:
        raise MailingError("Este cliente no tiene envío de resúmenes configurado.", code="not_configured")
    period = periods.Period(request.period_start, request.period_end)
    records = load_period_records(request.client, period.start, period.end)

    url = get_dashboard_alerts_url()
    if not url:
        logger.warning("mailing: DASHBOARD_URL is not set; the email goes without the button")
    content = render_alert_summary(request.client, schedule, period, request.send_date, records, url)
    logger.info("mailing: alert summary built (client=%s meta=%s)", request.client, content.meta)
    return content


register_report_builder(ALERT_SUMMARY, build_alert_summary)
