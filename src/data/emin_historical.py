"""Read the immutable EMIN historical-analysis bundle synced with dashboard data."""

from __future__ import annotations

import json
import gzip
import re
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.data.catalog import dashboard_data_root


_RUN_PATTERN = re.compile(r"^[0-9]{8}T[0-9]{4}[+-][0-9]{4}-[0-9a-f]{64}$")
_WEEK_PATTERN = re.compile(r"^[0-9]{4}-W[0-9]{2}$")
_REQUIRED_DAILY_FIELDS = {"cutoff", "day", "unit", "rank", "points", "has_observation"}
_BETA_STATUSES = {"worsened", "stable", "improved", "insufficient"}
_BETA_QUADRANTS = {"healthy", "recent_improvement", "critical", "recent_worsening"}


class InvalidHistoricalBundle(ValueError):
    """The EMIN package is missing, synthetic, or does not match its contract."""


@dataclass(frozen=True)
class EminHistoricalBundle:
    """Validated, immutable package data for the EMIN historical page."""

    run: str
    manifest: dict[str, Any]
    daily: tuple[dict[str, Any], ...]
    observed: tuple[dict[str, Any], ...]
    dashboard: dict[str, Any]


def load_emin_historical_bundle(
    data_root: str | Path | None = None,
    run_name: str | None = None,
) -> EminHistoricalBundle:
    """Load one complete immutable run below ``data/fleet_history/golden/emin``.

    Each ISO week has a ``latest.json`` pointer to versioned files in the same
    folder. The dashboard chooses the newest ISO week and its current pointer, and
    only reads the locally synced data tree.
    """
    root = dashboard_data_root(data_root)
    published = (root / "fleet_history" / "golden" / "emin").resolve()
    try:
        pointers = []
        for folder in published.iterdir():
            if not folder.is_dir() or not _WEEK_PATTERN.fullmatch(folder.name):
                continue
            pointer_path = folder / "latest.json"
            try:
                pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                continue
            except (OSError, json.JSONDecodeError) as exc:
                raise InvalidHistoricalBundle("El puntero del paquete EMIN no se puede leer") from exc
            if isinstance(pointer, dict) and pointer.get("week_year_iso") == folder.name:
                pointers.append((pointer.get("published_at", ""), folder, pointer))
    except FileNotFoundError:
        raise FileNotFoundError("No se encontró un paquete histórico EMIN sincronizado") from None
    except OSError as exc:
        raise InvalidHistoricalBundle("No se pueden revisar los paquetes EMIN sincronizados") from exc

    if run_name is not None:
        if not isinstance(run_name, str) or not _RUN_PATTERN.fullmatch(run_name):
            raise InvalidHistoricalBundle("El identificador del paquete EMIN no es válido")
        pointers = [entry for entry in pointers if entry[2].get("run") == run_name]
    if not pointers:
        raise FileNotFoundError("No se encontró el paquete histórico EMIN seleccionado")
    _, run_path, pointer = max(pointers, key=lambda entry: (entry[1].name, entry[0]))
    run_name = pointer.get("run")
    if not isinstance(run_name, str) or not _RUN_PATTERN.fullmatch(run_name):
        raise InvalidHistoricalBundle("El identificador del paquete EMIN no es válido")
    files = pointer.get("files")
    required = ("manifest.json", "daily.json", "observed.json", "dashboard.json.gz")
    if not isinstance(files, dict) or any(
        not isinstance(files.get(name), str)
        or files[name] != f"{run_name}--{name}"
        for name in required
    ):
        raise InvalidHistoricalBundle("El puntero no declara los archivos del paquete EMIN")
    try:
        signatures = tuple(
            (run_path / files[name]).stat().st_mtime_ns
            if (run_path / files[name]).is_file()
            else -1
            for name in required
        )
    except OSError as exc:
        raise InvalidHistoricalBundle("No se puede revisar la carpeta del paquete EMIN") from exc
    return _load_run_cached(str(run_path), run_name, tuple(files[name] for name in required), signatures)


