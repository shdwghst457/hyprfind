"""Swappable list / icon / column views per browser pane."""

from __future__ import annotations

import os

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QColumnView,
    QLabel,
    QListView,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from hyprfind.core.model import HyprFileSystemModel
from hyprfind.core.trash import is_trash_directory, trash_count
from hyprfind.core.sort_proxy import FileSortProxyModel
from hyprfind.ui.file_list import FileListView


class IconFileView(QListView):
    pathActivated = pyqtSignal(str)
    selectionChangedSignal = pyqtSignal()

    def __init__(self, model: HyprFileSystemModel, proxy: FileSortProxyModel, parent=None):
        super().__init__(parent)
        self._model = model
        self._proxy = proxy
        self.setModel(proxy)
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setSpacing(8)
        self.setUniformItemSizes(True)
        self.setSelectionMode(QListView.SelectionMode.ExtendedSelection)
        self.setWordWrap(True)
        self.setIconSize(self.iconSize())
        self.doubleClicked.connect(self._on_double_click)

    def set_icon_size(self, size: int) -> None:
        from PyQt6.QtCore import QSize
        self.setIconSize(QSize(size, size))
        self.setGridSize(QSize(size + 80, size + 40))

    def set_root_path(self, path: str) -> None:
        source = self._model.resolve_directory_index(path)
        proxy_index = self._proxy.mapFromSource(source)
        if proxy_index.isValid():
            self.setRootIndex(proxy_index)

    def selected_paths(self) -> list[str]:
        paths: list[str] = []
        for index in self.selectedIndexes():
            source = self._proxy.mapToSource(index)
            if source.isValid():
                paths.append(self._model.filePath(source))
        return list(dict.fromkeys(paths))

    def _on_double_click(self, index) -> None:
        source = self._proxy.mapToSource(index)
        if source.isValid():
            self.pathActivated.emit(self._model.filePath(source))

    def selectionChanged(self, selected, deselected) -> None:
        super().selectionChanged(selected, deselected)
        self.selectionChangedSignal.emit()


class ColumnFileView(QColumnView):
    pathActivated = pyqtSignal(str)
    selectionChangedSignal = pyqtSignal()

    def __init__(self, model: HyprFileSystemModel, proxy: FileSortProxyModel, parent=None):
        super().__init__(parent)
        self._model = model
        self._proxy = proxy
        self.setModel(proxy)
        self.setSelectionMode(QColumnView.SelectionMode.SingleSelection)
        self.clicked.connect(self._on_click)

    def set_root_path(self, path: str) -> None:
        source = self._model.resolve_directory_index(path)
        proxy_index = self._proxy.mapFromSource(source)
        if proxy_index.isValid():
            self.setRootIndex(proxy_index)

    def selected_paths(self) -> list[str]:
        index = self.currentIndex()
        if not index.isValid():
            return []
        source = self._proxy.mapToSource(index)
        if source.isValid():
            return [self._model.filePath(source)]
        return []

    def _on_click(self, index) -> None:
        source = self._proxy.mapToSource(index)
        if not source.isValid():
            return
        path = self._model.filePath(source)
        if os.path.isdir(path):
            self.pathActivated.emit(path)


class ViewStack(QWidget):
    """Hosts list, icon, and column views; exposes a unified API."""

    pathActivated = pyqtSignal(str)
    openParentRequested = pyqtSignal()
    previewRequested = pyqtSignal(str)
    addFavoriteRequested = pyqtSignal(str, str)
    statusMessage = pyqtSignal(str)
    filesTransferred = pyqtSignal(str, str)
    dragSourceFinished = pyqtSignal()
    selectionChanged = pyqtSignal()

    def __init__(self, model: HyprFileSystemModel, parent=None) -> None:
        super().__init__(parent)
        self._model = model
        self._mode = "list"
        self._current_path = ""
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._empty_label = QLabel(self)
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet("color: #888888; font-size: 14px;")
        self._empty_label.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._stack = QStackedWidget()
        layout.addWidget(self._stack)

        self.file_list = FileListView(model)
        self._proxy_icon = FileSortProxyModel(self)
        self._proxy_icon.setSourceModel(model)
        self._proxy_column = FileSortProxyModel(self)
        self._proxy_column.setSourceModel(model)
        self.icon_view = IconFileView(model, self._proxy_icon)
        self.column_view = ColumnFileView(model, self._proxy_column)

        self._stack.addWidget(self.file_list)
        self._stack.addWidget(self.icon_view)
        self._stack.addWidget(self.column_view)

        self.file_list.pathActivated.connect(self.pathActivated)
        self.file_list.openParentRequested.connect(self.openParentRequested)
        self.file_list.previewRequested.connect(self.previewRequested)
        self.file_list.addFavoriteRequested.connect(self.addFavoriteRequested)
        self.file_list.statusMessage.connect(self.statusMessage)
        self.file_list.filesTransferred.connect(self.filesTransferred)
        self.file_list.dragSourceFinished.connect(self.dragSourceFinished)
        self.icon_view.pathActivated.connect(self.pathActivated)
        self.column_view.pathActivated.connect(self.pathActivated)
        self.icon_view.selectionChangedSignal.connect(self.selectionChanged)
        self.file_list.selectionModel().selectionChanged.connect(
            lambda *_: self.selectionChanged.emit()
        )
        self._model.directoryRefreshed.connect(self._on_directory_refreshed)

    def _on_directory_refreshed(self, path: str) -> None:
        if self._current_path and os.path.normpath(path) == os.path.normpath(
            self._current_path
        ):
            self._update_empty_state()

    @property
    def active_view(self):
        if self._mode == "icon":
            return self.icon_view
        if self._mode == "column":
            return self.column_view
        return self.file_list

    def set_view_mode(self, mode: str, icon_size: int = 48) -> None:
        self._mode = mode
        if mode == "icon":
            self.icon_view.set_icon_size(icon_size)
            self._stack.setCurrentWidget(self.icon_view)
        elif mode == "column":
            self._stack.setCurrentWidget(self.column_view)
        else:
            self._stack.setCurrentWidget(self.file_list)

    def set_current_directory(self, path: str) -> None:
        self._current_path = path
        self.file_list.set_current_directory(path)
        self.icon_view.set_root_path(path)
        self.column_view.set_root_path(path)
        QTimer.singleShot(0, lambda: self._update_empty_state())
        QTimer.singleShot(150, lambda: self._update_empty_state())

    def _update_empty_state(self) -> None:
        path = self._current_path
        if not path or not is_trash_directory(path):
            self._empty_label.hide()
            return
        if trash_count() == 0:
            self._empty_label.setText("No items in Trash")
            self._empty_label.show()
            self._empty_label.raise_()
        else:
            self._empty_label.hide()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._empty_label.isVisible():
            self._empty_label.setGeometry(self.rect())

    def set_name_filter(self, text: str) -> None:
        self.file_list._proxy.set_name_filter(text)
        self._proxy_icon.set_name_filter(text)
        self._proxy_column.set_name_filter(text)

    def selected_paths(self) -> list[str]:
        return self.active_view.selected_paths() if hasattr(self.active_view, "selected_paths") else self.file_list.selected_paths()

    def setFocus(self) -> None:
        self.active_view.setFocus()
