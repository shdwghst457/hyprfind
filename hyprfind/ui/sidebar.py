"""Sidebar with favorites and mounted volumes."""

from __future__ import annotations

import os

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QFontMetrics, QPen
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from hyprfind.core.bookmarks import BookmarkStore
from hyprfind.core.file_ops import TransferOp
from hyprfind.core.mounts import Mount, MountService
from hyprfind.core.trash import (
    _ensure_trash,
    is_trash_directory,
    trash_count,
    trash_path,
)
from hyprfind.ui.drag_support import (
    highlight_colors,
    operation_for_modifiers,
    same_device,
)
from hyprfind.utils.paths import bookmark_name_for_path


def _drop_action_for(operation: TransferOp) -> Qt.DropAction:
    if operation is TransferOp.COPY:
        return Qt.DropAction.CopyAction
    if operation is TransferOp.ALIAS:
        return Qt.DropAction.LinkAction
    return Qt.DropAction.MoveAction


class _SidebarDropDelegate(QStyledItemDelegate):
    """Paints a Finder-style drop highlight over the hovered sidebar row."""

    def __init__(self, view: "_SidebarDropList", parent=None) -> None:
        super().__init__(parent)
        self._view = view

    def paint(self, painter, option, index) -> None:
        super().paint(painter, option, index)
        view = self._view
        if view._drop_row < 0 or index.row() != view._drop_row:
            return
        fill, border = highlight_colors(view._drop_op)
        inner = option.rect.adjusted(2, 2, -2, -2)
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        painter.drawRoundedRect(inner, 6, 6)
        painter.setPen(QPen(border, 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(inner, 6, 6)
        painter.restore()


class _SidebarDropList(QListWidget):
    """A favorites/volumes list that accepts file drops onto folder rows."""

    filesDropped = pyqtSignal(list, str, str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._drop_row = -1
        self._drop_op = TransferOp.MOVE
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(False)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self.viewport().setAcceptDrops(True)
        self.setItemDelegate(_SidebarDropDelegate(self, self))

    def _dest_for_pos(self, pos) -> tuple[str | None, int]:
        item = self.itemAt(pos)
        if item is None:
            return None, -1
        path = item.data(Qt.ItemDataRole.UserRole)
        if path and os.path.isdir(path):
            return path, self.row(item)
        return None, -1

    @staticmethod
    def _first_source(event) -> str | None:
        for url in event.mimeData().urls():
            if url.isLocalFile() and url.toLocalFile():
                return url.toLocalFile()
        return None

    def _operation_for(self, event, dest: str) -> TransferOp:
        source = self._first_source(event)
        cross = bool(source) and not same_device(source, dest)
        return operation_for_modifiers(event.modifiers(), cross_device=cross)

    def _set_drop_row(self, row: int, operation: TransferOp) -> None:
        if row == self._drop_row and operation == self._drop_op:
            return
        self._drop_row = row
        self._drop_op = operation
        self.viewport().update()

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if not event.mimeData().hasUrls():
            super().dragMoveEvent(event)
            return
        dest, row = self._dest_for_pos(event.position().toPoint())
        if dest is None:
            self._set_drop_row(-1, TransferOp.MOVE)
            event.ignore()
            return
        operation = self._operation_for(event, dest)
        event.setDropAction(_drop_action_for(operation))
        self._set_drop_row(row, operation)
        event.accept()

    def dragLeaveEvent(self, event) -> None:
        self._set_drop_row(-1, TransferOp.MOVE)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:
        if not event.mimeData().hasUrls():
            super().dropEvent(event)
            return
        dest, _row = self._dest_for_pos(event.position().toPoint())
        self._set_drop_row(-1, TransferOp.MOVE)
        if dest is None:
            event.ignore()
            return
        sources = [
            url.toLocalFile()
            for url in event.mimeData().urls()
            if url.isLocalFile() and url.toLocalFile()
        ]
        if not sources:
            event.ignore()
            return
        operation = self._operation_for(event, dest)
        event.setDropAction(_drop_action_for(operation))
        event.acceptProposedAction()
        self.filesDropped.emit(sources, dest, operation.value)


class _FavoritesList(_SidebarDropList):
    """Favorites list: drag to reorder, Trash pinned at top, files droppable."""

    favoritesReordered = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDragEnabled(True)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)

    @staticmethod
    def _is_internal_item_drag(event) -> bool:
        return event.mimeData().hasFormat(
            "application/x-qabstractitemmodeldatalist"
        )

    def dragEnterEvent(self, event) -> None:
        if self._is_internal_item_drag(event):
            if event.source() == self:
                event.accept()
            else:
                event.ignore()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if self._is_internal_item_drag(event):
            if event.source() != self:
                event.ignore()
                return
            pos = event.position().toPoint()
            item = self.itemAt(pos)
            row = self.row(item) if item is not None else self.count()
            if row <= 0:
                event.ignore()
                return
            event.accept()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        if event.mimeData().hasUrls() and not self._is_internal_item_drag(event):
            super().dropEvent(event)
            return
        if self._is_internal_item_drag(event) and event.source() == self:
            source_item = self.currentItem()
            if source_item is None:
                event.ignore()
                return
            source_row = self.row(source_item)
            if source_row <= 0:
                event.ignore()
                return
            pos = event.position().toPoint()
            target_item = self.itemAt(pos)
            target_row = (
                self.row(target_item) if target_item is not None else self.count()
            )
            if target_row <= 0:
                target_row = 1
            item = self.takeItem(source_row)
            if target_row > source_row:
                target_row -= 1
            self.insertItem(target_row, item)
            self.setCurrentItem(item)
            event.acceptProposedAction()
            self.favoritesReordered.emit()
            return
        event.ignore()


class Sidebar(QWidget):
    pathSelected = pyqtSignal(str)
    addFavoriteRequested = pyqtSignal(str, str)
    openInNewPaneRequested = pyqtSignal(str)
    removeFavoriteRequested = pyqtSignal(str)
    filesDropped = pyqtSignal(list, str, str)
    emptyTrashRequested = pyqtSignal()

    def __init__(
        self,
        bookmark_store: BookmarkStore,
        mount_service: MountService,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._bookmark_store = bookmark_store
        self._mount_service = mount_service
        self.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 8, 4, 8)
        layout.setSpacing(4)

        fav_label = QLabel("Favorites")
        fav_label.setObjectName("sidebarSectionLabel")
        layout.addWidget(fav_label)

        self._favorites = _FavoritesList()
        self._favorites.setIconSize(QSize(16, 16))
        self._favorites.setObjectName("sidebarList")
        self._favorites.itemClicked.connect(self._on_item_clicked)
        self._favorites.filesDropped.connect(self.filesDropped)
        self._favorites.favoritesReordered.connect(self._save_favorite_order)
        self._favorites.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self._favorites.customContextMenuRequested.connect(
            self._show_favorite_context_menu
        )
        layout.addWidget(self._favorites, stretch=2)

        self._volumes_toggle = QToolButton()
        self._volumes_toggle.setObjectName("sidebarSectionToggle")
        self._volumes_toggle.setText("▸ Volumes")
        self._volumes_toggle.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextOnly
        )
        self._volumes_toggle.setCheckable(True)
        self._volumes_toggle.setChecked(False)
        self._volumes_toggle.setAutoRaise(True)
        self._volumes_toggle.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self._volumes_toggle.toggled.connect(self._set_volumes_visible)
        layout.addWidget(self._volumes_toggle)

        self._volumes = _SidebarDropList()
        self._volumes.setIconSize(QSize(16, 16))
        self._volumes.setObjectName("sidebarList")
        self._volumes.setVisible(False)
        self._volumes.itemClicked.connect(self._on_item_clicked)
        self._volumes.filesDropped.connect(self.filesDropped)
        self._volumes.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self._volumes.customContextMenuRequested.connect(
            self._show_volume_context_menu
        )
        layout.addWidget(self._volumes, stretch=1)

        self.reload()

    def preferred_width(self) -> int:
        """Width to show favorite names without clipping (volumes ignored)."""
        fm = QFontMetrics(self._favorites.font())
        names = [
            bookmark.name
            for bookmark in self._bookmark_store.all_bookmarks()
        ]
        if not names:
            names = ["Favorites"]
        text_width = max(fm.horizontalAdvance(name) for name in names)
        # Layout margins, item padding, optional network icon, small buffer.
        chrome = 52
        return max(88, min(420, text_width + chrome))

    def reload(self) -> None:
        self._reload_favorites()
        self._reload_volumes()

    def _network_icon(self):
        return self.style().standardIcon(QStyle.StandardPixmap.SP_DriveNetIcon)

    def _local_volume_icon(self):
        return self.style().standardIcon(QStyle.StandardPixmap.SP_DriveHDIcon)

    def _reload_favorites(self) -> None:
        self._favorites.clear()
        _ensure_trash()
        trash_item = QListWidgetItem("Trash")
        trash_item.setData(Qt.ItemDataRole.UserRole, trash_path())
        trash_item.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon)
        )
        trash_item.setFlags(
            Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        )
        self._favorites.addItem(trash_item)
        for bookmark in self._bookmark_store.all_bookmarks():
            if not os.path.isdir(bookmark.path):
                continue
            item = QListWidgetItem(bookmark.name)
            item.setData(Qt.ItemDataRole.UserRole, bookmark.path)
            if self._mount_service.is_network_path(bookmark.path):
                item.setIcon(self._network_icon())
            self._favorites.addItem(item)

    def _reload_volumes(self) -> None:
        self._volumes.clear()
        for mount in self._mount_service.volume_mounts():
            if not os.path.isdir(mount.mount_point):
                continue
            item = QListWidgetItem(self._volume_label(mount))
            item.setData(Qt.ItemDataRole.UserRole, mount.mount_point)
            if mount.is_network:
                item.setIcon(self._network_icon())
            else:
                item.setIcon(self._local_volume_icon())
            self._volumes.addItem(item)

    @staticmethod
    def _volume_label(mount: Mount) -> str:
        return bookmark_name_for_path(mount.mount_point)

    def _set_volumes_visible(self, expanded: bool) -> None:
        self._volumes.setVisible(expanded)
        self._volumes_toggle.setText(
            "▾ Volumes" if expanded else "▸ Volumes"
        )

    def _show_favorite_context_menu(self, pos) -> None:
        item = self._favorites.itemAt(pos)
        if item is None:
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        if not path:
            return

        menu = QMenu(self)
        open_action = QAction("Open", self)
        open_action.triggered.connect(
            lambda: self.pathSelected.emit(path)
        )
        menu.addAction(open_action)

        new_pane_action = QAction("Open in New Pane", self)
        new_pane_action.triggered.connect(
            lambda: self.openInNewPaneRequested.emit(path)
        )
        menu.addAction(new_pane_action)

        if is_trash_directory(path):
            menu.addSeparator()
            empty_action = QAction("Empty Trash", self)
            empty_action.setEnabled(trash_count() > 0)
            empty_action.triggered.connect(self.emptyTrashRequested.emit)
            menu.addAction(empty_action)
        else:
            menu.addSeparator()
            remove_action = QAction("Remove from Favorites", self)
            remove_action.setEnabled(self._bookmark_store.is_removable(path))
            remove_action.triggered.connect(
                lambda: self.removeFavoriteRequested.emit(path)
            )
            menu.addAction(remove_action)

        menu.exec(self._favorites.mapToGlobal(pos))

    def _show_volume_context_menu(self, pos) -> None:
        item = self._volumes.itemAt(pos)
        if item is None:
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        if not path:
            return

        menu = QMenu(self)
        open_action = QAction("Open", self)
        open_action.triggered.connect(
            lambda: self.pathSelected.emit(path)
        )
        menu.addAction(open_action)

        favorite_action = QAction("Add to Favorites", self)
        favorite_action.triggered.connect(
            lambda: self._add_volume_to_favorites(path)
        )
        menu.addAction(favorite_action)

        menu.addSeparator()

        eject_action = QAction("Eject", self)
        eject_action.triggered.connect(lambda: self._eject_volume(path))
        menu.addAction(eject_action)

        menu.exec(self._volumes.mapToGlobal(pos))

    def _eject_volume(self, path: str) -> None:
        import subprocess

        try:
            subprocess.run(
                ["gio", "mount", "-u", path],
                check=False,
                timeout=10,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            try:
                subprocess.run(
                    ["udisksctl", "unmount", "-b", path],
                    check=False,
                    timeout=10,
                )
            except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
                pass
        self._mount_service.reload(force=True)
        self.reload()

    def _add_volume_to_favorites(self, path: str) -> None:
        name = bookmark_name_for_path(path)
        self.addFavoriteRequested.emit(name, path)

    def _save_favorite_order(self) -> None:
        paths: list[str] = []
        for row in range(1, self._favorites.count()):
            item = self._favorites.item(row)
            if item is None:
                continue
            path = item.data(Qt.ItemDataRole.UserRole)
            if path:
                paths.append(path)
        self._bookmark_store.reorder(paths)

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            self.pathSelected.emit(path)
