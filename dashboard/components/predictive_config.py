"""
Configuración centralizada de modos de falla por cliente y componente.

Estructura de dos ejes: client -> component.
  - "cda":      configuración original (motor, transmision). Sin cambios de valores.
  - "capstone": nuevo cliente. El vocabulario de labels (telemetría y aceite)
                reutiliza los nombres ya validados en components/alerts_charts.py.

IMPORTANTE (datos de dominio de Capstone):
  Los modos de falla, el mapeo de variables por modo y los umbrales de aceite
  (OIL_THRESHOLDS["capstone"]) NO están confirmados con dominio todavía. Las
  entradas marcadas con `# TODO(capstone): validar con dominio` son placeholders
  funcionales construidos con señales que sí existen en el vocabulario Capstone,
  para que la app funcione sin caer al fallback de CDA. No se inventan umbrales
  numéricos: OIL_THRESHOLDS["capstone"] queda vacío hasta tener valores reales
  (un umbral equivocado es peor que uno ausente).
"""

import re

import pandas as pd

from src.utils.logger import get_logger
from src.charts.signals import SIGNAL_LABELS

logger = get_logger(__name__)


# =============================================================================
# Shared catalog  -  defined in src/data/predictive_catalog.py
# =============================================================================
#
# FAILURE_MODE_CONFIG, the label tables, FAILURE_MODE_METHODOLOGY and every accessor now live
# in `src` so Campbell AI reads the same mapping this tab renders. They are re-exported here
# unchanged: `from dashboard.components.predictive_config import ...` keeps working, and there
# is only one definition to keep correct.

from src.data.predictive_catalog import (  # noqa: F401  (re-exported)
    FAILURE_MODE_CONFIG,
    FAILURE_MODE_METHODOLOGY,
    OIL_LABELS,
    TELEMETRY_LABELS,
    get_all_oil_variables,
    get_available_components,
    get_failure_mode_label,
    get_failure_mode_methodology,
    get_failure_mode_options,
    get_failure_modes_dict,
    get_failure_modes_for_component,
    get_oil_variables_for_mode,
    get_signals_catalog,
    get_telemetry_signals_for_mode,
    get_telemetry_variables_for_mode,
    humanize_mode_key,
    resolve_failure_mode_options,
    resolve_failure_modes,
)


# =============================================================================
# OIL_THRESHOLDS  —  client -> {variable: {rango: (normal, alerta, critico)}}
# =============================================================================

