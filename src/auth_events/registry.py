"""Reference registry (TR-1, item 4): `auth_registry/clients.json` and `users.json`.

Both are maintained by hand (edit and upload). The login handler and the dashboard read them
through a small in-memory cache; a failed reload keeps the last good copy.

`auth_registry/pages.json` (TR-6 item 2) is the third file: the page registry that resolves a
page view's `(path, tab)` to a stable `page_id` at write time and to a `display_name` at read time.
It has its own cache, so a missing or broken pages file never affects the client/user registry.
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


def normalize_path(raw: str | None) -> str:
    """URL pathname without query string, fragment or trailing slash; always with a leading slash."""
    path = (raw or "").split("#", 1)[0].split("?", 1)[0].strip()
    path = "/" + path.strip("/")
    return path


def _segments(path: str) -> list[str]:
    return [seg for seg in path.split("/") if seg]


def template_matches(template: str, path: str) -> bool:
    """`/predictive/<component>` matches `/predictive/motor`: `<name>` stands for one segment."""
    want, got = _segments(template), _segments(path)
    if len(want) != len(got):
        return False
    return all((w.startswith("<") and w.endswith(">")) or w == g for w, g in zip(want, got))


@dataclass(frozen=True)
class PagesRegistry:
    pages: tuple[dict, ...] = ()
    loaded_at: float = field(default_factory=time.time)

    def match(self, path: str, tab: str | None) -> dict | None:
        """The entry for `(path, tab)`; an exact path wins over a `<param>` template."""
        path = normalize_path(path)
        templates = []
        for entry in self.pages:
            if entry["tab"] != tab:
                continue
            if entry["path"] == path:
                return entry
            if "<" in entry["path"] and template_matches(entry["path"], path):
                templates.append(entry)
        return templates[0] if templates else None

    def by_id(self, page_id: str | None) -> dict | None:
        return next((p for p in self.pages if p["page_id"] == page_id), None)

    def display_name(self, page_id: str | None, path: str | None = None, tab: str | None = None) -> str:
        """The registry's display name; an unregistered page shows its path (plus ` › <tab>`)."""
        entry = self.by_id(page_id) if page_id and page_id != "unregistered" else None
        if entry is not None:
            return entry["display_name"]
        return unregistered_label(path, tab)


def unregistered_label(path: str | None, tab: str | None) -> str:
    label = normalize_path(path) if path else "—"
    return f"{label} › {tab}" if tab else label


def parse_pages(raw: bytes) -> PagesRegistry:
    items = json.loads(raw.decode("utf-8"))
    if not isinstance(items, list):
        raise ValueError("pages.json must contain a JSON array")
    pages, seen = [], set()
    for item in items:
        if (not isinstance(item, dict) or not item.get("page_id") or not item.get("path")
                or not isinstance(item.get("path"), str)):
            raise ValueError(f"invalid page entry: {item!r}")
        tab = item.get("tab")
        if tab is not None and not isinstance(tab, str):
            raise ValueError(f"invalid page entry (tab must be a string or null): {item!r}")
        path = normalize_path(item["path"])
        if (path, tab) in seen:
            logger.warning("pages.json lists (%s, %s) twice; the first entry wins", path, tab)
            continue
        seen.add((path, tab))
        pages.append({"page_id": item["page_id"], "display_name": item.get("display_name") or item["page_id"],
                      "path": path, "tab": tab})
    return PagesRegistry(pages=tuple(pages), loaded_at=time.time())


def _load_pages() -> PagesRegistry:
    storage = get_storage()
    if storage is None:
        raise RegistryUnavailable("no storage configured")
    return parse_pages(storage.get(settings.REGISTRY_PAGES_KEY))


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
_pages_cache = RegistryCache(loader=_load_pages)


def get_registry_or_none() -> Registry | None:
    return _cache.get()


def get_pages_or_none() -> PagesRegistry | None:
    """The cached page registry; None when it has never loaded (callers then treat every page as unregistered)."""
    return _pages_cache.get()


def reset_registry_cache() -> None:
    _cache.clear()
    _pages_cache.clear()


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
