"""
Recipient resolution: who may receive an email, per client and environment.

Matrix (see 01_mailing_service_backend.md):

| Group              | Production                          | Non-production         |
|--------------------|-------------------------------------|------------------------|
| Cliente            | selectable; scheduled: send_email   | never sent, not shown  |
| Coddi · Técnico    | always included, cannot be removed  | same                   |
| Coddi · Gerencia   | scheduled; selectable in manual     | never sent, not shown  |
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable, List, Optional

from . import config

GROUP_LABELS = {
    config.GROUP_CLIENT: "Cliente",
    config.GROUP_TECHNICAL: "Coddi · Técnico",
    config.GROUP_MANAGEMENT: "Coddi · Gerencia",
}

NON_PRODUCTION_REASON = "Solo disponible en producción"
LOCKED_REASON = "Siempre incluido"


@dataclass(frozen=True)
class Recipient:
    name: str
    email: str
    group: str
    send_email: bool
    selected_by_default: bool
    locked: bool = False
    disabled: bool = False
    disabled_reason: Optional[str] = None

    def to_dict(self) -> dict:
        data = asdict(self)
        data["group_label"] = GROUP_LABELS[self.group]
        return data


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def _from_registry(entries: Iterable[dict], group: str, production: bool) -> List[Recipient]:
    result: List[Recipient] = []
    for entry in entries:
        send = bool(entry.get("send_email", False))
        if group == config.GROUP_TECHNICAL:
            # Always included, in every environment, whatever `send_email` says.
            result.append(Recipient(
                name=entry["name"], email=entry["email"], group=group, send_email=True,
                selected_by_default=True, locked=True, disabled=False,
                disabled_reason=LOCKED_REASON,
            ))
        elif production:
            result.append(Recipient(
                name=entry["name"], email=entry["email"], group=group, send_email=send,
                selected_by_default=send,
            ))
        else:
            result.append(Recipient(
                name=entry["name"], email=entry["email"], group=group, send_email=send,
                selected_by_default=False, disabled=True,
                disabled_reason=NON_PRODUCTION_REASON,
            ))
    return result


def list_recipients(client: str, production: Optional[bool] = None) -> List[Recipient]:
    """All contacts for the client, grouped Cliente / Técnico / Gerencia, with their state.

    In non-production the Cliente and Gerencia contacts are listed but disabled and
    unselected (the admin screen shows them greyed out); they are not in `allowed_emails`.
    """
    production = config.is_production() if production is None else production
    client = config.normalize_client(client)
    result: List[Recipient] = []
    result += _from_registry(config.MAILING_RECIPIENTS.get(client, []), config.GROUP_CLIENT, production)
    result += _from_registry(config.CODDI_RECIPIENTS.get("technical", []), config.GROUP_TECHNICAL, production)
    result += _from_registry(config.CODDI_RECIPIENTS.get("management", []), config.GROUP_MANAGEMENT, production)
    return result


def technical_emails(client: str = "", production: Optional[bool] = None) -> List[str]:
    return [r.email for r in list_recipients(client, production) if r.group == config.GROUP_TECHNICAL]


def allowed_emails(client: str, production: Optional[bool] = None) -> List[str]:
    """Emails a manual send may target: everything not disabled, Técnico included."""
    return [r.email for r in list_recipients(client, production) if not r.disabled]


def scheduled_emails(client: str, production: Optional[bool] = None) -> List[str]:
    """Emails of a scheduled send: Técnico always; in production also contacts flagged
    `send_email` (client and management)."""
    if config.SCHEDULED_RECIPIENTS_OVERRIDE is not None:  # temporary test restriction (see config.py)
        return dedupe(config.SCHEDULED_RECIPIENTS_OVERRIDE)
    production = config.is_production() if production is None else production
    emails: List[str] = []
    for r in list_recipients(client, production):
        if r.group == config.GROUP_TECHNICAL or (production and r.send_email):
            emails.append(r.email)
    return dedupe(emails)


def dedupe(emails: Iterable[str]) -> List[str]:
    """Drop repeated addresses (case-insensitive), keeping first spelling and order."""
    seen = set()
    unique: List[str] = []
    for email in emails:
        key = normalize_email(email)
        if key and key not in seen:
            seen.add(key)
            unique.append(email.strip())
    return unique


def resolve_manual_selection(client: str, selected: Iterable[str], production: Optional[bool] = None):
    """Validate a manual selection against the server-side allowed set.

    Returns `(final_emails, rejected)`. `final_emails` always contains Coddi Técnico (added
    when missing). `rejected` lists every submitted email outside the allowed set; the
    caller must refuse the whole send when it is not empty.
    """
    allowed = list_recipients(client, production)
    canonical = {normalize_email(r.email): r.email for r in allowed if not r.disabled}
    rejected: List[str] = []
    picked: List[str] = []
    for raw in selected or []:
        key = normalize_email(str(raw))
        if not key:
            continue
        if key in canonical:
            picked.append(canonical[key])
        else:
            rejected.append(str(raw).strip())
    picked += [r.email for r in allowed if r.group == config.GROUP_TECHNICAL]
    return dedupe(picked), rejected