OIL_THRESHOLDS = {
    "cda": {
        "Hierro":     {"LT_1000": (48.0, 57.0, 65.0), "GE_1000": (71.0, 84.0, 93.0)},
        "Cobre":      {"LT_1000": (5.0, 8.0, 17.0), "GE_1000": (7.0, 12.0, 51.0)},
        "Plomo":      {"LT_1000": (3.0, 5.0, 8.0), "GE_1000": (4.0, 5.0, 6.0)},
        "Silicio":    {"LT_1000": (5.0, 6.0, 8.0), "GE_1000": (5.0, 6.0, 7.0)},
        "Sodio":      {"LT_1000": (7.0, 9.0, 18.0), "GE_1000": (8.0, 9.0, 10.0)},
        "Viscocidad": {"LT_1000": (16.0, 17.0, 18.0), "GE_1000": (16.0, 17.0, 18.0)},
        "Hollín":     {"LT_1000": (64.0, 73.0, 84.0), "GE_1000": (91.0, 106.0, 120.0)},
        "Cromo":      {"LT_1000": (0.0, 0.5, 1.0), "GE_1000": (0.0, 0.5, 1.0)},
    },

    # TODO(capstone): sin umbrales de dominio confirmados. Se deja vacío a
    # propósito — las variables sin entrada simplemente no muestran zonas de
    # severidad (mismo comportamiento que una variable sin threshold en CDA).
    # Un umbral numérico equivocado sería peor que su ausencia.
    # Umbrales de aceite QSK60 (Capstone). El dataset de Capstone no separa por
    # rango de horas, así que ambos rangos (LT_1000 / GE_1000) apuntan al mismo
    # set (normal, alerta, crítico) — así el lookup por oilHourRange funciona
    # igual que en CDA sin tocar las funciones de charts/tablas.
    "capstone": {
        "Aluminio":    {"LT_1000": (3.0, 4.0, 5.0),   "GE_1000": (3.0, 4.0, 5.0)},
        "Boro":        {"LT_1000": (61.0, 63.0, 64.5),   "GE_1000": (61.0, 63.0, 64.5)},
        "Cobre":       {"LT_1000": (1.5, 5.0, 6.5),   "GE_1000": (1.5, 5.0, 6.5)},
        "Cromo":       {"LT_1000": (2.00, 3.0, 4.0),   "GE_1000": (2.00, 3.0, 4.0)},
        "Estaño":      {"LT_1000": (3.00, 3.0, 4.0),   "GE_1000": (3.00, 3.0, 4.0)},
        "Hierro":      {"LT_1000": (18.00, 19.0, 21.00), "GE_1000": (18.00, 19.0, 21.00)},
        "Hollín":      {"LT_1000": (1.50, 3.0, 4.50),   "GE_1000": (1.50, 3.0, 4.50)},
        "Oxidación":   {"LT_1000": (19.00, 24.5, 36.75), "GE_1000": (19.00, 24.5, 36.75)},
        "Plomo":       {"LT_1000": (2.5, 4.0, 6.0),   "GE_1000": (2.5, 4.0, 6.0)},
        "Potasio":     {"LT_1000": (3.0, 4.0, 10.5),   "GE_1000":  (3.0, 4.0, 10.5)},
        "Silicio":     {"LT_1000": (11.00, 12.0, 13.0), "GE_1000": (11.00, 12.0, 13.0)},
        "Sodio":       {"LT_1000": (4.0, 6.0, 13.5), "GE_1000": (4.0, 6.0, 13.5)},
        "Viscocidad":  {"LT_1000": (16.0, 17.0, 18.0), "GE_1000": (16.0, 17.0, 18.0)},
    },
}


# =============================================================================
# Four-limit Stewart lookup for the predictive oil-evidence view (v2.8)
# =============================================================================
#
# OIL_THRESHOLDS above is the legacy hardcoded 3-tuple table (kept only for
# historical reference - no live code path reads it anymore). The predictive
# oil-evidence view (predictive > {component} > evidence > oil evidence) now
# sources its limits from stewart_limits_four.parquet instead, via
# load_predictive_oil_limits_four() below.

# Machine dimension for the Stewart Limits lookup. Every predictive component
# today (motor, transmision) is a haul-truck subsystem - confirmed directly
# against stewart_limits_four.parquet, whose `machine` column is 'camion' for
# every row, for both CDA and CAPSTONE.
PREDICTIVE_STEWART_MACHINE = 'camion'

# Predictivo component key -> oil component name(s) it should match, for
# clients whose oil naming is more specific than Predictivo's coarse key.
# e.g. Capstone's engine oil data is grouped under "motor diesel" rather than
# the bare "motor" Predictivo uses, but "motor diesel" is the only oil
# component "motor" should ever resolve to - never a traction motor, even
# though "motor traccion ..." also starts with the same word. Shared by
# load_real_oil_samples (real/non-forward-filled oil samples) and
# load_predictive_oil_limits_four (Stewart Limits) below, so both lookups
# agree on which oil component a Predictivo key maps to.
_OIL_COMPONENT_ALIASES = {
    "motor": {"motor", "motor diesel"},
}


def _normalize_unit_id(unit_id):
    """T_09 -> T_9, same criterion used across the predictive module."""
    if pd.isna(unit_id):
        return unit_id
    unit_str = str(unit_id)
    match = re.match(r"^([A-Za-z]+)_(0+)(\d+)$", unit_str)
    if match:
        return f"{match.group(1)}_{match.group(3)}"
    return unit_str


