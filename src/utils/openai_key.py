"""Resolve the OpenAI API key from the environment or AWS Secrets Manager.

Two environment variables are supported, with a fixed precedence:

* ``OPENAI_API_KEY_ARN`` — the ARN (or name) of an AWS Secrets Manager secret whose
  plain-text value is the key. When it is set the secret is fetched with boto3, which
  on ECS resolves credentials from the task's IAM role automatically, so the service
  only needs ``secretsmanager:GetSecretValue`` on that secret. **Takes precedence:** if
  both variables are set, the ARN wins and ``OPENAI_API_KEY`` is ignored.
* ``OPENAI_API_KEY`` — the plain key in the environment (or ``.env``). Used only when
  ``OPENAI_API_KEY_ARN`` is not set.

Having either one defined means "an OpenAI connection is configured". Callers that only
need to know whether a key is available (without paying for a Secrets Manager call)
should use :func:`openai_key_configured`; callers that need the key itself should use
:func:`resolve_openai_api_key`.
"""

from __future__ import annotations

import os
from functools import lru_cache

from src.utils.logger import get_logger

logger = get_logger(__name__)

ENV_KEY = "OPENAI_API_KEY"
ENV_KEY_ARN = "OPENAI_API_KEY_ARN"


def _aws_region() -> str:
    return (
        os.getenv(saWS_REGION")
        or os.getenv("AWS_DEFAULT_REGION")
        or "sa-east-1"
    ).strip() or "sa-east-1"


@lru_cache(maxsize=8)
def _fetch_secret(secret_id: str, region: str) -> str:
    """Plain-text value of a Secrets Manager secret. Cached per (secret, region).

    Cached because the key does not change within a process and every OpenAI call would
    otherwise pay a Secrets Manager round trip. On ECS boto3 picks up the task role's
    credentials from the container credential provider, so no keys are passed here.
    """
    import boto3

    client = boto3.client("secretsmanager", region_name=region)
    response = client.get_secret_value(SecretId=secret_id)
    secret = response.get("SecretString")
    if secret is None:
        raise RuntimeError(f"{ENV_KEY_ARN} secret {secret_id} has no plain-text value")
    return secret.strip()


def openai_key_configured() -> bool:
    """True when either variable is set, without fetching the secret.

    Lets callers decide "is AI available?" cheaply; the actual key (and any Secrets
    Manager call) is deferred to :func:`resolve_openai_api_key`.
    """
    return bool(os.getenv(ENV_KEY_ARN, "").strip() or os.getenv(ENV_KEY, "").strip())


def resolve_openai_api_key() -> str | None:
    """The OpenAI API key, or ``None`` when neither variable is configured.

    ``OPENAI_API_KEY_ARN`` takes precedence over ``OPENAI_API_KEY``. Raises on a
    misconfigured ARN (missing secret, no access) rather than silently falling back, so
    the failure is visible instead of surfacing later as an opaque OpenAI auth error.
    """
    arn = os.getenv(ENV_KEY_ARN, "").strip()
    if arn:
        return _fetch_secret(arn, _aws_region())
    return os.getenv(ENV_KEY, "").strip() or None
