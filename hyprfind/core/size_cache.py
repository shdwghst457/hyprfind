"""Persistent, self-validating folder-size cache.

Recursive folder sizes are expensive to compute (especially over SMB), yet most
folders never change again once written. This cache remembers each folder's
computed size on disk, keyed by absolute path, together with the folder's own
modification time at the moment of computation. On a later visit we re-stat the
folder — a single, cheap syscall — and reuse the stored size when the mtime is
unchanged, skipping the recursive walk entirely.

Validation caveat (intentional trade-off): a directory's mtime changes when an
entry is added, removed, or renamed inside it, which covers the overwhelming
majority of size changes. It does *not* change when a file deep in the subtree
merely grows in place. Catching that cheaply is impossible without re-walking
the whole tree, which would defeat the cache. A manual refresh (F5) always
invalidates and recomputes, so the rare in-place-growth case stays correctable.

The store is deliberately Qt-free so it can be unit-tested in isolation; the
owning calculator drives debounced saving.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

# Soft ceiling so the on-disk file can't grow without bound. When exceeded we
# keep the most recently computed entries and drop the stalest ones.
MAX_ENTRIES = 50_000

# Bump when the meaning of stored values changes so stale files are discarded.
# v2: only fully-completed walks are persisted (v1 could store error/partial 0s).
CACHE_VERSION = 2


def _dir_mtime_ns(path: str) -> int | None:
    try:
        return os.stat(path).st_mtime_ns
    except OSError:
        return None


class PersistentSizeCache:
    def __init__(self, path: Path) -> None:
        self._path = path
        # abspath -> {"size": int, "mtime_ns": int, "at": float}
        self._data: dict[str, dict] = {}
        self._dirty = False

    def load(self) -> None:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._data = {}
            return
        if not isinstance(raw, dict) or raw.get("version") != CACHE_VERSION:
            # Different (or missing) schema version: discard and start fresh.
            self._data = {}
            self._dirty = bool(raw)
            return
        entries = raw.get("entries")
        if not isinstance(entries, dict):
            self._data = {}
            return
        clean: dict[str, dict] = {}
        for key, value in entries.items():
            if (
                isinstance(value, dict)
                and isinstance(value.get("size"), int)
                and isinstance(value.get("mtime_ns"), int)
            ):
                clean[key] = {
                    "size": value["size"],
                    "mtime_ns": value["mtime_ns"],
                    "at": float(value.get("at", 0.0)),
                }
        self._data = clean
        self._dirty = False

    def get_valid(self, abs_path: str) -> int | None:
        """Return the cached size if still valid; prune the entry otherwise."""
        entry = self._data.get(abs_path)
        if entry is None:
            return None
        current = _dir_mtime_ns(abs_path)
        if current is None:
            # Folder vanished or became unreadable — drop the stale record.
            self._data.pop(abs_path, None)
            self._dirty = True
            return None
        if current != entry["mtime_ns"]:
            return None
        return entry["size"]

    def put(self, abs_path: str, size: int) -> None:
        mtime_ns = _dir_mtime_ns(abs_path)
        if mtime_ns is None:
            return
        self._data[abs_path] = {
            "size": size,
            "mtime_ns": mtime_ns,
            "at": time.time(),
        }
        self._dirty = True

    def discard(self, abs_path: str) -> None:
        if self._data.pop(abs_path, None) is not None:
            self._dirty = True

    def clear(self) -> None:
        if self._data:
            self._data = {}
            self._dirty = True

    @property
    def dirty(self) -> bool:
        return self._dirty

    def save_if_dirty(self) -> None:
        if not self._dirty:
            return
        self._prune()
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(self._path.suffix + ".tmp")
            tmp.write_text(
                json.dumps({"version": CACHE_VERSION, "entries": self._data}),
                encoding="utf-8",
            )
            os.replace(tmp, self._path)
            self._dirty = False
        except OSError:
            # A failed cache write is never fatal; keep going.
            pass

    def _prune(self) -> None:
        if len(self._data) <= MAX_ENTRIES:
            return
        ranked = sorted(
            self._data.items(), key=lambda kv: kv[1]["at"], reverse=True
        )
        self._data = dict(ranked[:MAX_ENTRIES])
