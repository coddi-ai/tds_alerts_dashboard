"""Laboratory turnaround KPIs, computed once for the dashboard and for Campbell AI.

Monitoring > Oil > Laboratorio is the functional reference. It used to own the whole
calculation inside its callbacks, so an assistant answering the same question had to
reproduce the filters, the period and the denominators by hand - which is how the two ended
up disagreeing about a number the user reads side by side.

Three durations, all in whole days, from the three dates a sample carries:

- **Tránsito** = ``labDate - sampleDate``: extraction to reception at the lab.
- **Laboratorio** = ``reportDate - labDate``: reception to published report.
- **Diagnóstico** = ``reportDate - sampleDate``: the whole path, and the only one available
  when the source has no usable ``labDate``.

Decisions this module fixes, because they change the numbers and had to be stated somewhere
(they mirror the dashboard's current behaviour except where noted):

- **The period filters on ``reportDate``** and a row without one is excluded: it has no
  publication date, so it cannot belong to a publication period.
- **The final day is complete.** A date-only ``end_date`` covers the whole day, so a report
  published at 14:00 on the last day is included. The dashboard's ``<= Timestamp(end_date)``
  silently dropped those; here the boundary is ``< end + 1 day``. Same result for the
  midnight-stamped data in service today, correct for data that carries a time.
- **Default period**: six months back from the newest ``reportDate`` present, floored at the
  oldest one. Reported in the result, never implied.
- **A missing date is not a duration of zero.** Each average carries its own denominator, and
  rows the source could not date are counted separately.
- **Every excluded row is counted.** A sample with no extraction date cannot produce any of the
  three durations and is dropped, exactly as the dashboard does - but silently dropping it left
  a total that could not be reconciled with the source. The counts now add up:
  ``source_rows = excluded_without_sample_date + dated_samples``, and of those dated samples
  ``samples_without_report_date`` fall outside any publication period while the rest are
  filtered into ``total_samples``.
- **Negative durations are kept and counted**, not clipped: an inverted pair of dates is a
  data problem to surface, and silently turning it into zero hides it.
- **``labDate`` is optional.** Without it transit and lab time are unavailable - not zero -
  and the diagnostic time still answers the question.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import pandas as pd

# The three dates every duration is derived from.
SAMPLE_DATE = "sampleDate"
LAB_DATE = "labDate"
REPORT_DATE = "reportDate"

# The field the period filters on: a KPI about published reports is bounded by publication.
PERIOD_FIELD = REPORT_DATE

DURATION_COLUMNS = ("transit_time", "lab_time", "diagnostic_time")
DURATION_UNIT = "dias"

# Default lookback for the aggregate view, matching the dashboard's own date picker.
DEFAULT_PERIOD_MONTHS = 6

METRIC_LABELS: dict[str, str] = {
    "transit_time": "Tiempo de tránsito (extracción a recepción en laboratorio)",
    "lab_time": "Tiempo de laboratorio (recepción a informe)",
    "diagnostic_time": "Tiempo de diagnóstico (extracción a informe)",
}


@dataclass(frozen=True)
class LabPeriod:
    """The period actually applied, so an answer can state it instead of implying it."""

    start: Optional[pd.Timestamp]
    end: Optional[pd.Timestamp]
    source: str  # "default" | "requested"

    def as_payload(self) -> dict[str, Any]:
        return {
            "field": PERIOD_FIELD,
            "start": self.start.date().isoformat() if self.start is not None else None,
            "end": self.end.date().isoformat() if self.end is not None else None,
            "source": self.source,
            "final_day_included": True,
        }


def normalize_lab_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Parse the three dates and derive the three durations.

    A frame with no ``labDate`` column keeps the column as ``NaT`` rather than being rejected:
    transit and lab time are then unavailable, which is a different answer from zero.
    """
    if frame is None or frame.empty:
        return pd.DataFrame(
            columns=[SAMPLE_DATE, LAB_DATE, REPORT_DATE, "unitId", *DURATION_COLUMNS]
        )
    working = frame.copy()
    for column in (SAMPLE_DATE, LAB_DATE, REPORT_DATE):
        if column in working.columns:
            working[column] = pd.to_datetime(
                working[column], errors="coerce", utc=True
            ).dt.tz_localize(None)
        else:
            working[column] = pd.NaT

    # Nothing can be computed without an extraction date. The count of what this removes is
    # reported by `compute_lab_kpis`; see `count_undated_samples`.
    working = working.dropna(subset=[SAMPLE_DATE])
    working["transit_time"] = (working[LAB_DATE] - working[SAMPLE_DATE]).dt.days
    working["lab_time"] = (working[REPORT_DATE] - working[LAB_DATE]).dt.days
    working["diagnostic_time"] = (working[REPORT_DATE] - working[SAMPLE_DATE]).dt.days
    keep = [SAMPLE_DATE, LAB_DATE, REPORT_DATE, "unitId", "componentName", "sampleNumber"]
    keep = [column for column in keep if column in working.columns]
    return working[[*keep, *DURATION_COLUMNS]].copy()


