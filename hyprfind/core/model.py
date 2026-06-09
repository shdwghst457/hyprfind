"""Filesystem model with targeted directory refresh and folder sizes."""

from __future__ import annotations

import os
from collections.abc import Callable

from PyQt6.QtCore import QDir, QModelIndex, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFileSystemModel

from hyprfind.core.folder_size import FolderSizeCalculator
from hyprfind.core.fs_columns import DATE_MODIFIED, SIZE
from hyprfind.utils.formatting import format_bytes

FOLDER_SIZE_CALCULATING = "Calculating…"
FOLDER_SIZE_UNAVAILABLE = "—"


class HyprFileSystemModel(QFileSystemModel):
    directoryRefreshed = pyqtSignal(str)

    def __init__(
        self,
        is_network_path: Callable[[str], bool] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setReadOnly(False)
        self.setFilter(
            QDir.Filter.AllDirs
            | QDir.Filter.Files
            | QDir.Filter.NoDotAndDotDot
            | QDir.Filter.Drives
        )
        self.setResolveSymlinks(True)
        self._show_hidden = False
        self._active_directory: str | None = None
        self._folder_sizes = FolderSizeCalculator(is_network_path, parent=self)
        self._folder_sizes.sizeReady.connect(self._on_folder_size_ready)
        self._folder_sizes.sizeFailed.connect(self._on_folder_size_failed)
        self._folder_sizes.directoryScanned.connect(self._on_child_directories_scanned)
        self._dirty_size_paths: set[str] = set()
        self._size_flush_timer = QTimer(self)
        self._size_flush_timer.setSingleShot(True)
        self._size_flush_timer.setInterval(80)
        self._size_flush_timer.timeout.connect(self._flush_folder_size_cells)
        self._rescan_timer = QTimer(self)
        self._rescan_timer.setSingleShot(True)
        self._rescan_timer.setInterval(400)
        self._rescan_timer.timeout.connect(self._rescan_active_directory)
        self.directoryLoaded.connect(self._on_directory_loaded)

    def folder_size_calculator(self) -> FolderSizeCalculator:
        return self._folder_sizes

    def set_show_hidden(self, show: bool) -> None:
        self._show_hidden = show
        filters = (
            QDir.Filter.AllDirs
            | QDir.Filter.Files
            | QDir.Filter.NoDotAndDotDot
            | QDir.Filter.Drives
        )
        if show:
            filters |= QDir.Filter.Hidden
        self.setFilter(filters)

    def resolve_directory_index(self, path: str) -> QModelIndex:
        """Return a source-model index for directory ``path``, or invalid."""
        normalized = os.path.abspath(os.path.expanduser(path))
        idx = self.index(normalized)
        if idx.isValid():
            return idx

        # QFileSystemModel may not have loaded ancestors yet; walk up the chain.
        parent = normalized
        while parent and parent != os.path.dirname(parent):
            self.index(parent)
            parent = os.path.dirname(parent)
        idx = self.index(normalized)
        if idx.isValid():
            return idx

        # Last resort: ask the model to watch the path, then restore prior root.
        saved_root = self.rootPath()
        self.setRootPath(normalized)
        idx = self.index(normalized)
        if saved_root:
            self.setRootPath(saved_root)
        return idx

    def set_active_directory(self, path: str) -> None:
        normalized = os.path.abspath(os.path.expanduser(path))
        self._active_directory = normalized
        self.clear_folder_size_queue()
        self._dirty_size_paths.clear()
        QTimer.singleShot(0, lambda: self._start_folder_size_scan(normalized))

    def _folder_size_display(self, path: str) -> str:
        cached = self._folder_sizes.cached_size(path)
        if cached is not None:
            return format_bytes(cached)
        if self._folder_sizes.is_failed(path):
            return FOLDER_SIZE_UNAVAILABLE
        if self._folder_sizes.is_pending(path):
            return FOLDER_SIZE_CALCULATING
        return ""

    def item_byte_size(self, index: QModelIndex) -> int:
        if not index.isValid():
            return 0
        if self.isDir(index):
            path = self.filePath(index)
            cached = self._folder_sizes.cached_size(path)
            return cached if cached is not None else 0
        return super().size(index)

    def size(self, index: QModelIndex) -> int:
        return self.item_byte_size(index)

    def hasChildren(self, parent: QModelIndex = QModelIndex()) -> bool:
        if parent.isValid() and self.isDir(parent):
            return True
        return super().hasChildren(parent)

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ):
        if (
            orientation == Qt.Orientation.Horizontal
            and role == Qt.ItemDataRole.TextAlignmentRole
            and section in (SIZE, DATE_MODIFIED)
        ):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return super().headerData(section, orientation, role)

    def type(self, index: QModelIndex) -> str:
        if index.isValid() and os.path.islink(self.filePath(index)):
            return "Alias"
        return super().type(index)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.TextAlignmentRole:
            if index.column() in (SIZE, DATE_MODIFIED):
                return int(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
        if (
            role == Qt.ItemDataRole.DisplayRole
            and index.column() == SIZE
            and self.isDir(index)
        ):
            return self._folder_size_display(self.filePath(index))
        return super().data(index, role)

    def clear_folder_size_queue(self) -> None:
        self._folder_sizes.clear_pending()

    def _model_child_folder_paths(self, directory: str) -> list[str]:
        paths: list[str] = []
        dir_index = self.index(directory)
        if not dir_index.isValid():
            return paths
        for row in range(self.rowCount(dir_index)):
            child = self.index(row, 0, dir_index)
            if child.isValid() and self.isDir(child):
                paths.append(os.path.abspath(self.filePath(child)))
        return paths

    def _start_folder_size_scan(self, directory: str) -> None:
        if not self._active_directory:
            return
        if os.path.normpath(directory) != os.path.normpath(self._active_directory):
            return
        self._folder_sizes.scan_directory_async(directory)
        self._queue_model_folder_paths(directory)

    def _queue_model_folder_paths(self, directory: str) -> None:
        self._schedule_folder_paths(self._model_child_folder_paths(directory))

    def _on_child_directories_scanned(self, directory: str, paths: list) -> None:
        if not self._active_directory:
            return
        if os.path.normpath(directory) != os.path.normpath(self._active_directory):
            return
        self._schedule_folder_paths(paths)

    def _schedule_folder_paths(self, paths: list[str]) -> None:
        queued = self._folder_sizes.schedule(paths)
        if queued:
            self._mark_folder_size_dirty(queued)

    def _mark_folder_size_dirty(self, paths: list[str] | str) -> None:
        if isinstance(paths, str):
            self._dirty_size_paths.add(paths)
        else:
            self._dirty_size_paths.update(paths)
        if not self._size_flush_timer.isActive():
            self._size_flush_timer.start()

    def _flush_folder_size_cells(self) -> None:
        batch = []
        for _ in range(30):
            if not self._dirty_size_paths:
                break
            batch.append(self._dirty_size_paths.pop())
        for path in batch:
            self._emit_folder_size_cell(path)
        if self._dirty_size_paths:
            self._size_flush_timer.start()

    def _on_directory_loaded(self, path: str) -> None:
        if not self._active_directory:
            return
        normalized = os.path.normpath(path)
        active = os.path.normpath(self._active_directory)
        if normalized == active:
            self._rescan_timer.start()

    def _rescan_active_directory(self) -> None:
        if not self._active_directory:
            return
        directory = self._active_directory
        cached = [
            path
            for path in self._model_child_folder_paths(directory)
            if self._folder_sizes.cached_size(path) is not None
        ]
        if cached:
            self._mark_folder_size_dirty(cached)
        self._queue_model_folder_paths(directory)

    def refresh_directory(self, path: str) -> None:
        normalized = os.path.abspath(os.path.expanduser(path))
        if not os.path.isdir(normalized):
            return

        self._folder_sizes.invalidate(normalized)

        index = self.index(normalized)
        if index.isValid():
            rows = self.rowCount(index)
            if rows > 0:
                top_left = self.index(0, 0, index)
                bottom_right = self.index(
                    rows - 1, self.columnCount() - 1, index
                )
                self.dataChanged.emit(
                    top_left,
                    bottom_right,
                    [Qt.ItemDataRole.DisplayRole],
                )

        # Heavy rootPath reset only for the actively viewed directory (SMB poll
        # needs it); other paths just invalidate sizes and notify listeners.
        if self._active_directory and os.path.normpath(
            normalized
        ) == os.path.normpath(self._active_directory):
            saved_root = self.rootPath()
            self.setRootPath("")
            self.setRootPath(saved_root if saved_root else QDir.rootPath())
        self.directoryRefreshed.emit(normalized)
        if self._active_directory and os.path.normpath(
            normalized
        ) == os.path.normpath(self._active_directory):
            self._rescan_timer.start()

    def _emit_folder_size_cell(self, path: str) -> None:
        index = self.index(path, 0)
        if not index.isValid():
            return
        size_index = self.index(index.row(), SIZE, index.parent())
        self.dataChanged.emit(size_index, size_index, [Qt.ItemDataRole.DisplayRole])

    def notify_user_activity(self) -> None:
        self._folder_sizes.notify_user_activity()

    def _on_folder_size_ready(self, path: str) -> None:
        self._mark_folder_size_dirty(path)

    def _on_folder_size_failed(self, path: str) -> None:
        self._mark_folder_size_dirty(path)

    def path_from_index(self, index: QModelIndex) -> str:
        if not index.isValid():
            return ""
        return self.filePath(index)
