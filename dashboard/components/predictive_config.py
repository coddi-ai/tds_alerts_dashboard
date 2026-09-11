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


def load_predictive_oil_limits_four(client: str, component: str) -> dict:
    """
    Resolve the four-limit Stewart dict (LIC/LIM/LSM/LSC, data contract v2.8)
    for one predictive component ('motor', 'transmision', ...), or {} if
    unavailable.

    The predictive module's `component` key-space does not always match
    stewart_limits_four.parquet's `component` field 1:1 - e.g. CDA's Stewart
    component is literally 'motor' (an exact match), but CAPSTONE splits
    engine components into 'motor diesel'/'motor traccion derecho'/'motor
    traccion izquierdo' (no unambiguous match to predictive's generic
    'motor'). Rather than guess which Capstone sub-component to use - a wrong
    limit is worse than an absent one, the same principle already applied to
    OIL_THRESHOLDS["capstone"] above - this only resolves limits when
    `component` matches a Stewart Limits component name EXACTLY for that
    client; otherwise it returns {} (no limits shown for that combination),
    never falling back to the legacy OIL_THRESHOLDS table above.

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
    return limits.get(client.upper(), {}).get(PREDICTIVE_STEWART_MACHINE, {}).get(component, {})


# =============================================================================
# HELPERS  —  todos aceptan `client` (default "cda" para retro-compat).
# El fallback ante un cliente desconocido loguea y cae a "cda", nunca a un
# componente de otro cliente por accidente.
# =============================================================================
