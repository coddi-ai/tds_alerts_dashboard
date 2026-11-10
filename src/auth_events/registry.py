"""Reference registry (TR-1, item 4): `auth_registry/clients.json` and `users.json`.

Both are maintained by hand (edit and upload). The login handler and the dashboard read them
through a small in-memory cache; a failed reload keeps the last good copy.
"""

import json
import threading
import time
from dataclasses import dataclass, field

from src.auth_events import settings
from src.auth_events.storage import Storage, get_storage
from src.utils.logger import get_logger

logger = get_logger(__name__)

# After a failed reload, wait this long before trying again (capped by the TTL), so an S3
# outage costs one attempt per interval instead of one per login.
RETRY_AFTER_FAILURE_SECONDS = 30.0


class RegistryUnavailable(Exception):
    """The registry was never loaded and cannot be loaded now."""


@dataclass(frozen=True)
class Registry:
    clients: tuple[dict, ...] = ()
    users: tuple[dict, ...] = ()
    loaded_at: float = field(default_factory=time.time)

    def client(self, client_id: str | None) -> dict | None:
        return next((c for c in self.clients if c["client_id"] == client_id), None)

    def active_clients(self) -> list[dict]:
        return [c for c in self.clients if c.get("active", True)]

    def user(self, username: str) -> dict | None:
        exact = next((u for u in self.users if u["username"] == username), None)
        if exact is not None:
            return exact
        lowered = username.casefold()
        return next((u for u in self.users if u["username"].casefold() == lowered), None)

    def users_of_client(self, client_id: str) -> list[dict]:
        return [u for u in self.users if u["user_type"] == "client" and u.get("client_id") == client_id]

    def internal_users(self) -> list[dict]:
        return [u for u in self.users if u["user_type"] == "internal"]


def parse_registry(clients_raw: bytes, users_raw: bytes) -> Registry:
    clients = json.loads(clients_raw.decode("utf-8"))
    users = json.loads(users_raw.decode("utf-8"))
    if not isinstance(clients, list) or not isinstance(users, list):
        raise ValueError("registry files must contain JSON arrays")
    clean_clients = []
    for item in clients:
        if not isinstance(item, dict) or not item.get("client_id"):
            raise ValueError(f"invalid client entry: {item!r}")
        clean_clients.append({
            "client_id": item["client_id"],
            "display_name": item.get("display_name") or item["client_id"],
            "active": bool(item.get("active", True)),
        })
    clean_users = []
    for item in users:
        if not isinstance(item, dict) or not item.get("username") or item.get("user_type") not in ("client", "internal"):
            raise ValueError(f"invalid user entry: {item!r}")
        clean_users.append({
            "username": item["username"],
            "user_type": item["user_type"],
            "client_id": item.get("client_id") if item["user_type"] == "client" else None,
        })
    return Registry(clients=tuple(clean_clients), users=tuple(clean_users), loaded_at=time.time())


def load_registry(storage: Storage) -> Registry:
    return parse_registry(storage.get(settings.REGISTRY_CLIENTS_KEY), storage.get(settings.REGISTRY_USERS_KEY))


class RegistryCache:
    """TTL cache around `load_registry` that never discards a good copy because of a bad reload."""

    def __init__(self, loader=None, ttl=None, clock=time.monotonic):
        self._loader = loader or self._default_loader
        self._ttl = ttl
        self._clock = clock
        self._lock = threading.Lock()
        self._registry: Registry | None = None
        self._next_attempt = 0.0

    @staticmethod
    def _default_loader() -> Registry:
        storage = get_storage()
        if storage is None:
            raise RegistryUnavailable("no storage configured")
        return load_registry(storage)

    def ttl(self) -> float:
        return settings.registry_cache_ttl() if self._ttl is None else self._ttl

    def get(self) -> Registry | None:
        """The cached registry, reloaded when stale; None if it has never loaded."""
        with self._lock:
            now = self._clock()
            if self._registry is not None and now < self._next_attempt:
                return self._registry
            if self._registry is None and now < self._next_attempt:
                return None
            try:
                self._registry = self._loader()
                self._next_attempt = now + self.ttl()
            except Exception as exc:  # noqa: BLE001 - any failure keeps the last good copy
                logger.warning(
                    "Auth registry reload failed (%s: %s); %s",
                    type(exc).__name__, exc,
                    "keeping the last good copy" if self._registry is not None else "no copy available",
                )
                self._next_attempt = now + min(self.ttl(), RETRY_AFTER_FAILURE_SECONDS)
            return self._registry

    def clear(self) -> None:
        with self._lock:
            self._registry = None
            self._next_attempt = 0.0


_cache = RegistryCache()


def get_registry_or_none() -> Registry | None:
    return _cache.get()


def reset_registry_cache() -> None:
    _cache.clear()


def resolve_user(registry: Registry | None, username: str) -> tuple[str, str | None]:
    """(user_type, client_id) for a login. `unmapped` when the user is absent or no registry."""
    if registry is None:
        return "unmapped", None
    entry = registry.user(username)
    if entry is None:
        return "unmapped", None
    if entry["user_type"] == "client":
        return "client", entry.get("client_id")
    return "internal", None
