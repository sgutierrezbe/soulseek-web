"""In-process caches.

`TTLCache` is a bounded, time-expiring dict used for metadata lookups (Deezer
ranks, iTunes charts). Cover images additionally get `CoverCache`, which keeps a
small LRU in memory in front of an on-disk store -- cover bytes never change
once fetched, so the disk copy survives restarts and keeps memory flat no matter
how many albums get browsed.
"""

from __future__ import annotations

import hashlib
import threading
import time
from collections import OrderedDict
from pathlib import Path

from config import CACHE_DIR


class TTLCache:
    """Bounded mapping whose entries expire after `ttl` seconds."""

    def __init__(self, maxsize: int = 512, ttl: float = 3600) -> None:
        self._data: OrderedDict[str, tuple[float, object]] = OrderedDict()
        self._maxsize = maxsize
        self._ttl = ttl
        self._lock = threading.Lock()

    def get(self, key: str, default=None):
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return default
            expires, value = entry
            if expires < time.time():
                del self._data[key]
                return default
            self._data.move_to_end(key)
            return value

    def set(self, key: str, value, ttl: float | None = None) -> None:
        with self._lock:
            self._data[key] = (time.time() + (self._ttl if ttl is None else ttl), value)
            self._data.move_to_end(key)
            while len(self._data) > self._maxsize:
                self._data.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


class CoverCache:
    """Two-tier (memory + disk) cache for cover art."""

    _MIME_EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
    _EXT_MIME = {ext: mime for mime, ext in _MIME_EXT.items()}

    def __init__(
        self,
        directory: Path,
        memory_items: int = 48,
        max_bytes: int = 256 * 1024 * 1024,
    ) -> None:
        self._dir = directory
        self._max_bytes = max_bytes
        self._memory: OrderedDict[str, tuple[bytes, str]] = OrderedDict()
        self._memory_items = memory_items
        # Negative results expire so a cover added to the folder later is found.
        self._missing = TTLCache(maxsize=2048, ttl=1800)
        self._lock = threading.Lock()
        self._writes_since_prune = 0
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass

    @staticmethod
    def digest(key: str) -> str:
        return hashlib.sha1(key.encode("utf-8", "replace")).hexdigest()

    def etag(self, key: str) -> str:
        return f'W/"{self.digest(key)[:16]}"'

    def _paths(self, key: str):
        stem = self._dir / self.digest(key)
        for ext, mime in self._EXT_MIME.items():
            yield stem.with_suffix(ext), mime

    # ── reads ────────────────────────────────────────────────────────────────

    def get(self, key: str) -> tuple[bytes, str] | None:
        with self._lock:
            hit = self._memory.get(key)
            if hit is not None:
                self._memory.move_to_end(key)
                return hit
        for path, mime in self._paths(key):
            try:
                data = path.read_bytes()
            except OSError:
                continue
            if data:
                self._remember(key, data, mime)
                return data, mime
        return None

    def is_missing(self, key: str) -> bool:
        return self._missing.get(key) is not None

    # ── writes ───────────────────────────────────────────────────────────────

    def _remember(self, key: str, data: bytes, mime: str) -> None:
        with self._lock:
            self._memory[key] = (data, mime)
            self._memory.move_to_end(key)
            while len(self._memory) > self._memory_items:
                self._memory.popitem(last=False)

    def set(self, key: str, data: bytes, mime: str = "image/jpeg") -> None:
        if not data:
            self.mark_missing(key)
            return
        mime = mime if mime in self._MIME_EXT else "image/jpeg"
        self._remember(key, data, mime)
        path = (self._dir / self.digest(key)).with_suffix(self._MIME_EXT[mime])
        try:
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_bytes(data)
            tmp.replace(path)
        except OSError:
            return
        with self._lock:
            self._writes_since_prune += 1
            due = self._writes_since_prune >= 200
            if due:
                self._writes_since_prune = 0
        if due:
            self.prune()

    def mark_missing(self, key: str) -> None:
        self._missing.set(key, True)

    def forget(self, key: str) -> None:
        """Drop a cached cover so the next request re-reads it from disk."""
        with self._lock:
            self._memory.pop(key, None)
        self._missing.set(key, None, ttl=0)
        for path, _ in self._paths(key):
            try:
                path.unlink()
            except OSError:
                pass

    # ── housekeeping ─────────────────────────────────────────────────────────

    def prune(self) -> None:
        """Evict least-recently-used files once the store exceeds its budget."""
        try:
            entries = [
                (p.stat().st_atime, p.stat().st_size, p)
                for p in self._dir.iterdir()
                if p.is_file() and p.suffix in self._EXT_MIME
            ]
        except OSError:
            return
        total = sum(size for _, size, _ in entries)
        if total <= self._max_bytes:
            return
        for _, size, path in sorted(entries):
            try:
                path.unlink()
            except OSError:
                continue
            total -= size
            if total <= self._max_bytes * 0.8:
                break


covers = CoverCache(CACHE_DIR / "covers")
metadata = TTLCache(maxsize=1024, ttl=6 * 3600)