def count_undated_samples(frame: pd.DataFrame) -> int:
    """Rows the source carries with no usable extraction date.

    They cannot produce transit, lab or diagnostic time, so they are excluded - but a total
    that silently omits them cannot be reconciled against the source, which is the question a
    reader asks when the number looks low.
    """
    if frame is None or frame.empty:
        return 0
    if SAMPLE_DATE not in frame.columns:
        # No extraction date at all: every row is undated.
        return int(len(frame))
    parsed = pd.to_datetime(frame[SAMPLE_DATE], errors="coerce", utc=True)
    return int(parsed.isna().sum())


def default_lab_period(frame: pd.DataFrame) -> LabPeriod:
    """Six months up to the newest published report, floored at the oldest one."""
    if frame.empty or REPORT_DATE not in frame.columns:
        return LabPeriod(None, None, "default")
    dated = frame[REPORT_DATE].dropna()
    if dated.empty:
        return LabPeriod(None, None, "default")
    newest = dated.max().normalize()
    oldest = dated.min().normalize()
    start = max(oldest, (newest - pd.DateOffset(months=DEFAULT_PERIOD_MONTHS)).normalize())
    return LabPeriod(start, newest, "default")


def resolve_lab_period(
    frame: pd.DataFrame, start_date: Any = "", end_date: Any = ""
) -> LabPeriod:
    """The requested period when one was given, otherwise the declared default."""
    requested_start = _parse_boundary(start_date)
    requested_end = _parse_boundary(end_date)
    if requested_start is None and requested_end is None:
        return default_lab_period(frame)
    fallback = default_lab_period(frame)
    return LabPeriod(
        requested_start if requested_start is not None else fallback.start,
        requested_end if requested_end is not None else fallback.end,
        "requested",
    )


def _parse_boundary(value: Any) -> Optional[pd.Timestamp]:
    if value is None or not str(value).strip():
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return pd.Timestamp(parsed).tz_localize(None) if parsed.tzinfo else pd.Timestamp(parsed)


def filter_lab_period(frame: pd.DataFrame, period: LabPeriod) -> pd.DataFrame:
    """Rows published inside the period, with the final day counted in full."""
    if frame.empty:
        return frame
    scoped = frame.dropna(subset=[REPORT_DATE])
    if period.start is not None:
        scoped = scoped[scoped[REPORT_DATE] >= period.start.normalize()]
    if period.end is not None:
        # The whole final day, so a report published during it is not dropped for having a
        # time later than midnight.
        scoped = scoped[scoped[REPORT_DATE] < period.end.normalize() + pd.Timedelta(days=1)]
    return scoped.copy()


def has_positive_lab_time(frame: pd.DataFrame) -> bool:
    """Whether the split transit/lab view is meaningful for this population.

    Sources that stamp ``labDate`` equal to ``reportDate`` produce an all-zero lab time, which
    reads as "the lab took no time" rather than "reception was not recorded separately". The
    dashboard falls back to the diagnostic time in that case and so does this.
    """
    if "lab_time" not in frame.columns:
        return False
    values = frame["lab_time"].dropna()
    return bool((values > 0).any())


def _average(frame: pd.DataFrame, column: str) -> dict[str, Any]:
    """One average with everything needed to audit it: denominator, spread, exclusions."""
    if column not in frame.columns:
        return {
            "available": False,
            "reason": "La fuente no permite calcular esta metrica",
            "unit": DURATION_UNIT,
        }
    series = frame[column]
    valid = series.dropna()
    payload: dict[str, Any] = {
        "available": bool(len(valid)),
        "unit": DURATION_UNIT,
        "label": METRIC_LABELS.get(column, column),
        "valid_samples": int(len(valid)),
        "missing_samples": int(series.isna().sum()),
        "negative_samples": int((valid < 0).sum()),
        "zero_samples": int((valid == 0).sum()),
    }
    if not len(valid):
        # No denominator: explicitly not a mean of zero.
        payload["average"] = None
        payload["reason"] = (
            "Sin muestras con las dos fechas necesarias; no disponible, no cero."
        )
        return payload
    payload["average"] = round(float(valid.mean()), 1)
    payload["min"] = int(valid.min())
    payload["max"] = int(valid.max())
    return payload


