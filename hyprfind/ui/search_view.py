"""Search results view.

Results are a flat list drawn from many directories, so they cannot reuse the
QFileSystemModel-backed views; this owns a small model of its own with a "Where"
column, matching Finder's search window.
"""

from __future__ import annotations

import os

from PyQt6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    Qt,
    QThread,
    QUrl,
    pyqtSignal,
)
from PyQt6.QtGui import QDesktopServices, QIcon
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QMenu,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from hyprfind.core.search import SearchHit, SearchQuery, SearchWorker
from hyprfind.ui.icons import ThemeIconProvider
from hyprfind.utils.formatting import format_bytes

COL_NAME = 0
COL_KIND = 1
COL_SIZE = 2
COL_WHERE = 3
HEADERS = ("Name", "Kind", "Size", "Where")


class SearchResultsModel(QAbstractTableModel):
    """Flat, append-only table of search hits."""

    def __init__(self, icon_provider: ThemeIconProvider | None = None, parent=None):
        super().__init__(parent)
        self._hits: list[SearchHit] = []
        self._icons = icon_provider
        self._home = os.path.expanduser("~")

    def clear(self) -> None:
        self.beginResetModel()
        self._hits = []
        self.endResetModel()

    def add_hits(self, hits: list[SearchHit]) -> None:
        if not hits:
            return
        start = len(self._hits)
        self.beginInsertRows(QModelIndex(), start, start + len(hits) - 1)
        self._hits.extend(hits)
        self.endInsertRows()

    def hit_at(self, row: int) -> SearchHit | None:
        if 0 <= row < len(self._hits):
            return self._hits[row]
        return None

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._hits)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return HEADERS[section]
        return None

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        hit = self._hits[index.row()]
        column = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if column == COL_NAME:
                return hit.name
            if column == COL_KIND:
                return "Folder" if hit.is_dir else self._kind(hit.name)
            if column == COL_SIZE:
                return "—" if hit.is_dir else format_bytes(hit.size)
            if column == COL_WHERE:
                return self._where(hit.parent)
        elif role == Qt.ItemDataRole.DecorationRole and column == COL_NAME:
            return self._icon(hit)
        elif role == Qt.ItemDataRole.ToolTipRole:
            return hit.path
        elif role == Qt.ItemDataRole.TextAlignmentRole and column == COL_SIZE:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        elif role == Qt.ItemDataRole.UserRole:
            return hit.path
        return None

    def _icon(self, hit: SearchHit) -> QIcon:
        if self._icons is None:
            return QIcon()
        from PyQt6.QtCore import QFileInfo

        return self._icons.icon(QFileInfo(hit.path))

    @staticmethod
    def _kind(name: str) -> str:
        ext = os.path.splitext(name)[1].lstrip(".")
        return f"{ext.upper()} file" if ext else "Document"

    def _where(self, parent: str) -> str:
        """Show the containing folder relative to home, as Finder does."""
        if parent == self._home:
            return "Home"
        if parent.startswith(self._home + os.sep):
            return parent[len(self._home) + 1 :]
        return parent


class SearchView(QWidget):
    """Results list plus a status line, driven by a background SearchWorker."""

    pathActivated = pyqtSignal(str)
    revealRequested = pyqtSignal(str)
    statusMessage = pyqtSignal(str)
    searchFinished = pyqtSignal(int)

    def __init__(self, icon_provider: ThemeIconProvider | None = None, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._status = QLabel("")
        self._status.setObjectName("searchStatus")
        layout.addWidget(self._status)

        self._model = SearchResultsModel(icon_provider, self)
        self._tree = QTreeView(self)
        self._tree.setModel(self._model)
        self._tree.setRootIsDecorated(False)
        self._tree.setAlternatingRowColors(True)
        self._tree.setUniformRowHeights(True)
        self._tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._tree.setSortingEnabled(False)
        self._tree.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._show_context_menu)
        self._tree.doubleClicked.connect(self._on_activated)
        self._tree.activated.connect(self._on_activated)
        layout.addWidget(self._tree)

        header = self._tree.header()
        header.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(COL_KIND, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(COL_SIZE, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(COL_WHERE, QHeaderView.ResizeMode.Stretch)
        header.resizeSection(COL_NAME, 280)
        header.resizeSection(COL_KIND, 110)
        header.resizeSection(COL_SIZE, 90)

        self._thread: QThread | None = None
        self._worker: SearchWorker | None = None
        self._query_text = ""

    # ------------------------------------------------------------------ running

    def start(self, query: SearchQuery) -> None:
        """Begin a search, replacing any in flight."""
        self.stop()
        self._query_text = query.text
        self._model.clear()
        scope = ", ".join(os.path.basename(r.rstrip(os.sep)) or r for r in query.roots)
        self._status.setText(f"Searching {scope} for “{query.text}”…")

        self._thread = QThread(self)
        self._worker = SearchWorker(query)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.hitsFound.connect(self._model.add_hits)
        self._worker.finished.connect(self._on_finished)
        self._thread.start()

    def stop(self) -> None:
        """Cancel any running search and join its thread."""
        if self._worker is not None:
            self._worker.cancel()
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(3000)
            self._thread = None
            self._worker = None

    def _on_finished(self, total: int, cancelled: bool, truncated: bool) -> None:
        if cancelled:
            self._status.setText(f"Search stopped — {total} found so far")
        elif total == 0:
            self._status.setText(f"No results for “{self._query_text}”")
        else:
            suffix = " (showing the first matches)" if truncated else ""
            plural = "s" if total != 1 else ""
            self._status.setText(f"{total} result{plural} for “{self._query_text}”{suffix}")
        self.searchFinished.emit(total)

    # ------------------------------------------------------------------ actions

    def result_count(self) -> int:
        return self._model.rowCount()

    def selected_paths(self) -> list[str]:
        rows = {index.row() for index in self._tree.selectedIndexes()}
        paths = []
        for row in sorted(rows):
            hit = self._model.hit_at(row)
            if hit is not None:
                paths.append(hit.path)
        return paths

    def _on_activated(self, index: QModelIndex) -> None:
        hit = self._model.hit_at(index.row())
        if hit is None:
            return
        self._open(hit.path)

    def _open(self, path: str) -> None:
        # Folders navigate the pane; files hand off to the desktop, matching
        # the behaviour of the browse views.
        if os.path.isdir(path):
            self.pathActivated.emit(path)
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _show_context_menu(self, pos) -> None:
        index = self._tree.indexAt(pos)
        hit = self._model.hit_at(index.row()) if index.isValid() else None
        if hit is None:
            return
        menu = QMenu(self)
        menu.addAction("Open", lambda: self._open(hit.path))
        menu.addAction(
            "Show in Enclosing Folder", lambda: self.revealRequested.emit(hit.path)
        )
        menu.addSeparator()
        menu.addAction(
            "Copy Path",
            lambda: self._copy_path(hit.path),
        )
        menu.exec(self._tree.viewport().mapToGlobal(pos))

    def _copy_path(self, path: str) -> None:
        from PyQt6.QtWidgets import QApplication

        QApplication.clipboard().setText(path)
        self.statusMessage.emit(f"Copied: {path}")

    def closeEvent(self, event) -> None:
        self.stop()
        super().closeEvent(event)
