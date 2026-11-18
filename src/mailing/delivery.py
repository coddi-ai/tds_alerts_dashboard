"""
Generic delivery through the email Lambda. Knows nothing about alerts or reports.

Contract (the same one the other Coddi emails use): the Lambda receives the event
`{"body": json.dumps({"fieldName": "CDA-alert", "variables": {"sendCDAAlertEmailInput":
{"mailTo": [...], "mailSubject": ..., "mailText": <html>}}})}` and answers `statusCode` 200 on
success.

Transport: AWS SDK `lambda:Invoke` (synchronous, RequestResponse) on the function in
`LAMBDA_FUNCTION_NAME` (its ARN). The caller runs in another account and region (sa-east-1)
than the function (us-east-1), so the client is created in the region taken from the ARN, not
the caller's default region. Credentials come from the default AWS chain (the execution role
of the caller). That role needs `lambda:InvokeFunction` on the ARN, and the function's
resource-based policy must allow the caller's role (cross-account).

Never retried at the SDK level: an invoke that timed out may still have sent the email, and a
retry would send it twice. Retries are the service layer's decision.

Security: the function ARN is read from the environment per call and never logged or placed
in an error. SDK exceptions can embed it, so they are reduced to a short generic reason here
and never propagate.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional, Sequence

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from src.utils.logger import get_logger

from . import config

logger = get_logger(__name__)

# At DEBUG these libraries print request details (botocore: parameters incl. FunctionName;
# urllib3: "Starting new HTTPS connection"); keep the function ARN out of the logs.
for _noisy in ("botocore", "urllib3.connectionpool"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

LAMBDA_FIELD_NAME = "CDA-alert"
GENERIC_FAILURE = "No se pudo contactar el servicio de correo."


@dataclass(frozen=True)
class DeliveryResult:
    ok: bool
    reason: Optional[str] = None  # short, safe-to-show reason when not ok


def build_payload(subject: str, html: str, recipients: Sequence[str]) -> str:
    inner = {
        "fieldName": LAMBDA_FIELD_NAME,
        "variables": {
            "sendCDAAlertEmailInput": {
                "mailTo": list(recipients),
                "mailSubject": subject,
                "mailText": html,
            }
        },
    }
    return json.dumps(inner)


def _region_from_arn(function_arn: str) -> Optional[str]:
    """`arn:aws:lambda:us-east-1:123456789012:function:name` -> `us-east-1`."""
    parts = function_arn.split(":")
    if len(parts) >= 6 and parts[0] == "arn" and parts[2] == "lambda" and parts[3]:
        return parts[3]
    return None


@lru_cache(maxsize=4)
def _client(region: Optional[str]):
    return boto3.client(
        "lambda",
        region_name=region,
        config=Config(
            connect_timeout=config.DEFAULT_LAMBDA_TIMEOUT[0],
            read_timeout=config.DEFAULT_LAMBDA_TIMEOUT[1],
            retries={"total_max_attempts": 1},  # a single attempt: no automatic re-invoke (duplicate emails)
        ),
    )


def _lambda_confirms_success(response: dict) -> bool:
    if response.get("StatusCode") != 200 or response.get("FunctionError"):
        return False
    stream = response.get("Payload")
    raw = stream.read() if stream is not None else b""
    if not raw:
        return True
    try:
        body = json.loads(raw)
    except ValueError:
        return True  # non-JSON payload: handler returned fine
    if isinstance(body, dict):
        if "errorMessage" in body or "errorType" in body or body.get("errors"):
            return False
        status = body.get("statusCode", 200)
        try:
            return int(status) == 200
        except (TypeError, ValueError):
            return False
    return True


def send_email(subject: str, html: str, recipients: Sequence[str]) -> DeliveryResult:
    """Send one message to all `recipients` through the Lambda. Never raises."""
    function = config.get_lambda_function_name()
    if not function:
        logger.error("mailing: LAMBDA_FUNCTION_NAME is not configured")
        return DeliveryResult(False, "El servicio de correo no está configurado.")
    if not recipients:
        return DeliveryResult(False, "No hay destinatarios.")

    event = {"body": build_payload(subject, html, recipients)}
    try:
        response = _client(_region_from_arn(function)).invoke(
            FunctionName=function,
            InvocationType="RequestResponse",
            Payload=json.dumps(event).encode("utf-8"),
        )
        confirmed = _lambda_confirms_success(response)
    except ClientError as exc:
        # Error code only (e.g. AccessDeniedException): str(exc) would carry the ARN.
        code = exc.response.get("Error", {}).get("Code", "unknown")
        logger.warning("mailing: Lambda invoke failed (%s)", code)
        return DeliveryResult(False, GENERIC_FAILURE)
    except BotoCoreError as exc:
        name = type(exc).__name__  # e.g. ReadTimeoutError, EndpointConnectionError, NoCredentialsError
        logger.warning("mailing: Lambda invoke failed (%s)", name)
        if "Timeout" in name:
            return DeliveryResult(False, "El servicio de correo no respondió a tiempo.")
        return DeliveryResult(False, GENERIC_FAILURE)

    if confirmed:
        return DeliveryResult(True)
    logger.warning("mailing: Lambda did not confirm success (HTTP %s)", response.get("StatusCode"))
    return DeliveryResult(False, "El servicio de correo rechazó el envío.")
