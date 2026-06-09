"""Directory refresh: inotify for local paths, polling for network mounts."""

from __future__ import annotations

import os
from typing import Literal

from hyprfind.core.mounts import NETWORK_FSTYPES, MountService
from hyprfind.utils.paths import gvfs_base

Strategy = Literal["inotify", "poll"]


def directory_snapshot(path: str) -> dict[str, tuple[int, int]]:
    """Return mapping of name -> (mtime_ns, size) for directory entries."""
    snapshot: dict[str, tuple[int, int]] = {}
    try:
        with os.scandir(path) as entries:
            for entry in entries:
                if entry.name in {".", ".."}:
                    continue
                try:
                    stat = entry.stat(follow_symlinks=False)
                    snapshot[entry.name] = (stat.st_mtime_ns, stat.st_size)
                except OSError:
                    snapshot[entry.name] = (0, 0)
    except OSError:
        pass
    return snapshot


def snapshots_differ(
    before: dict[str, tuple[int, int]], after: dict[str, tuple[int, int]]
) -> bool:
    return before != after


def strategy_for(path: str, mount_service: MountService) -> Strategy:
    normalized = os.path.abspath(os.path.expanduser(path))
    mount = mount_service.mount_for_path(normalized)
    if mount and mount.fstype in NETWORK_FSTYPES:
        return "poll"
    if normalized.startswith(gvfs_base()):
        return "poll"
    return "inotify"


class DirectoryRefreshService:
    """Qt-backed directory watcher; defers PyQt6 import until instantiation."""

    def __new__(cls, *args, **kwargs):
        from PyQt6.QtCore import QObject, QTimer, QFileSystemWatcher, pyqtSignal

        class _Service(QObject):
            changed = pyqtSignal(str)
            strategyChanged = pyqtSignal(str, str)

            def __init__(
                self,
                mount_service: MountService,
                poll_interval_ms: int = 1500,
                parent=None,
            ) -> None:
                super().__init__(parent)
                self._mount_service = mount_service
                self._poll_interval_ms = poll_interval_ms
                self._current_path: str | None = None
                self._strategy: Strategy | None = None
                self._snapshot: dict[str, tuple[int, int]] = {}
                self._watcher: QFileSystemWatcher | None = None
                self._poll_timer = QTimer(self)
                self._poll_timer.setInterval(poll_interval_ms)
                self._poll_timer.timeout.connect(self._poll_tick)

            @property
            def current_path(self) -> str | None:
                return self._current_path

            @property
            def strategy(self) -> Strategy | None:
                return self._strategy

            def status_label(self) -> str:
                if not self._current_path:
                    return ""
                if self._strategy == "poll":
                    mount = self._mount_service.mount_for_path(self._current_path)
                    if mount and mount.fstype in {"cifs", "smb3"}:
                        return "Polling (CIFS)"
                    return "Polling (SMB)"
                return "Watching"

            def watch(self, path: str) -> None:
                normalized = os.path.abspath(os.path.expanduser(path))
                if not os.path.isdir(normalized):
                    return

                self.stop()
                self._current_path = normalized
                self._strategy = strategy_for(normalized, self._mount_service)
                self._snapshot = directory_snapshot(normalized)
                self.strategyChanged.emit(normalized, self._strategy)

                if self._strategy == "inotify":
                    self._watcher = QFileSystemWatcher(self)
                    self._watcher.directoryChanged.connect(self._on_inotify_changed)
                    self._watcher.fileChanged.connect(self._on_inotify_changed)
                    self._watcher.addPath(normalized)
                else:
                    self._poll_timer.start()

            def stop(self) -> None:
                self._poll_timer.stop()
                if self._watcher is not None:
                    paths = list(self._watcher.directories()) + list(
                        self._watcher.files()
                    )
                    if paths:
                        self._watcher.removePaths(paths)
                    self._watcher.deleteLater()
                    self._watcher = None
                self._current_path = None
                self._strategy = None
                self._snapshot = {}

            def force_poll_check(self) -> bool:
                if not self._current_path:
                    return False
                current = directory_snapshot(self._current_path)
                if snapshots_differ(self._snapshot, current):
                    self._snapshot = current
                    self.changed.emit(self._current_path)
                    return True
                return False

            def _on_inotify_changed(self, _path: str) -> None:
                if self._current_path:
                    self.changed.emit(self._current_path)

            def _poll_tick(self) -> None:
                if not self._current_path:
                    return
                current = directory_snapshot(self._current_path)
                if snapshots_differ(self._snapshot, current):
                    self._snapshot = current
                    self.changed.emit(self._current_path)

        return _Service(*args, **kwargs)
