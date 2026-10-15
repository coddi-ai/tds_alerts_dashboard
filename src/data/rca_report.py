"""
Reportes > Reporte RCA: contrato entre el formulario del dashboard y el generador.

El generador (captura de datos de la unidad + armado del informe de causa raiz) se
desarrolla en paralelo. El formulario ya arma la solicitud completa con
`build_rca_request`; `submit_rca_request` es el unico punto que hay que reemplazar
para conectarlo. Mientras tanto devuelve `status = "pending_backend"` y la vista
muestra la solicitud tal como la recibiria el generador.

Forma de la solicitud (dict serializable a JSON):

    {
      "client": "CDA",                 # id normalizado del cliente activo
      "unit": "T_10",                  # obligatorio
      "system": "motor" | None,        # valor de src.data.erp_schemas.System; None = todos
      "event_date": "2026-10-14" | None,
      "title": str, "description": str, "findings": str, "actions": str,
      "troubleshooting": None,         # reservado: bloque aun en desarrollo en la vista
      "images": [{"filename", "mime", "size", "caption", "data_base64"}],
      "requested_by": "usuario", "requested_at": "2026-10-15T12:00:00+00:00",
    }
"""

from __future__ import annotations

import base64
import binascii
import uuid
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from src.utils.logger import get_logger

logger = get_logger(__name__)

# Las imagenes viajan en base64 entre navegador y servidor en cada callback: el tope
# mantiene esos viajes livianos hasta que el generador tenga su propio almacenamiento.
RCA_MAX_IMAGES = 6
RCA_MAX_IMAGE_BYTES = 4 * 1024 * 1024
RCA_IMAGE_TYPES = ("image/png", "image/jpeg", "image/webp", "image/gif")

STATUS_PENDING_BACKEND = "pending_backend"

TEXT_FIELDS = ("title", "description", "findings", "actions")


def decode_image(filename: str, contents: str) -> Tuple[Optional[dict], Optional[str]]:
    """(imagen, None) o (None, motivo) para un archivo de dcc.Upload (`data:<mime>;base64,...`).

    Motivos: "type" (no es una imagen admitida), "size" (supera el tope), "invalid".
    """
    header, _, payload = (contents or "").partition(",")
    mime = header.removeprefix("data:").split(";", 1)[0].lower()
    if mime not in RCA_IMAGE_TYPES:
        return None, "type"
    try:
        size = len(base64.b64decode(payload, validate=True))
    except (binascii.Error, ValueError):
        return None, "invalid"
    if size > RCA_MAX_IMAGE_BYTES:
        return None, "size"
    return {
        "id": uuid.uuid4().hex,
        "filename": filename or "imagen",
        "mime": mime,
        "size": size,
        "data": contents,
        "caption": "",
    }, None


def build_rca_request(client: str, unit: str, system: Optional[str], event_date: Optional[str],
                      fields: dict, images: List[dict], requested_by: Optional[str]) -> dict:
    """Solicitud completa para el generador, a partir de lo que el usuario lleno."""
    return {
        "client": client,
        "unit": unit,
        "system": system or None,
        "event_date": event_date or None,
        **{name: (fields.get(name) or "").strip() for name in TEXT_FIELDS},
        "troubleshooting": None,
        "images": [{
            "filename": image["filename"],
            "mime": image["mime"],
            "size": image["size"],
            "caption": (image.get("caption") or "").strip(),
            "data_base64": image["data"].partition(",")[2],
        } for image in images],
        "requested_by": requested_by or None,
        "requested_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def request_summary(request: dict) -> dict:
    """La solicitud sin el contenido de las imagenes, para mostrarla o registrarla."""
    return {
        **request,
        "images": [{k: v for k, v in image.items() if k != "data_base64"} for image in request["images"]],
    }


def submit_rca_request(request: dict) -> dict:
    """Envia la solicitud al generador de reportes RCA.

    PENDIENTE: el generador aun no existe. Cuando este listo, esta funcion debe
    devolver {"status": "ready", "href": <url del PDF>} (o "error" con "message").
    """
    logger.info(f"Reporte RCA solicitado (generador pendiente): {request_summary(request)}")
    return {"status": STATUS_PENDING_BACKEND}
