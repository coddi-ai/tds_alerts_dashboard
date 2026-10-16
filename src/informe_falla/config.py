"""
Configuracion del Informe preliminar de falla, en un solo lugar.

Cada valor tiene su default declarado una vez en `InformeSettings` y se puede cambiar por
variable de entorno (en .env o en docker-compose.yml) sin tocar codigo:

    INFORME_FALLA_MODEL                 modelo de OpenAI que redacta el informe (default gpt-6-luna)
    INFORME_FALLA_LLM_TIMEOUT_SECONDS   tiempo maximo de la llamada a la IA
    INFORME_FALLA_TEMPERATURE           temperatura; vacio = no se envia (el modelo usa la suya)
    INFORME_FALLA_SEED                  semilla para respuestas mas repetibles; vacio = no se envia
    INFORME_FALLA_OUTPUT_DIR            carpeta donde quedan los PDF y sus registros JSON
    INFORME_FALLA_DATA_CACHE_SECONDS    vida del historial del Predictivo ya cargado, por cliente
    INFORME_FALLA_MAX_WORKERS           informes que se generan a la vez
    INFORME_FALLA_JOB_TTL_SECONDS       cuanto se recuerda un trabajo terminado en memoria

Solo aplica al informe preliminar: Campbell AI tiene su propia configuracion (src/campbell_ai/config.py).
Los umbrales del analisis (ventanas, percentiles, niveles) y el catalogo de verificaciones
estan en catalog.py: son parte del metodo, no de la operacion.

El contexto de cada cliente que va en el prompt esta en PERFILES_CLIENTE, abajo.
"""

from __future__ import annotations

import os
from dataclasses import MISSING, dataclass, fields
from datetime import date
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]


# =============================================================================
# Operacion (por variable de entorno)
# =============================================================================
@dataclass(frozen=True)
class InformeSettings:
    model: str = "gpt-6-luna"
    llm_timeout_seconds: float = 180.0
    temperature: Optional[float] = None
    seed: Optional[int] = None
    output_dir: Path = PROJECT_ROOT / "outputs" / "informe_falla"
    data_cache_seconds: int = 900
    max_workers: int = 2
    job_ttl_seconds: int = 6 * 3600

    @classmethod
    def from_env(cls) -> "InformeSettings":
        defaults = {f.name: f.default for f in fields(cls) if f.default is not MISSING}
        return cls(
            model=_env_str("INFORME_FALLA_MODEL") or defaults["model"],
            llm_timeout_seconds=float(_env_str("INFORME_FALLA_LLM_TIMEOUT_SECONDS") or defaults["llm_timeout_seconds"]),
            temperature=_env_opcional("INFORME_FALLA_TEMPERATURE", float),
            seed=_env_opcional("INFORME_FALLA_SEED", int),
            output_dir=Path(_env_str("INFORME_FALLA_OUTPUT_DIR") or defaults["output_dir"]),
            data_cache_seconds=int(_env_str("INFORME_FALLA_DATA_CACHE_SECONDS") or defaults["data_cache_seconds"]),
            max_workers=int(_env_str("INFORME_FALLA_MAX_WORKERS") or defaults["max_workers"]),
            job_ttl_seconds=int(_env_str("INFORME_FALLA_JOB_TTL_SECONDS") or defaults["job_ttl_seconds"]),
        )


def _env_str(name: str) -> Optional[str]:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else None


def _env_opcional(name: str, tipo):
    value = _env_str(name)
    return tipo(value) if value is not None else None


def get_informe_settings() -> InformeSettings:
    """Se lee en cada uso (es barato): un cambio en el entorno aplica sin reiniciar el proceso."""
    return InformeSettings.from_env()


# =============================================================================
# Contexto por cliente (aparece en el prompt)
# =============================================================================
# equipo: descripcion del equipo para la IA. nombre: como se muestra en el informe.
# fecha_inicio_base: inicio de la telemetria; antes, el score solo usaba aceite y no es
# comparable, asi que esas semanas no entran a la linea base. None = sin corte.
PERFIL_GENERICO = {"equipo": "camión minero", "nombre": None, "fecha_inicio_base": None}
PERFILES_CLIENTE = {
    "CAPSTONE": {"equipo": "camión minero con motor Cummins QSK60", "nombre": "Capstone",
                 "fecha_inicio_base": date(2025, 7, 12)},
}


def perfil_cliente(cliente: str) -> dict:
    perfil = {**PERFIL_GENERICO, **PERFILES_CLIENTE.get((cliente or "").upper(), {})}
    perfil["nombre"] = perfil["nombre"] or (cliente or "").title()
    return perfil
