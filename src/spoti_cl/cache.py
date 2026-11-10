"""A tiny JSON backed cache with TTL support.

The cache lives under ``~/.cache/spoti-cl`` (or ``%LOCALAPPDATA%`` on Windows)
and keeps three things:

* the anonymous session token,
* the persisted GraphQL query hashes,
* resolved track metadata and YouTube matches.

Everything is written atomically so a crash can never leave a half written
file behind.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

DEFAULT_TTL = 7 * 24 * 3600


def cache_root() -> Path:
    """Return the directory used for cached data."""
    override = os.environ.get("SPOTICL_CACHE_DIR")
    if override:
        return Path(override)
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "spoti-cl" / "cache"
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "spoti-cl"


class Cache:
    """A namespaced JSON cache with per namespace TTLs."""

    def __init__(self, root: Path | None = None, ttl: float = DEFAULT_TTL) -> None:
        self.root = Path(root) if root else cache_root()
        self.ttl = ttl
        self._lock = threading.RLock()
        self._memory: dict[str, tuple[float, Any]] = {}
        self.root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ paths
    def _path(self, namespace: str) -> Path:
        safe = namespace.replace("/", "_").replace("\\", "_")
        return self.root / f"{safe}.json"

    # ------------------------------------------------------------------- read
    def get(self, namespace: str, default: Any = None, ttl: float | None = None) -> Any:
        """Return the cached value for ``namespace`` or ``default`` when stale."""
        with self._lock:
            max_age = self.ttl if ttl is None else ttl
            stamp, value = self._memory.get(namespace, (0.0, None))
            if value is not None and self._fresh(stamp, max_age):
                return value

            path = self._path(namespace)
            if not path.exists():
                self._memory.pop(namespace, None)
                return default
            try:
                payload = json.loads(path.read_text("utf-8"))
            except (OSError, ValueError):
                return default
            if not isinstance(payload, dict) or "value" not in payload:
                return default
            stamp = float(payload.get("stored_at", 0.0))
            if not self._fresh(stamp, max_age):
                return default
            self._memory[namespace] = (stamp, payload["value"])
            return payload["value"]

    @staticmethod
    def _fresh(stamp: float, max_age: float) -> bool:
        """True when an entry is still within its time to live."""
        if max_age < 0:
            return True
        return (time.time() - stamp) <= max_age

    # ------------------------------------------------------------------ write
    def set(self, namespace: str, value: Any, ttl: float | None = None) -> None:
        """Store ``value`` under ``namespace``."""
        with self._lock:
            stamp = time.time()
            self._memory[namespace] = (stamp, value)
            path = self._path(namespace)
            payload = {"stored_at": stamp, "value": value}
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                handle, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
                with os.fdopen(handle, "w", encoding="utf-8") as fh:
                    json.dump(payload, fh, ensure_ascii=False)
                os.replace(tmp_name, path)
            except OSError:
                # A cache miss is never fatal.
                pass

    def delete(self, namespace: str) -> None:
        with self._lock:
            self._memory.pop(namespace, None)
            path = self._path(namespace)
            try:
                path.unlink()
            except OSError:
                pass

    def clear(self) -> None:
        """Drop every cached entry."""
        with self._lock:
            self._memory.clear()
            for path in self.root.glob("*.json"):
                try:
                    path.unlink()
                except OSError:
                    pass
