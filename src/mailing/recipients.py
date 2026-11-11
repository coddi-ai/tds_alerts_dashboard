"""
Recipient resolution: who may receive an email, per client.

The registry (config.MAILING_RECIPIENTS + config.CODDI_RECIPIENTS) is the allowed set of a
manual send in EVERY environment (01.1). The environment only changes the default selection.

| Group              | Manual: selectable | Default selection                     | Scheduled          |
|--------------------|--------------------|---------------------------------------|--------------------|
| Cliente            | yes                | production: `send_email`; else none   | `send_email`       |
| Coddi · Técnico    | locked, always in  | always                                | always (all)       |
| Coddi · Gerencia   | yes                | production: `send_email`; else none   | `send_email`       |

Scheduled recipients are identical in every environment. A client listed in
`config.SCHEDULED_TECHNICAL_ONLY_CLIENTS` (Emin, while it is in test) gets only Técnico.
"""

from dataclasses import asdict, dataclass
from typing import Iterable, List, Optional

from . import config

GROUP_LABELS = {
    config.GROUP_CLIENT: "Cliente",
    config.GROUP_TECHNICAL: "Coddi · Técnico",
    config.GROUP_MANAGEMENT: "Coddi · Gerencia",
}

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
            # Always included, in every environment, whatever `send_email` says. The only
            # locked rows, and so the only ones the screen disables.
            result.append(Recipient(
                name=entry["name"], email=entry["email"], group=group, send_email=True,
                selected_by_default=True, locked=True, disabled=True,
                disabled_reason=LOCKED_REASON,
            ))
        else:
            # Selectable in every environment; production pre-selects the `send_email` ones.
            result.append(Recipient(
                name=entry["name"], email=entry["email"], group=group, send_email=send,
                selected_by_default=production and send,
            ))
    return result


def list_recipients(client: str, production: Optional[bool] = None) -> List[Recipient]:
    """Every registry contact for the client, grouped Cliente / Técnico / Gerencia.

    `production` only changes `selected_by_default`; nothing is disabled by the environment.
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
    """Emails a manual send may target: the whole registry of the client, in any environment."""
    return [r.email for r in list_recipients(client, production)]


def scheduled_emails(client: str) -> List[str]:
    """Emails of a scheduled send, identical in every environment: all Técnico plus the
    client and Gerencia contacts flagged `send_email`.

    A client in `config.SCHEDULED_TECHNICAL_ONLY_CLIENTS` (Emin, while it is in test) gets only
    the Técnico contacts.
    """
    technical_only = config.normalize_client(client) in config.SCHEDULED_TECHNICAL_ONLY_CLIENTS
    emails: List[str] = []
    for r in list_recipients(client):
        if r.group == config.GROUP_TECHNICAL or (r.send_email and not technical_only):
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
    """Validate a manual selection against the registry of the client (server-side).

    Returns `(final_emails, rejected)`. `final_emails` always contains Coddi Técnico (added
    when missing). `rejected` lists every submitted email outside the allowed set; the
    caller must refuse the whole send when it is not empty.
    """
    allowed = list_recipients(client, production)
    canonical = {normalize_email(r.email): r.email for r in allowed}
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