def compute_lab_kpis(
    frame: pd.DataFrame,
    *,
    start_date: Any = "",
    end_date: Any = "",
    threshold_days: float | None = None,
) -> dict[str, Any]:
    """The laboratory KPI block: period, population, each average and its denominator.

    `frame` is the raw classified-oil frame; normalization and filtering happen here so every
    consumer shares one population.
    """
    source_rows = 0 if frame is None or frame.empty else int(len(frame))
    undated = count_undated_samples(frame)
    normalized = normalize_lab_frame(frame)
    period = resolve_lab_period(normalized, start_date, end_date)
    scoped = filter_lab_period(normalized, period)

    payload: dict[str, Any] = {
        "period": period.as_payload(),
        "period_default_months": DEFAULT_PERIOD_MONTHS,
        "total_samples": int(len(scoped)),
        # The population, stated so it can be reconciled with the source rather than trusted:
        # source_rows = excluded_without_sample_date + dated_samples, and of the dated ones
        # samples_without_report_date sit outside any period.
        "source_rows": source_rows,
        "excluded_without_sample_date": undated,
        "dated_samples": int(len(normalized)),
        "samples_without_report_date": int(
            len(normalized) - int(normalized[REPORT_DATE].notna().sum())
        ),
        "samples_without_lab_date": int(
            len(scoped) - int(scoped[LAB_DATE].notna().sum()) if len(scoped) else 0
        ),
        "duration_unit": DURATION_UNIT,
    }
    if undated:
        payload["excluded_without_sample_date_detail"] = (
            "Filas descartadas por no tener fecha de extraccion valida: sin ella no se puede "
            "calcular ningun tiempo. Estan fuera de todos los denominadores; informalas como "
            "exclusion, no como demora cero."
        )
    if threshold_days is not None:
        payload["compliance_threshold_days"] = float(threshold_days)
        payload["compliance_threshold_note"] = (
            "Umbral de referencia configurado para este cliente. No es un SLA contractual "
            "verificado; no calcules un porcentaje de cumplimiento con el."
        )
    if not len(scoped):
        payload["metrics_available"] = False
        payload["detail"] = (
            "Sin informes publicados en el periodo. Es ausencia de datos, no cumplimiento "
            "total ni un promedio de cero."
        )
        return payload  # population counts above already explain what was excluded

    split = has_positive_lab_time(scoped)
    payload["metrics_available"] = True
    payload["reporting_mode"] = "transito_y_laboratorio" if split else "solo_diagnostico"
    payload["metrics"] = {
        "transit_time": _average(scoped, "transit_time"),
        "lab_time": _average(scoped, "lab_time"),
        "diagnostic_time": _average(scoped, "diagnostic_time"),
    }
    if not split:
        payload["reporting_mode_detail"] = (
            "El tiempo de laboratorio no tiene ningun valor positivo en el periodo: la fuente "
            "no distingue recepcion de informe. Reporta el tiempo de diagnostico y di que el "
            "desglose no esta disponible; no lo presentes como cero."
        )
    payload["note"] = (
        "Promedios en dias enteros sobre las muestras que tienen las dos fechas de cada "
        "metrica; cada una trae su propio denominador en valid_samples. Un dato faltante no "
        "es un cero. El periodo filtra por reportDate e incluye el dia final completo. La "
        "poblacion se reconcilia asi: source_rows = excluded_without_sample_date + "
        "dated_samples; de esas, samples_without_report_date quedan fuera de cualquier "
        "periodo y el resto se filtra a total_samples."
    )
    return payload


def lab_kpis_by_unit(
    frame: pd.DataFrame,
    *,
    start_date: Any = "",
    end_date: Any = "",
    column: str | None = None,
    top: int = 20,
) -> pd.Series:
    """Per-equipment average of one duration, over the same population as `compute_lab_kpis`."""
    normalized = normalize_lab_frame(frame)
    period = resolve_lab_period(normalized, start_date, end_date)
    scoped = filter_lab_period(normalized, period)
    if scoped.empty or "unitId" not in scoped.columns:
        return pd.Series(dtype="float64")
    resolved = column or (
        "transit_time" if has_positive_lab_time(scoped) else "diagnostic_time"
    )
    return (
        scoped.groupby("unitId")[resolved]
        .mean()
        .dropna()
        .sort_values(ascending=False)
        .head(top)
    )
