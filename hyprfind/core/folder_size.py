"""Background folder size calculation — idle-priority, non-blocking UI."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import QObject, QRunnable, QThread, QThreadPool, QTimer, pyqtSignal, pyqtSlot

from hyprfind.core.size_cache import PersistentSizeCache
from hyprfind.utils.paths import cache_dir

MAX_WORKERS = 2
MAX_NETWORK_WORKERS = 1
MAX_IN_MEMORY_CACHE = 5000

MAX_FILES_LOCAL = 200_000
MAX_FILES_NETWORK = 100_000
MAX_SECONDS_LOCAL = 600.0
MAX_SECONDS_NETWORK = 300.0

IDLE_DELAY_MS = 350
PUMP_DELAY_MS = 25
NETWORK_YIELD_EVERY = 48
NETWORK_YIELD_SECONDS = 0.004


def list_child_directories(directory: str) -> list[str]:
    """Return absolute paths of direct child folders (safe for worker threads)."""
    paths: list[str] = []
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        paths.append(os.path.abspath(entry.path))
                except OSError:
                    continue
    except OSError:
        return []
    return paths


# Outcome of a folder-size walk.
SIZE_COMPLETE = "complete"  # full, trustworthy walk — safe to cache to disk
SIZE_PARTIAL = "partial"    # cut short (timeout/limit) or a subtree was skipped
SIZE_ERROR = "error"        # nothing usable could be read


def compute_folder_size(path: str, *, network: bool = False) -> tuple[int, str]:
    """Walk a folder and return ``(byte_size, status)``.

    ``status`` is one of ``SIZE_COMPLETE``, ``SIZE_PARTIAL`` or ``SIZE_ERROR``:

      * COMPLETE — the whole subtree was read; the byte count is authoritative
        and may be persisted to the on-disk cache.
      * PARTIAL  — the walk was truncated (timeout / file-count cap) or at least
        one subdirectory or entry could not be read, so the count is a lower
        bound. Shown to the user but never persisted, so it is retried later.
      * ERROR    — the folder itself was unreadable, or every entry failed and
        nothing was counted. Surfaced as "—" rather than a misleading "0 bytes".
    """
    max_files = MAX_FILES_NETWORK if network else MAX_FILES_LOCAL
    max_seconds = MAX_SECONDS_NETWORK if network else MAX_SECONDS_LOCAL
    deadline = time.monotonic() + max_seconds
    total = 0
    files_seen = 0
    ops = 0
    truncated = False
    had_errors = False

    root = os.path.abspath(path)
    stack = [root]
    while stack:
        if time.monotonic() > deadline:
            truncated = True
            break
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    if time.monotonic() > deadline:
                        truncated = True
                        break
                    ops += 1
                    if network and ops % NETWORK_YIELD_EVERY == 0:
                        time.sleep(NETWORK_YIELD_SECONDS)
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            files_seen += 1
                            if files_seen > max_files:
                                truncated = True
                                break
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        # A single unreadable entry: skip it, but the total is
                        # now a lower bound.
                        had_errors = True
                        continue
        except OSError:
            if current == root:
                # Can't even read the folder we were asked about.
                return 0, SIZE_ERROR
            # A whole subtree is unreadable — significant undercount.
            had_errors = True
            continue
        if truncated:
            break

    if truncated:
        return total, SIZE_PARTIAL
    if had_errors:
        return (total, SIZE_ERROR) if total == 0 else (total, SIZE_PARTIAL)
    return total, SIZE_COMPLETE


class _FolderSizeWorker(QRunnable):
    def __init__(
        self,
        path: str,
        generation: int,
        network: bool,
        signals: QObject,
    ) -> None:
        super().__init__()
        self._path = path
        self._generation = generation
        self._network = network
        self._signals = signals
        self.setAutoDelete(True)

    def run(self) -> None:
        thread = QThread.currentThread()
        if thread is not None:
            thread.setPriority(QThread.Priority.LowestPriority)
        size, status = compute_folder_size(self._path, network=self._network)
        self._signals.finished.emit(
            self._path, size, status, self._generation, self._network
        )


class _DirectoryScanWorker(QRunnable):
    def __init__(self, directory: str, signals: QObject) -> None:
        super().__init__()
        self._directory = directory
        self._signals = signals
        self.setAutoDelete(True)

    def run(self) -> None:
        thread = QThread.currentThread()
        if thread is not None:
            thread.setPriority(QThread.Priority.LowestPriority)
        paths = list_child_directories(self._directory)
        self._signals.scanned.emit(self._directory, paths)


class _FolderSizeSignals(QObject):
    finished = pyqtSignal(str, int, str, int, bool)


class _DirectoryScanSignals(QObject):
    scanned = pyqtSignal(str, list)


class FolderSizeCalculator(QObject):
    """Idle-priority queue; yields I/O and UI time while sizes are calculated."""

    sizeReady = pyqtSignal(str, int)
    sizeFailed = pyqtSignal(str)
    directoryScanned = pyqtSignal(str, list)
    queueChanged = pyqtSignal(int)

    def __init__(
        self,
        is_network_path: Callable[[str], bool] | None = None,
        parent: QObject | None = None,
        persistent_path: Path | None = None,
    ) -> None:
        super().__init__(parent)
        self._is_network_path = is_network_path or (lambda _path: False)
        self._cache: dict[str, int] = {}
        self._persistent = PersistentSizeCache(
            persistent_path or (cache_dir() / "folder_sizes.json")
        )
        self._persistent.load()
        self._failed: set[str] = set()
        self._pending: set[str] = set()
        self._queued: list[str] = []
        self._active = 0
        self._network_active = 0
        self._generation = 0
        self._user_active = False
        self._signals = _FolderSizeSignals()
        self._signals.finished.connect(self._on_finished)
        self._scan_signals = _DirectoryScanSignals()
        self._scan_signals.scanned.connect(self._emit_directory_scanned)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(MAX_WORKERS)
        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.setInterval(IDLE_DELAY_MS)
        self._idle_timer.timeout.connect(self._on_user_idle)
        self._pump_timer = QTimer(self)
        self._pump_timer.setSingleShot(True)
        self._pump_timer.setInterval(PUMP_DELAY_MS)
        self._pump_timer.timeout.connect(self._pump)
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(2000)
        self._save_timer.timeout.connect(self._persistent.save_if_dirty)

    def cached_size(self, path: str) -> int | None:
        return self._cache.get(os.path.abspath(path))

    def is_failed(self, path: str) -> bool:
        return os.path.abspath(path) in self._failed

    def is_network_path(self, path: str) -> bool:
        return self._is_network_path(os.path.abspath(path))

    def is_pending(self, path: str) -> bool:
        return os.path.abspath(path) in self._pending

    def pending_count(self) -> int:
        return len(self._pending)

    def notify_user_activity(self) -> None:
        self._user_active = True
        self._idle_timer.start()

    def scan_directory_async(self, directory: str) -> None:
        """Discover child folders on a worker thread."""
        worker = _DirectoryScanWorker(os.path.abspath(directory), self._scan_signals)
        self._pool.start(worker)

    def clear_pending(self) -> None:
        self._generation += 1
        self._queued.clear()
        self._pending.clear()
        self._failed.clear()
        self._emit_queue_changed()

    def schedule(self, paths: list[str]) -> list[str]:
        """Queue paths in one batch — no per-item signals.

        Folders whose persisted size is still valid (directory mtime unchanged)
        are served straight from disk: they go into the in-memory cache and emit
        ``sizeReady`` immediately instead of being walked again.
        """
        queued: list[str] = []
        promoted: list[str] = []
        for path in paths:
            normalized = os.path.abspath(path)
            if (
                normalized in self._cache
                or normalized in self._pending
                or normalized in self._failed
            ):
                continue
            cached = self._persistent.get_valid(normalized)
            if cached is not None:
                self._cache[normalized] = cached
                promoted.append(normalized)
                continue
            self._pending.add(normalized)
            self._queued.append(normalized)
            queued.append(normalized)
        if self._persistent.dirty:
            self._schedule_save()
        for normalized in promoted:
            self.sizeReady.emit(normalized, self._cache[normalized])
        if queued:
            self._emit_queue_changed()
            self._schedule_pump()
        return queued

    def _enqueue(self, path: str) -> bool:
        return bool(self.schedule([path]))

    def _emit_queue_changed(self) -> None:
        self.queueChanged.emit(len(self._pending))

    def _schedule_pump(self) -> None:
        if not self._pump_timer.isActive():
            self._pump_timer.start()

    def _schedule_save(self) -> None:
        if not self._save_timer.isActive():
            self._save_timer.start()

    def flush(self) -> None:
        """Persist any pending cache changes immediately (e.g. on app exit)."""
        self._save_timer.stop()
        self._persistent.save_if_dirty()

    def _on_user_idle(self) -> None:
        self._user_active = False
        self._schedule_pump()

    def _pop_next_job(self) -> str | None:
        local_idx = next(
            (
                i
                for i, path in enumerate(self._queued)
                if not self._is_network_path(path)
            ),
            None,
        )
        if local_idx is not None and self._active < MAX_WORKERS:
            return self._queued.pop(local_idx)

        if self._network_active < MAX_NETWORK_WORKERS and self._active < MAX_WORKERS:
            net_idx = next(
                (
                    i
                    for i, path in enumerate(self._queued)
                    if self._is_network_path(path)
                ),
                None,
            )
            if net_idx is not None:
                return self._queued.pop(net_idx)
        return None

    def _pump(self) -> None:
        if self._user_active:
            return
        started = 0
        while self._queued and self._active < MAX_WORKERS:
            path = self._pop_next_job()
            if path is None:
                break
            if path not in self._pending:
                continue
            network = self._is_network_path(path)
            self._active += 1
            if network:
                self._network_active += 1
            worker = _FolderSizeWorker(path, self._generation, network, self._signals)
            self._pool.start(worker)
            started += 1
            if network:
                break
        if self._queued and self._active < MAX_WORKERS and not self._user_active:
            self._schedule_pump()
        elif self._queued and self._user_active:
            self._idle_timer.start()

    def invalidate(self, path: str) -> None:
        normalized = os.path.abspath(path)
        self._cache.pop(normalized, None)
        self._failed.discard(normalized)
        self._pending.discard(normalized)
        self._persistent.discard(normalized)
        if self._persistent.dirty:
            self._schedule_save()
        if normalized in self._queued:
            self._queued = [p for p in self._queued if p != normalized]
        self._emit_queue_changed()

    @pyqtSlot(str, list)
    def _emit_directory_scanned(self, directory: str, paths: list) -> None:
        self.directoryScanned.emit(directory, paths)

    @pyqtSlot(str, int, str, int, bool)
    def _on_finished(
        self,
        path: str,
        size: int,
        status: str,
        generation: int,
        network: bool,
    ) -> None:
        self._active = max(0, self._active - 1)
        if network:
            self._network_active = max(0, self._network_active - 1)
        self._pending.discard(path)
        self._emit_queue_changed()

        if generation != self._generation:
            self._schedule_pump()
            return

        if status == SIZE_ERROR:
            self._failed.add(path)
            self.sizeFailed.emit(path)
        else:
            value = max(0, size)
            self._cache[path] = value
            if len(self._cache) > MAX_IN_MEMORY_CACHE:
                drop = max(1, len(self._cache) // 10)
                for key in list(self._cache.keys())[:drop]:
                    self._cache.pop(key, None)
            # Only a complete walk is trustworthy enough to persist; partial
            # results stay in memory for this session and are recomputed later.
            if status == SIZE_COMPLETE:
                self._persistent.put(path, value)
                self._schedule_save()
            self.sizeReady.emit(path, value)
        self._schedule_pump()
