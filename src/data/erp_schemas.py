"""Pydantic schema for Conexión ERP warnings (data_contract.md §1).

Ported from the ERP Connection team's `agent/envelope.py` handoff
(migration_dashboard/reference/envelope.py). The pipeline-only
`SignalEnvelope` model is intentionally omitted — the dashboard only ever
reads/writes already-formed `Warning` records.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

from src.i18n import LazyLabels


class Source(str, Enum):
    alertas = "alertas"
    telemetria = "telemetria"
    aceites = "aceites"
    predictivo = "predictivo"
    # El pipeline ERP emite este valor en inglés para los hallazgos de pautas
    # de inspección (data/warnings/centinela/*.parquet); se conserva tal cual
    # viene en el archivo y sólo la etiqueta se muestra en español.
    inspections = "inspections"


SOURCE_LABELS = LazyLabels({
    Source.alertas: "erp.source.alertas",
    Source.telemetria: "erp.source.telemetria",
    Source.aceites: "erp.source.aceites",
    Source.predictivo: "erp.source.predictivo",
    Source.inspections: "erp.source.inspections",
})


class System(str, Enum):
    motor = "motor"
    transmision = "transmision"
    diferencial = "diferencial"
    hidraulico = "hidraulico"
    convertidor = "convertidor"
    direccion = "direccion"
    mando_final = "mando_final"
    rueda = "rueda"
    frenos = "frenos"
    lubricacion = "lubricacion"


SYSTEM_LABELS = LazyLabels({
    System.motor: "erp.system.motor",
    System.transmision: "erp.system.transmision",
    System.diferencial: "erp.system.diferencial",
    System.hidraulico: "erp.system.hidraulico",
    System.convertidor: "erp.system.convertidor",
    System.direccion: "erp.system.direccion",
    System.mando_final: "erp.system.mando_final",
    System.rueda: "erp.system.rueda",
    System.frenos: "erp.system.frenos",
    System.lubricacion: "erp.system.lubricacion",
})


class ConditionLabel(str, Enum):
    normal = "normal"
    alerta = "alerta"
    anormal = "anormal"


CONDITION_LABEL_LABELS = LazyLabels({
    ConditionLabel.normal: "erp.condition.normal",
    ConditionLabel.alerta: "erp.condition.alerta",
    ConditionLabel.anormal: "erp.condition.anormal",
})


class Severity(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


SEVERITY_LABELS = LazyLabels({
    Severity.low: "erp.severity.low",
    Severity.medium: "erp.severity.medium",
    Severity.high: "erp.severity.high",
    Severity.critical: "erp.severity.critical",
})


class WarningStatus(str, Enum):
    pending = "pending"
    validated = "validated"
    rejected = "rejected"
    sent = "sent"


STATUS_LABELS = LazyLabels({
    WarningStatus.pending: "erp.status.pending",
    WarningStatus.validated: "erp.status.validated",
    WarningStatus.rejected: "erp.status.rejected",
    WarningStatus.sent: "erp.status.sent",
})


class ErpType(str, Enum):
    sap = "sap"
    ellipse = "ellipse"
    maximo = "maximo"
    stub = "stub"


class Warning(BaseModel):
    model_config = {"validate_assignment": True}

    warning_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    client_id: str
    asset_id: str
    source: Source
    system: System
    condition_label: Literal[ConditionLabel.alerta, ConditionLabel.anormal]
    severity: Severity
    title: str
    description: str
    recommended_action: str
    supporting_data: dict[str, Any] = Field(default_factory=dict)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: WarningStatus = WarningStatus.pending
    validated_by: str | None = None
    validated_at: datetime | None = None
    operator_notes: str | None = None
    sent_at: datetime | None = None
    erp_type: ErpType
    erp_reference: str | None = None
