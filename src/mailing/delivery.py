"""
Generic delivery through the email Lambda. Knows nothing about alerts or reports.

Contract (the same one the other Coddi emails use): the Lambda receives the HTTP body
`json.dumps({"fieldName": "CDA-alert", "variables": {"sendCDAAlertEmailInput":
{"mailTo": [...], "mailSubject": ..., "mailText": <html>}}})` and answers 200 on success.
(When invoked with boto3 the same string travels as `{"body": <that string>}`; through the
Function URL the HTTP body *is* that string.)

All recipients go in one message, in `mailTo`, so everyone can see who else received it.

Authentication: the Function URL uses AWS_IAM auth (an unsigned request gets HTTP 403
AccessDeniedException), so every request is signed with SigV4 (service `lambda`, region taken
from the URL host). Credentials: `LAMBDA_ACCESS_KEY` / `LAMBDA_SECRET_ACCESS_KEY` from the
environment (a dedicated identity: the S3 keys the app also has are deliberately not used),
else the default AWS chain (e.g. the EC2 instance role). The signing identity needs
`lambda:InvokeFunctionUrl` and `lambda:InvokeFunction` on the function. With no credentials at
all the request goes out unsigned, which only works for a public (auth NONE) URL.

Security: the Lambda URL is a secret. It is read from the environment per call and never
logged or placed in an error; `requests` exceptions embed the URL in their text, so they
are reduced to a short generic reason here and never propagate.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Dict, Optional, Sequence

import requests

from src.utils.logger import get_logger

from . import config

logger = get_logger(__name__)

# At DEBUG these libraries print the request host (botocore.auth: the canonical request;
# urllib3: "Starting new HTTPS connection"), and the host of a Function URL is the secret.
for _noisy in ("botocore.auth", "urllib3.connectionpool"):
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


_REGION_IN_URL = re.compile(r"\.lambda-url\.([a-z0-9-]+)\.on\.aws", re.IGNORECASE)


def _credentials():
    access, secret = config.get_env("LAMBDA_ACCESS_KEY"), config.get_env("LAMBDA_SECRET_ACCESS_KEY")
    if access and secret:
        from botocore.credentials import Credentials

        return Credentials(access, secret)
    import botocore.session

    return botocore.session.get_session().get_credentials()


def _signed_headers(url: str, body: str) -> Dict[str, str]:
    """Content-Type plus the SigV4 headers, or just Content-Type when nothing can sign."""
    headers = {"Content-Type": "application/json"}
    match = _REGION_IN_URL.search(url)
    try:
        credentials = _credentials()
    except Exception:  # noqa: BLE001 - never let a credentials problem leak into the logs
        credentials = None
    if credentials is None or match is None:
        return headers
    from botocore.auth import SigV4Auth
    from botocore.awsrequest import AWSRequest

    request = AWSRequest(method="POST", url=url, data=body, headers=dict(headers))
    SigV4Auth(credentials.get_frozen_credentials(), "lambda", match.group(1)).add_auth(request)
    return {key: str(value) for key, value in request.headers.items()}


def _lambda_confirms_success(response: requests.Response) -> bool:
    if response.status_code != 200:
        return False
    if response.headers.get("X-Amz-Function-Error"):
        return False
    try:
        body = response.json()
    except ValueError:
        return True  # 200 from the Function URL with a non-JSON body: handler returned fine
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
    url = config.get_lambda_url()
    if not url:
        logger.error("mailing: LAMBDA_URL is not configured")
        return DeliveryResult(False, "El servicio de correo no está configurado.")
    if not recipients:
        return DeliveryResult(False, "No hay destinatarios.")

    body = build_payload(subject, html, recipients)
    try:
        response = requests.post(
            url,
            data=body,
            headers=_signed_headers(url, body),
            timeout=config.DEFAULT_LAMBDA_TIMEOUT,
        )
    except requests.Timeout:
        logger.warning("mailing: Lambda request timed out")
        return DeliveryResult(False, "El servicio de correo no respondió a tiempo.")
    except requests.RequestException as exc:
        # type(exc).__name__ only: str(exc) would carry the URL.
        logger.warning("mailing: Lambda request failed (%s)", type(exc).__name__)
        return DeliveryResult(False, GENERIC_FAILURE)

    if _lambda_confirms_success(response):
        return DeliveryResult(True)
    logger.warning("mailing: Lambda did not confirm success (HTTP %s)", response.status_code)
    return DeliveryResult(False, "El servicio de correo rechazó el envío.")
