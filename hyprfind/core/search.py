"""Recursive filename search.

Runs on a worker thread and streams batched results, so searching a large tree
(or a slow SMB share) shows hits as they are found instead of freezing until the
whole walk completes.
"""

from __future__ import annotations

import fnmatch
import os
import time
from dataclasses import dataclass, field

from PyQt6.QtCore import QObject, pyqtSignal

# Emit in batches: one signal per hit would swamp the event loop on a big tree.
BATCH_SIZE = 64
BATCH_INTERVAL = 0.15

# Stop after this many hits. A query like "e" would otherwise match everything
# and the results view would grow without bound.
MAX_RESULTS = 10_000

# Kernel and device trees: never user data, and walking them can block.
PRUNED_PREFIXES = ("/proc", "/sys", "/dev", "/run/user")

SCOPE_EVERYWHERE = "everywhere"
SCOPE_HERE = "here"


@dataclass(frozen=True)
class SearchHit:
    path: str
    name: str
    size: int
    mtime: float
    is_dir: bool

    @property
    def parent(self) -> str:
        return os.path.dirname(self.path)


@dataclass
class SearchQuery:
    """What to look for and where."""

    text: str
    roots: list[str] = field(default_factory=list)
    include_hidden: bool = False
    directories_only: bool = False

    def matcher(self):
        """Return a predicate over file names.

        Wildcards make it a glob (Finder's advanced search); otherwise it is a
        forgiving case-insensitive substring match.
        """
        needle = self.text.strip()
        if not needle:
            return None
        lowered = needle.casefold()
        if any(char in needle for char in "*?["):
            return lambda name: fnmatch.fnmatchcase(name.casefold(), lowered)
        return lambda name: lowered in name.casefold()


def _is_pruned(path: str) -> bool:
    normalized = os.path.normpath(path)
    return any(
        normalized == prefix or normalized.startswith(prefix + os.sep)
        for prefix in PRUNED_PREFIXES
    )


class SearchWorker(QObject):
    """Walks the roots of a query, emitting batches of hits."""

    hitsFound = pyqtSignal(list)
    progress = pyqtSignal(str)
    finished = pyqtSignal(int, bool, bool)  # total, cancelled, truncated

    def __init__(self, query: SearchQuery) -> None:
        super().__init__()
        self._query = query
        self._cancelled = False

    def cancel(self) -> None:
        """Safe from the GUI thread; the walk checks the flag between entries."""
        self._cancelled = True

    def run(self) -> None:
        matches = self._query.matcher()
        if matches is None:
            self.finished.emit(0, False, False)
            return

        batch: list[SearchHit] = []
        total = 0
        truncated = False
        last_flush = time.monotonic()
        last_progress = last_flush
        seen_dirs: set[tuple[int, int]] = set()

        for root in self._query.roots:
            if self._cancelled or truncated:
                break
            for hit in self._walk(root, matches, seen_dirs):
                if self._cancelled:
                    break
                batch.append(hit)
                total += 1
                if total >= MAX_RESULTS:
                    truncated = True
                    break

                now = time.monotonic()
                if len(batch) >= BATCH_SIZE or now - last_flush >= BATCH_INTERVAL:
                    self.hitsFound.emit(batch)
                    batch = []
                    last_flush = now
                if now - last_progress >= 0.3:
                    self.progress.emit(hit.parent)
                    last_progress = now

        if batch:
            self.hitsFound.emit(batch)
        self.finished.emit(total, self._cancelled, truncated)

    def _walk(self, root: str, matches, seen_dirs: set[tuple[int, int]]):
        """Depth-first walk with an explicit stack and loop protection."""
        stack = [root]
        include_hidden = self._query.include_hidden
        dirs_only = self._query.directories_only

        while stack:
            if self._cancelled:
                return
            current = stack.pop()
            if _is_pruned(current):
                continue
            try:
                entries = list(os.scandir(current))
            except OSError:
                # Unreadable directory (permissions, dead share); skip it.
                continue

            for entry in entries:
                if self._cancelled:
                    return
                name = entry.name
                if not include_hidden and name.startswith("."):
                    continue
                try:
                    is_dir = entry.is_dir(follow_symlinks=False)
                except OSError:
                    continue

                if is_dir:
                    key = self._identity(entry)
                    if key is not None and key in seen_dirs:
                        continue  # Already visited via a bind mount or hard link.
                    if key is not None:
                        seen_dirs.add(key)
                    stack.append(entry.path)

                if dirs_only and not is_dir:
                    continue
                if not matches(name):
                    continue
                yield self._to_hit(entry, is_dir)

    @staticmethod
    def _identity(entry) -> tuple[int, int] | None:
        try:
            stat = entry.stat(follow_symlinks=False)
        except OSError:
            return None
        return (stat.st_dev, stat.st_ino)

    @staticmethod
    def _to_hit(entry, is_dir: bool) -> SearchHit:
        try:
            stat = entry.stat(follow_symlinks=False)
            size = 0 if is_dir else stat.st_size
            mtime = stat.st_mtime
        except OSError:
            size, mtime = 0, 0.0
        return SearchHit(
            path=entry.path, name=entry.name, size=size, mtime=mtime, is_dir=is_dir
        )


def search_roots(scope: str, current_directory: str, home: str) -> list[str]:
    """Roots for a scope: the current folder, or the user's whole home."""
    if scope == SCOPE_HERE and current_directory:
        return [current_directory]
    return [home]
