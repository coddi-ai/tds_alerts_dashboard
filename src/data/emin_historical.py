"""Read the immutable EMIN historical-analysis bundle synced with dashboard data."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.data.catalog import dashboard_data_root


_RUN_PATTERN = re.compile(r"^[0-9]{8}T[0-9]{4}[+-][0-9]{4}-[0-9a-f]{64}$")
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


def load_emin_historical_bundle(
    data_root: str | Path | None = None,
    run_name: str | None = None,
) -> EminHistoricalBundle:
    """Load one complete immutable run below ``data/emin_historical/published``.

    When ``run_name`` is omitted, the locally synced ``latest.json`` pointer is
    used. The pointer can only select a package within the configured data
    directory; the dashboard never downloads or writes source data here.
    """
    root = dashboard_data_root(data_root)
    published = (root / "emin_historical" / "published").resolve()
    if run_name is None:
        pointer_path = published / "latest.json"
        try:
            pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise FileNotFoundError("No se encontró un paquete histórico EMIN sincronizado") from None
        except (OSError, json.JSONDecodeError) as exc:
            raise InvalidHistoricalBundle("El puntero del paquete EMIN no se puede leer") from exc
        run_name = pointer.get("run") if isinstance(pointer, dict) else None

    if not isinstance(run_name, str) or not _RUN_PATTERN.fullmatch(run_name):
        raise InvalidHistoricalBundle("El identificador del paquete EMIN no es válido")

    run_path = (published / run_name).resolve()
    try:
        run_path.relative_to(published)
    except ValueError as exc:
        raise InvalidHistoricalBundle("El paquete EMIN está fuera de su carpeta autorizada") from exc

    try:
        signatures = tuple(
            (run_path / filename).stat().st_mtime_ns
            if (run_path / filename).is_file()
            else -1
            for filename in ("manifest.json", "daily.json", "observed.json")
        )
    except OSError as exc:
        raise InvalidHistoricalBundle("No se puede revisar la carpeta del paquete EMIN") from exc

    return _load_run_cached(str(run_path), signatures)


@lru_cache(maxsize=1)
def _load_run_cached(run_path: str, signatures: tuple[int, int, int]) -> EminHistoricalBundle:
    folder = Path(run_path)
    manifest_path = folder / "manifest.json"
    daily_path = folder / "daily.json"
    observed_path = folder / "observed.json"
    if signatures[0] < 0 or signatures[1] < 0:
        raise InvalidHistoricalBundle("El paquete EMIN no tiene manifiesto o ranking diario")

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        daily = json.loads(daily_path.read_text(encoding="utf-8"))
        observed = json.loads(observed_path.read_text(encoding="utf-8")) if signatures[2] >= 0 else []
    except (OSError, json.JSONDecodeError) as exc:
        raise InvalidHistoricalBundle("Un archivo del paquete EMIN no se puede leer") from exc

    if not isinstance(manifest, dict) or manifest.get("synthetic") is not False:
        raise InvalidHistoricalBundle("El dashboard solo muestra paquetes EMIN observados")
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

    return EminHistoricalBundle(
        run=folder.name,
        manifest=manifest,
        daily=tuple(daily),
        observed=tuple(observed),
    )


def clear_emin_historical_cache() -> None:
    """Clear the package cache; exposed for deterministic unit tests."""
    _load_run_cached.cache_clear()
