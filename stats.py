"""Durable upload statistics.

slskd's `/transfers/uploads` is a view of its *current* transfer list: clearing
completed uploads, or slskd's own retention, wipes the history. So lifetime
totals cannot simply be read from it. Instead a background task samples that
list and folds newly-finished uploads into an aggregate persisted alongside the
rest of our config.

Counting is exact rather than approximate. Each poll:

    current  = ids slskd currently reports as succeeded
    new      = current - already_counted
    counted  = current            <- pruned to what slskd still reports

An id is counted the first time it appears and is then forgotten once slskd
drops it from the list. Transfer ids are GUIDs and never reappear, so nothing is
double counted and the bookkeeping set stays bounded by slskd's list length.
"""

from __future__ import annotations

import json
import threading
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config import CONFIG_DIR

STATS_FILE = CONFIG_DIR / "upload_stats.json"

# Caps so the file cannot grow without bound on a heavily shared library.
MAX_TRACKED_FILES = 3000
MAX_TRACKED_ALBUMS = 1500
MAX_TRACKED_USERS = 2000
DAILY_HISTORY_DAYS = 365


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.replace(microsecond=0).isoformat()


def _split_path(filename: str) -> tuple[str, str]:
    """Return (album folder, bare filename) from a Soulseek-style path."""
    normalized = str(filename).replace("\\", "/").rstrip("/")
    parts = [p for p in normalized.split("/") if p]
    if not parts:
        return "", str(filename)
    name = parts[-1]
    folder = parts[-2] if len(parts) >= 2 else ""
    return folder, name


def _is_succeeded(state: str) -> bool:
    # slskd serialises flags as e.g. "Completed, Succeeded" / "Completed, Errored".
    return "Succeeded" in (state or "")