def load_real_oil_samples(client: str, component: str, unit: str):
    """
    Load real (non-forward-filled) oil samples for a component/unit from the
    oil technique's golden layer (data/oil/golden/{client}/classified.parquet).

    Predictivo's component key ("motor", "transmision") is the grouped/coarse
    granularity, so it's matched against componentNameNormalized (Oil Data
    Contract v2.8: componentName is the fine-grained original name, e.g.
    "mando final izquierdo"; componentNameNormalized is the grouped version,
    e.g. "mando final" - the one that lines up with Predictivo's key). Falls
    back to componentName only if a client's classified.parquet has no
    componentNameNormalized column at all.

    Also consults _OIL_COMPONENT_ALIASES so a Predictivo key can match a more
    specific oil component name (e.g. "motor" -> "motor diesel"), without
    pulling in unrelated components that merely start with the same word
    (e.g. Capstone's traction motors).

    Returns None when nothing matches, so callers can show an empty state
    instead of a fabricated chart/table.
    """
    from src.data.loaders import load_oil_classified

    try:
        df_classified = load_oil_classified(client)
    except Exception as exc:  # noqa: BLE001 - treat as no data on any load issue
        logger.warning(f"No se pudo cargar classified.parquet para {client}: {exc}")
        return None

    if df_classified is None or df_classified.empty:
        return None

    comp_key = (component or "").strip().lower()
    match_keys = _OIL_COMPONENT_ALIASES.get(comp_key, {comp_key})
    if "componentNameNormalized" in df_classified.columns:
        name_col = "componentNameNormalized"
    elif "componentName" in df_classified.columns:
        name_col = "componentName"
    else:
        return None

    comp_rows = df_classified[df_classified[name_col].astype(str).str.strip().str.lower().isin(match_keys)]
    if comp_rows.empty or "unitId" not in comp_rows.columns:
        return None

    unit_norm = _normalize_unit_id(unit)
    comp_rows = comp_rows[comp_rows["unitId"].apply(_normalize_unit_id) == unit_norm]

    return comp_rows if not comp_rows.empty else None


def load_predictive_oil_limits_four(client: str, component: str) -> dict:
    """
    Resolve the four-limit Stewart dict (LIC/LIM/LSM/LSC, data contract v2.8)
    for one predictive component ('motor', 'transmision', ...), or {} if
    unavailable.

    The predictive module's `component` key-space does not always match
    stewart_limits_four.parquet's `component` field 1:1 - e.g. CDA's Stewart
    component is literally 'motor' (an exact match), but CAPSTONE splits
    engine components into 'motor diesel'/'motor traccion derecho'/'motor
    traccion izquierdo'. _OIL_COMPONENT_ALIASES resolves this the same way it
    already does for real oil samples: 'motor' unambiguously maps to 'motor
    diesel' for Capstone, never to a traction motor. For any component with
    no alias entry, this only resolves limits when `component` matches a
    Stewart Limits component name EXACTLY for that client; otherwise it
    returns {} (no limits shown for that combination) rather than guessing -
    a wrong limit is worse than an absent one, the same principle already
    applied to OIL_THRESHOLDS["capstone"] above. Never falls back to the
    legacy OIL_THRESHOLDS table above.

    Args:
        client: Client key, any case ('cda', 'CDA', 'capstone', ...).
        component: Predictive component key ('motor', 'transmision', ...).

    Returns:
        Nested dict {essay: {oilHourRange: {LIC, LIM, LSM, LSC, ...}}}, or {}.
    """
    from config.settings import get_settings
    from src.data.loaders import load_stewart_limits_four

    settings = get_settings()
    limits_file = settings.get_stewart_limits_four_path(client)
    if not limits_file.exists():
        return {}

    limits = load_stewart_limits_four(limits_file)
    component_limits = limits.get(client.upper(), {}).get(PREDICTIVE_STEWART_MACHINE, {})

    comp_key = (component or "").strip().lower()
    for candidate in _OIL_COMPONENT_ALIASES.get(comp_key, {comp_key}):
        resolved = component_limits.get(candidate, {})
        if resolved:
            return resolved
    return {}


# =============================================================================
# HELPERS  —  todos aceptan `client` (default "cda" para retro-compat).
# El fallback ante un cliente desconocido loguea y cae a "cda", nunca a un
# componente de otro cliente por accidente.
# =============================================================================