@lru_cache(maxsize=1)
def _load_run_cached(run_path: str, run_name: str, files: tuple[str, ...], signatures: tuple[int, ...]) -> EminHistoricalBundle:
    folder = Path(run_path)
    manifest_path, daily_path, observed_path, dashboard_path = (folder / name for name in files)
    if signatures[0] < 0 or signatures[1] < 0 or signatures[3] < 0:
        raise InvalidHistoricalBundle("El paquete EMIN no tiene manifiesto, ranking diario o vistas del dashboard")

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        daily = json.loads(daily_path.read_text(encoding="utf-8"))
        observed = json.loads(observed_path.read_text(encoding="utf-8")) if signatures[2] >= 0 else []
        with gzip.open(dashboard_path, "rt", encoding="utf-8") as stream:
            dashboard = json.load(stream)
    except (OSError, json.JSONDecodeError) as exc:
        raise InvalidHistoricalBundle("Un archivo del paquete EMIN no se puede leer") from exc

    if not isinstance(manifest, dict) or manifest.get("synthetic") is not False:
        raise InvalidHistoricalBundle("El dashboard solo muestra paquetes EMIN observados")
    supported_contracts = {
        "coddi.emin.historical-dashboard.v1",
        "coddi.emin.historical-dashboard.v2",
        "coddi.emin.historical-dashboard.v3",
        "coddi.emin.historical-dashboard.v4",
        "coddi.emin.historical-dashboard.v5",
    }
    contract = manifest.get("dashboard_contract") if isinstance(manifest, dict) else None
    if contract not in supported_contracts or not isinstance(dashboard, dict) or dashboard.get("contract") != contract:
        raise InvalidHistoricalBundle("Las vistas precalculadas del dashboard no coinciden con el contrato EMIN")
    if not isinstance(daily, list) or not isinstance(observed, list):
        raise InvalidHistoricalBundle("El paquete EMIN tiene una estructura inválida")
    for row in daily:
        if not isinstance(row, dict) or not _REQUIRED_DAILY_FIELDS <= row.keys():
            raise InvalidHistoricalBundle("El ranking diario no coincide con el contrato EMIN")
        if not isinstance(row["day"], str) or not isinstance(row["unit"], str):
            raise InvalidHistoricalBundle("El ranking diario contiene fechas o equipos inválidos")
        if not isinstance(row.get("event_groups", []), list):
            raise InvalidHistoricalBundle("Los grupos de eventos del paquete EMIN son inválidos")
    if any(not isinstance(row, dict) for row in observed):
        raise InvalidHistoricalBundle("La evidencia observada del paquete EMIN es inválida")
    report = dashboard.get("beta_report")
    if report is not None:
        _validate_beta_report(report, dashboard.get("metadata", {}))
        condition_model = report.get("condition_model")
        if condition_model is not None:
            _validate_condition_model(condition_model, manifest.get("condition_model"), report)
        elif manifest.get("condition_model") is not None:
            raise InvalidHistoricalBundle("El manifiesto declara un modelo de condición que no está en las vistas")

    # Resolve package row references only. Scoring, classification and aggregation are
    # already materialized by the producer and are never recomputed in the dashboard.
    for cutoff, fleet_view in dashboard.get("fleet", {}).items():
        row_ids = fleet_view.get("row_ids")
        if isinstance(row_ids, list):
            fleet_view["rows"] = [daily[index] for index in row_ids if isinstance(index, int) and 0 <= index < len(daily)]
        group_ids = fleet_view.get("group_row_ids")
        if isinstance(group_ids, dict):
            fleet_view["groups"] = {
                group: [daily[index] for index in indexes if isinstance(index, int) and 0 <= index < len(daily)]
                for group, indexes in group_ids.items() if isinstance(indexes, list)
            }
    for unit, unit_view in dashboard.get("units", {}).items():
        daily_ids, evidence_ids = unit_view.get("daily_ids"), unit_view.get("evidence_ids")
        if isinstance(daily_ids, list):
            unit_view["daily"] = [daily[index] for index in daily_ids if isinstance(index, int) and 0 <= index < len(daily)]
        if isinstance(evidence_ids, list):
            unit_view["evidence"] = [observed[index] for index in evidence_ids if isinstance(index, int) and 0 <= index < len(observed)]
        for selected in unit_view.get("by_cutoff", {}).values():
            trend_ids = selected.get("trend_ids") if isinstance(selected, dict) else None
            if isinstance(trend_ids, list):
                selected["trend"] = [daily[index] for index in trend_ids if isinstance(index, int) and 0 <= index < len(daily)]

    return EminHistoricalBundle(
        run=run_name,
        manifest=manifest,
        daily=tuple(daily),
        observed=tuple(observed),
        dashboard=dashboard,
    )


