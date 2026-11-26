"""Read the immutable EMIN historical-analysis bundle synced with dashboard data."""

from __future__ import annotations

import json
import gzip
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.data.catalog import dashboard_data_root


_RUN_PATTERN = re.compile(r"^[0-9]{8}T[0-9]{4}[+-][0-9]{4}-[0-9a-f]{64}$")
_WEEK_PATTERN = re.compile(r"^[0-9]{4}-W[0-9]{2}$")
_REQUIRED_DAILY_FIELDS = {"cutoff", "day", "unit", "rank", "points", "has_observation"}


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
    folder. The dashboard chooses the pointer with the newest capture time and
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
    _, run_path, pointer = max(pointers, key=lambda entry: (entry[0], entry[1].name))
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