class UploadStats:
    """Aggregate of everything other users have taken from this library."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._dirty = False
        self._counted: set[str] = set()
        self._data = self._empty()
        self.load()

    @staticmethod
    def _empty() -> dict:
        return {
            "version": 1,
            "since": None,
            "total_files": 0,
            "total_bytes": 0,
            "last_upload_at": None,
            "files": {},    # "folder/name" -> {folder, name, count, bytes, last}
            "albums": {},   # folder      -> {count, bytes, last}
            "users": {},    # username    -> {count, bytes, last, first}
            "daily": {},    # "YYYY-MM-DD"-> {files, bytes}
        }

    # ── persistence ──────────────────────────────────────────────────────────

    def load(self) -> None:
        with self._lock:
            try:
                raw = json.loads(STATS_FILE.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return
            if isinstance(raw, dict) and raw.get("version") == 1:
                merged = self._empty()
                merged.update(raw)
                self._data = merged

    def save(self, force: bool = False) -> None:
        with self._lock:
            if not (self._dirty or force):
                return
            payload = json.dumps(self._data, separators=(",", ":"))
            self._dirty = False
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            tmp = STATS_FILE.with_suffix(".json.tmp")
            tmp.write_text(payload, encoding="utf-8")
            tmp.replace(STATS_FILE)
        except OSError:
            # Losing a sample is better than crashing the poller.
            pass

    def reset(self) -> None:
        with self._lock:
            self._data = self._empty()
            self._counted.clear()
            self._dirty = True
        self.save(force=True)

    # ── ingestion ────────────────────────────────────────────────────────────

    def record(self, transfers: list[dict]) -> int:
        """Fold a poll of slskd uploads into the aggregate. Returns new count."""
        succeeded = {
            str(t.get("id")): t
            for t in transfers
            if t.get("id") and _is_succeeded(t.get("state", ""))
        }

        with self._lock:
            new_ids = succeeded.keys() - self._counted
            for transfer_id in new_ids:
                self._add(succeeded[transfer_id])
            # Prune to what slskd still reports, so this set stays small.
            self._counted = set(succeeded.keys())
            if new_ids:
                self._dirty = True
                self._trim()
            return len(new_ids)

    def _add(self, transfer: dict) -> None:
        data = self._data
        # Prefer the transferred count: a partial upload still cost us bytes.
        size = int(transfer.get("bytesTransferred") or transfer.get("size") or 0)
        username = str(transfer.get("username") or "unknown")
        folder, name = _split_path(transfer.get("filename", ""))
        key = f"{folder}/{name}" if folder else name

        ended = transfer.get("endedAt") or transfer.get("requestedAt")
        try:
            moment = datetime.fromisoformat(str(ended).replace("Z", "+00:00"))
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            moment = _now()
        stamp = _iso(moment)

        data["total_files"] += 1
        data["total_bytes"] += size
        data["since"] = data["since"] or stamp
        if not data["last_upload_at"] or stamp > data["last_upload_at"]:
            data["last_upload_at"] = stamp

        entry = data["files"].setdefault(key, {"folder": folder, "name": name, "count": 0, "bytes": 0, "last": stamp})
        entry["count"] += 1
        entry["bytes"] += size
        entry["last"] = max(entry["last"], stamp)

        if folder:
            album = data["albums"].setdefault(folder, {"count": 0, "bytes": 0, "last": stamp})
            album["count"] += 1
            album["bytes"] += size
            album["last"] = max(album["last"], stamp)

        user = data["users"].setdefault(username, {"count": 0, "bytes": 0, "first": stamp, "last": stamp})
        user["count"] += 1
        user["bytes"] += size
        user["last"] = max(user["last"], stamp)
        user["first"] = min(user["first"], stamp)

        day = data["daily"].setdefault(stamp[:10], {"files": 0, "bytes": 0})
        day["files"] += 1
        day["bytes"] += size

    def _trim(self) -> None:
        """Drop the least active entries once a bucket exceeds its cap."""
        data = self._data

        def cap(bucket: str, limit: int) -> None:
            items = data[bucket]
            if len(items) <= limit:
                return
            # Keep the most-uploaded, breaking ties toward recent activity.
            ranked = sorted(items.items(), key=lambda kv: (kv[1]["count"], kv[1]["last"]), reverse=True)
            data[bucket] = dict(ranked[:limit])

        cap("files", MAX_TRACKED_FILES)
        cap("albums", MAX_TRACKED_ALBUMS)
        cap("users", MAX_TRACKED_USERS)

        cutoff = (_now() - timedelta(days=DAILY_HISTORY_DAYS)).date().isoformat()
        data["daily"] = {d: v for d, v in data["daily"].items() if d >= cutoff}

    # ── reads ────────────────────────────────────────────────────────────────

    def summary(self, top: int = 10, days: int = 30) -> dict:
        with self._lock:
            data = json.loads(json.dumps(self._data))  # cheap deep copy

        today = _now().date()
        daily_map = data["daily"]

        # A dense series (zero-filled) so the chart has no gaps.
        timeline = []
        for offset in range(days - 1, -1, -1):
            day = (today - timedelta(days=offset)).isoformat()
            entry = daily_map.get(day, {"files": 0, "bytes": 0})
            timeline.append({"date": day, "files": entry["files"], "bytes": entry["bytes"]})

        def window(count: int) -> dict:
            start = (today - timedelta(days=count - 1)).isoformat()
            selected = [v for d, v in daily_map.items() if d >= start]
            return {
                "files": sum(v["files"] for v in selected),
                "bytes": sum(v["bytes"] for v in selected),
            }

        def rank(bucket: dict, builder) -> list[dict]:
            # Rank by upload count, not bytes: "how many times" is the question
            # these lists answer, and it keeps the leading figure and the bar
            # length encoding the same measure. Bytes break ties.
            ranked = sorted(
                bucket.items(), key=lambda kv: (kv[1]["count"], kv[1]["bytes"]), reverse=True
            )
            return [builder(k, v) for k, v in ranked[:top]]

        return {
            "totals": {
                "files": data["total_files"],
                "bytes": data["total_bytes"],
                "users": len(data["users"]),
                "albums": len(data["albums"]),
                "since": data["since"],
                "last_upload_at": data["last_upload_at"],
            },
            "today": daily_map.get(today.isoformat(), {"files": 0, "bytes": 0}),
            "week": window(7),
            "month": window(30),
            "timeline": timeline,
            "top_files": rank(
                data["files"],
                lambda k, v: {"name": v["name"], "folder": v["folder"], "count": v["count"], "bytes": v["bytes"], "last": v["last"]},
            ),
            "top_albums": rank(
                data["albums"],
                lambda k, v: {"folder": k, "count": v["count"], "bytes": v["bytes"], "last": v["last"]},
            ),
            "top_users": rank(
                data["users"],
                lambda k, v: {"username": k, "count": v["count"], "bytes": v["bytes"], "last": v["last"], "first": v["first"]},
            ),
        }


stats = UploadStats()