def clear_emin_historical_cache() -> None:
    """Clear the package cache; exposed for deterministic unit tests."""
    _load_run_cached.cache_clear()


def _validate_beta_report(report, metadata):
    error = "El informe Beta de EMIN no coincide con su contrato"
    if not isinstance(report, dict) or report.get("version") != 1:
        raise InvalidHistoricalBundle(error)
    cutoff, counts = report.get("cutoff"), report.get("counts")
    if (
        not isinstance(cutoff, dict) or not _WEEK_PATTERN.fullmatch(str(cutoff.get("week")))
        or not isinstance(cutoff.get("complete"), bool)
        or not isinstance(counts, dict) or set(counts) != _BETA_STATUSES
        or any(not isinstance(count, int) or count < 0 for count in counts.values())
        or not isinstance(report.get("methodology"), str)
        or not isinstance(report.get("rows"), list) or not isinstance(report.get("units"), dict)
        or not isinstance(metadata, dict) or not isinstance(metadata.get("variation_stability_tolerance"), (int, float))
    ):
        raise InvalidHistoricalBundle(error)
    if any(not isinstance(report.get(key), list) or not all(isinstance(item, str) for item in report[key])
           for key in ("domains", "groups")):
        raise InvalidHistoricalBundle(error)
    try:
        start = date.fromisoformat(report["start"])
        end = date.fromisoformat(cutoff["cutoff"])
        if start > end or sum(counts.values()) != len(report["rows"]):
            raise ValueError
        scoped = "analysis_start" in report
        if scoped and (date.fromisoformat(report["analysis_start"]) != start or start != date(2024, 1, 1)):
            raise ValueError
        zones = report.get("quadrants")
        if zones is not None:
            zone_counts = zones["counts"]
            comparable = len(report["rows"]) - counts["insufficient"]
            threshold = zones["threshold"]
            if (not isinstance(zone_counts, dict) or set(zone_counts) != _BETA_QUADRANTS
                    or any(not isinstance(count, int) or count < 0 for count in zone_counts.values())
                    or sum(zone_counts.values()) != comparable
                    or (comparable and (not isinstance(threshold, (int, float)) or not 1 <= threshold < float("inf")))
                    or (not comparable and threshold is not None)):
                raise ValueError
        scoring_counts = report.get("scoring_coverage")
        if scoring_counts is not None and (
            report.get("scoring_review_version") != 1 or not isinstance(scoring_counts, dict)
            or set(scoring_counts) != {"verified", "preliminary", "insufficient"}
            or any(type(value) is not int or value < 0 for value in scoring_counts.values())
            or sum(scoring_counts.values()) != len(report["rows"])
        ):
            raise ValueError
        weekly_order = report.get("weekly_review_order")
        if weekly_order is not None:
            candidates = {row["unit"] for row in report["rows"] if row["scoring_review"]["finding_id"] is not None}
            if (report.get("scoring_review_version") != 1 or not isinstance(weekly_order, list)
                    or len(weekly_order) != len(candidates) or set(weekly_order) != candidates):
                raise ValueError
        for row in report["rows"]:
            unit = report["units"][row["unit"]]
            comparison = row["comparison"]
            if (comparison["status"] not in _BETA_STATUSES
                    or not isinstance(comparison["missing"], list)
                    or not isinstance(row["domains"], dict) or not isinstance(row["groups"], list)
                    or not all(isinstance(unit[key], list) for key in ("records", "headline", "oil", "timeline"))):
                raise ValueError
            if report.get("scoring_review_version") == 1:
                review = row["scoring_review"]
                coverage = review["coverage"]
                finding = review["finding_id"]
                if (coverage["state"] not in {"verified", "preliminary", "insufficient"}
                        or review["level"] not in {"high", "low", None}
                        or any(type(coverage[key]) is not int or coverage[key] < 0
                               for key in ("verified_current_days", "verified_prior_weeks"))
                        or (finding is not None and (type(finding) is not int or not any(
                            record["id"] == finding and record["week"] == cutoff["week"]
                            for record in unit["records"])))):
                    raise ValueError
                history = review.get("finding_history")
                if history is not None:
                    weeks, oil, safety, both = (history[key] for key in ("weeks", "oil_weeks", "safety_weeks", "both_weeks"))
                    latest = history["latest_week"]
                    if (any(type(value) is not int or value < 0 for value in (weeks, oil, safety, both))
                            or both > min(oil, safety) or weeks != oil + safety - both
                            or (weeks == 0 and latest is not None)
                            or (weeks > 0 and (not _WEEK_PATTERN.fullmatch(str(latest)) or latest > cutoff["week"]))):
                        raise ValueError
            if scoped and not isinstance(unit["milestone_ids"], list):
                raise ValueError
            if zones is not None and not comparison["missing"] and comparison.get("quadrant") not in _BETA_QUADRANTS:
                raise ValueError
    except (KeyError, ValueError, TypeError):
        raise InvalidHistoricalBundle(error) from None


def _validate_condition_model(model, manifest_model, report):
    error = "El modelo de condición EMIN no coincide con su contrato"
    try:
        if (not isinstance(model, dict) or model.get("version") != 2
                or type(model.get("threshold")) is not int or model["threshold"] < 2
                or type(model.get("alert_threshold")) is not int
                or not 1 <= model["alert_threshold"] < model["threshold"]
                or not isinstance(model.get("rows"), list)
                or not isinstance(model.get("provenance"), dict)
                or not isinstance(manifest_model, dict)):
            raise ValueError
        provenance = model["provenance"]
        for field in ("run_id", "sha256", "manifest_sha256", "base_package_run", "cutoff"):
            if provenance.get(field) != manifest_model.get(field):
                raise ValueError
        for field in ("sha256", "manifest_sha256", "source_columns_sha256", "base_package_manifest_sha256"):
            digest = provenance.get(field)
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError
        if (type(provenance.get("alerts_rows")) is not int or provenance["alerts_rows"] < 0
                or not isinstance(provenance.get("coverage_limitations"), list)
                or not isinstance(provenance.get("preview"), bool)
                or provenance.get("cutoff") != report["cutoff"]["cutoff"]):
            raise ValueError
        base_hashes = provenance.get("base_package_files_sha256")
        if (not isinstance(base_hashes, dict)
                or set(base_hashes) != {"daily.json", "observed.json", "dashboard.json.gz"}
                or any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)
                       for value in base_hashes.values())):
            raise ValueError
        expected_units = {row["unit"] for row in report["rows"]}
        rows = model["rows"]
        units = [row.get("unit") for row in rows if isinstance(row, dict)]
        if len(rows) != len(units) or len(set(units)) != len(units) or set(units) != expected_units:
            raise ValueError
        cutoff = date.fromisoformat(report["cutoff"]["cutoff"])
        for row in rows:
            current = row.get("current")
            if current is not None:
                if (not isinstance(current, dict)
                        or current.get("level") not in {"clear", "monitor", "alert", "critical"}
                        or current.get("movement") not in _BETA_STATUSES
                        or (current.get("points") is not None and
                            (not isinstance(current["points"], (int, float)) or current["points"] < 0))
                        or not isinstance(current.get("changes"), list)
                        or not isinstance(current.get("active"), list)):
                    raise ValueError
            if (row.get("historical_points") is not None
                    and (not isinstance(row["historical_points"], (int, float)) or row["historical_points"] < 0)):
                raise ValueError
            if not isinstance(row.get("weeks"), list) or not isinstance(row.get("source_dates"), dict):
                raise ValueError
            for day in row["source_dates"].values():
                if day is not None and date.fromisoformat(day) > cutoff:
                    raise ValueError
            for week in row["weeks"]:
                if (not isinstance(week, dict) or not _WEEK_PATTERN.fullmatch(str(week.get("week")))
                        or week["week"] > report["cutoff"]["week"]
                        or (week.get("points") is not None and
                            (not isinstance(week["points"], (int, float)) or week["points"] < 0))):
                    raise ValueError
        classification = model.get("classification")
        if classification is not None:
            if (not isinstance(classification, dict)
                    or any(type(classification.get(key)) is not int or classification[key] < 0
                           for key in ("alerts_scored", "alerts_not_scored", "other_source_signals"))
                    or not isinstance(classification.get("alerts_by_domain_group"), dict)
                    or any(type(value) is not int or value < 0
                           for value in classification["alerts_by_domain_group"].values())):
                raise ValueError
    except (KeyError, ValueError, TypeError, OverflowError):
        raise InvalidHistoricalBundle(error) from None
