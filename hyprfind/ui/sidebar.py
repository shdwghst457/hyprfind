"""Sidebar with favorites and mounted volumes."""

from __future__ import annotations

import os

from PyQt6.QtCore import QPoint, QRect, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QFontMetrics, QPen, QPolygon
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QSizePolicy,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from hyprfind.core.bookmarks import BookmarkStore
from hyprfind.core.file_ops import TransferOp
from hyprfind.core.mounts import MountService
from hyprfind.core.trash import (
    _ensure_trash,
    is_trash_directory,
    trash_count,
    trash_path,
)
from hyprfind.core.volumes import Volume, VolumeService
from hyprfind.ui.icons import folder_icon, trash_icon, volume_icon
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
        # Finder never scrolls its sidebar sideways; long names elide instead.
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setFrameShape(QListWidget.Shape.NoFrame)
        self.setUniformItemSizes(True)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

    def sizeHint(self) -> QSize:
        """Hug the rows so stacked sections sit adjacent, as Finder's do."""
        base = super().sizeHint()
        rows = self.count()
        if rows == 0:
            return QSize(base.width(), 0)
        row_height = self.sizeHintForRow(0)
        if row_height <= 0:
            return base
        return QSize(base.width(), rows * row_height + 4)

    def minimumSizeHint(self) -> QSize:
        # Allow shrink-and-scroll when the window is too short for every row.
        return QSize(super().minimumSizeHint().width(), 0)

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


EJECT_HIT_WIDTH = 26
_VOLUME_ROLE = int(Qt.ItemDataRole.UserRole) + 1


def _draw_eject_glyph(painter, rect: QRect, color: QColor) -> None:
    """Finder-style eject mark: a small triangle above a short bar."""
    painter.save()
    painter.setRenderHint(painter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)

    width = 9
    center_x = rect.center().x()
    top = rect.center().y() - 5
    triangle = QPolygon(
        [
            QPoint(center_x, top),
            QPoint(center_x - width // 2, top + 5),
            QPoint(center_x + width // 2, top + 5),
        ]
    )
    painter.drawPolygon(triangle)
    painter.setPen(QPen(color, 1.6))
    bar_y = top + 8
    painter.drawLine(center_x - width // 2, bar_y, center_x + width // 2, bar_y)
    painter.restore()


class _VolumeRowDelegate(_SidebarDropDelegate):
    """Adds an eject affordance to volume rows that support it."""

    def __init__(self, view: "_VolumesList", parent=None) -> None:
        super().__init__(view, parent)
        self._volume_view = view

    def paint(self, painter, option, index) -> None:
        volume: Volume | None = index.data(_VOLUME_ROLE)
        ejectable = volume is not None and volume.is_ejectable

        if ejectable:
            # Shrink the text area so long share names never sit under the icon.
            option.rect = option.rect.adjusted(0, 0, -EJECT_HIT_WIDTH, 0)
            super().paint(painter, option, index)
            option.rect = option.rect.adjusted(0, 0, EJECT_HIT_WIDTH, 0)
        else:
            super().paint(painter, option, index)

        if not ejectable:
            return

        hovered = self._volume_view.hovered_row() == index.row()
        color = QColor("#e8e8e8") if hovered else QColor("#7c7c7c")
        _draw_eject_glyph(painter, self._volume_view.eject_rect(option.rect), color)


class _VolumesList(_SidebarDropList):
    """Drives and shares, each with an inline eject button."""

    ejectRequested = pyqtSignal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._hovered_row = -1
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.setItemDelegate(_VolumeRowDelegate(self, self))

    def hovered_row(self) -> int:
        return self._hovered_row

    @staticmethod
    def eject_rect(row_rect: QRect) -> QRect:
        return QRect(
            row_rect.right() - EJECT_HIT_WIDTH,
            row_rect.top(),
            EJECT_HIT_WIDTH,
            row_rect.height(),
        )

    def _eject_volume_at(self, pos: QPoint) -> Volume | None:
        item = self.itemAt(pos)
        if item is None:
            return None
        volume = item.data(_VOLUME_ROLE)
        if not isinstance(volume, Volume) or not volume.is_ejectable:
            return None
        if not self.eject_rect(self.visualItemRect(item)).contains(pos):
            return None
        return volume

    def mouseMoveEvent(self, event) -> None:
        item = self.itemAt(event.pos())
        row = self.row(item) if item is not None else -1
        if row != self._hovered_row:
            self._hovered_row = row
            self.viewport().update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        if self._hovered_row != -1:
            self._hovered_row = -1
            self.viewport().update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            volume = self._eject_volume_at(event.pos())
            if volume is not None:
                # Consume the click so the row is not also opened.
                self.ejectRequested.emit(volume)
                event.accept()
                return
        super().mousePressEvent(event)


class Sidebar(QWidget):
    pathSelected = pyqtSignal(str)
    statusMessage = pyqtSignal(str)
    addFavoriteRequested = pyqtSignal(str, str)
    openInNewPaneRequested = pyqtSignal(str)
    openInNewTabRequested = pyqtSignal(str)
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
        self._volume_service = VolumeService(mount_service)
        self.setObjectName("sidebar")
        self.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 10, 6, 8)
        layout.setSpacing(2)

        self._favorites_toggle = self._make_section_toggle("Favorites")
        self._favorites_toggle.toggled.connect(self._set_favorites_visible)
        layout.addWidget(self._favorites_toggle)

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
        layout.addWidget(self._favorites)

        self._volumes_toggle = self._make_section_toggle("Locations")
        self._volumes_toggle.toggled.connect(self._set_volumes_visible)
        layout.addWidget(self._volumes_toggle)

        self._volumes = _VolumesList()
        self._volumes.setIconSize(QSize(16, 16))
        self._volumes.setObjectName("sidebarList")
        self._volumes.itemClicked.connect(self._on_volume_clicked)
        self._volumes.filesDropped.connect(self.filesDropped)
        self._volumes.ejectRequested.connect(self._eject_volume)
        self._volumes.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self._volumes.customContextMenuRequested.connect(
            self._show_volume_context_menu
        )
        layout.addWidget(self._volumes)
        layout.addStretch(1)
        self._set_volumes_visible(True)

        # Nothing on a bare Hyprland session tells us a USB disk was plugged in,
        # so poll for device changes at a rate that stays invisible in top(1).
        self._device_timer = QTimer(self)
        self._device_timer.setInterval(4000)
        self._device_timer.timeout.connect(self._refresh_volumes_if_changed)
        self._device_timer.start()
        self._volume_signature: tuple = ()

        self.reload()

    def _make_section_toggle(self, title: str) -> QPushButton:
        # QPushButton rather than QToolButton: only the former honours the
        # stylesheet's text-align, and these headers must sit flush left.
        button = QPushButton()
        button.setObjectName("sidebarSectionToggle")
        button.setProperty("sectionTitle", title)
        button.setCheckable(True)
        button.setChecked(True)
        button.setFlat(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        button.setText(f"▾  {title}")
        return button

    @staticmethod
    def _update_section_toggle(button: QPushButton, expanded: bool) -> None:
        title = button.property("sectionTitle") or ""
        button.setText(f"{'▾' if expanded else '▸'}  {title}")

    def _set_favorites_visible(self, expanded: bool) -> None:
        self._favorites.setVisible(expanded)
        self._update_section_toggle(self._favorites_toggle, expanded)

    def preferred_width(self) -> int:
        """Width that shows favorite and volume names without clipping."""
        fm = QFontMetrics(self._favorites.font())
        names = [bookmark.name for bookmark in self._bookmark_store.all_bookmarks()]
        text_width = max(
            (fm.horizontalAdvance(name) for name in names or ["Favorites"]),
            default=0,
        )

        # Volume rows also reserve room for the inline eject button.
        for row in range(self._volumes.count()):
            item = self._volumes.item(row)
            if item is None:
                continue
            width = fm.horizontalAdvance(item.text()) + EJECT_HIT_WIDTH
            text_width = max(text_width, width)

        # Layout margins, item padding, icon, small buffer.
        chrome = 56
        return max(150, min(420, text_width + chrome))

    def reload(self) -> None:
        self._reload_favorites()
        self._reload_volumes()

    def _reload_favorites(self) -> None:
        self._favorites.clear()
        _ensure_trash()
        trash_item = QListWidgetItem("Trash")
        trash_item.setData(Qt.ItemDataRole.UserRole, trash_path())
        trash_item.setIcon(trash_icon(full=trash_count() > 0))
        trash_item.setFlags(
            Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        )
        self._favorites.addItem(trash_item)
        for bookmark in self._bookmark_store.all_bookmarks():
            if not os.path.isdir(bookmark.path):
                continue
            item = QListWidgetItem(bookmark.name)
            item.setData(Qt.ItemDataRole.UserRole, bookmark.path)
            item.setIcon(
                folder_icon(
                    bookmark.path,
                    is_network=self._mount_service.is_network_path(bookmark.path),
                )
            )
            self._favorites.addItem(item)
        self._favorites.updateGeometry()

    @staticmethod
    def _volume_signature_of(volumes: list[Volume]) -> tuple:
        return tuple((v.device, v.mount_point, v.name) for v in volumes)

    def _reload_volumes(self) -> None:
        volumes = self._volume_service.volumes()
        self._volume_signature = self._volume_signature_of(volumes)
        self._volumes.clear()

        for volume in volumes:
            if volume.is_mounted and not os.path.isdir(volume.mount_point or ""):
                continue
            item = QListWidgetItem(volume.name)
            item.setIcon(volume_icon(volume.kind))
            item.setData(Qt.ItemDataRole.UserRole, volume.mount_point or "")
            item.setData(_VOLUME_ROLE, volume)
            if volume.is_mounted:
                item.setToolTip(f"{volume.name} — {volume.mount_point}")
            else:
                # Attached but unmounted: dim it and mount on first click.
                item.setForeground(QColor("#8a8a8a"))
                item.setToolTip(f"{volume.name} — click to mount ({volume.device})")
            self._volumes.addItem(item)

        self._volumes.updateGeometry()
        self._volumes_toggle.setEnabled(bool(volumes))

    def _refresh_volumes_if_changed(self) -> None:
        if not self.isVisible():
            return
        volumes = self._volume_service.volumes()
        if self._volume_signature_of(volumes) == self._volume_signature:
            return
        self._reload_volumes()

    def _set_volumes_visible(self, expanded: bool) -> None:
        self._volumes.setVisible(expanded)
        self._update_section_toggle(self._volumes_toggle, expanded)

    def _on_volume_clicked(self, item: QListWidgetItem) -> None:
        volume = item.data(_VOLUME_ROLE)
        if not isinstance(volume, Volume):
            self._on_item_clicked(item)
            return
        if volume.is_mounted:
            self.pathSelected.emit(volume.mount_point)
            return

        self.statusMessage.emit(f"Mounting {volume.name}…")
        mount_point, error = self._volume_service.mount(volume)
        self._reload_volumes()
        if error:
            self.statusMessage.emit(error)
            return
        if mount_point:
            self.statusMessage.emit(f"Mounted {volume.name}")
            self.pathSelected.emit(mount_point)

    def _eject_volume(self, volume: Volume) -> None:
        name = volume.name
        error = self._volume_service.eject(volume)
        self._mount_service.reload(force=True)
        self._reload_volumes()
        self.statusMessage.emit(error if error else f"Ejected {name}")

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

        new_tab_action = QAction("Open in New Tab", self)
        new_tab_action.triggered.connect(
            lambda: self.openInNewTabRequested.emit(path)
        )
        menu.addAction(new_tab_action)

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
        volume = item.data(_VOLUME_ROLE)
        if not isinstance(volume, Volume):
            return

        menu = QMenu(self)

        if volume.is_mounted:
            path = volume.mount_point
            open_action = QAction("Open", self)
            open_action.triggered.connect(lambda: self.pathSelected.emit(path))
            menu.addAction(open_action)

            new_tab_action = QAction("Open in New Tab", self)
            new_tab_action.triggered.connect(
                lambda: self.openInNewTabRequested.emit(path)
            )
            menu.addAction(new_tab_action)

            new_pane_action = QAction("Open in New Pane", self)
            new_pane_action.triggered.connect(
                lambda: self.openInNewPaneRequested.emit(path)
            )
            menu.addAction(new_pane_action)

            favorite_action = QAction("Add to Favorites", self)
            favorite_action.triggered.connect(
                lambda: self._add_volume_to_favorites(path)
            )
            menu.addAction(favorite_action)

            if volume.is_ejectable:
                menu.addSeparator()
                label = "Disconnect" if volume.is_network else "Eject"
                eject_action = QAction(label, self)
                eject_action.triggered.connect(lambda: self._eject_volume(volume))
                menu.addAction(eject_action)
        else:
            mount_action = QAction("Mount", self)
            mount_action.triggered.connect(lambda: self._on_volume_clicked(item))
            menu.addAction(mount_action)

        menu.addSeparator()
        refresh_action = QAction("Refresh Devices", self)
        refresh_action.triggered.connect(self._force_refresh_volumes)
        menu.addAction(refresh_action)

        menu.exec(self._volumes.mapToGlobal(pos))

    def _force_refresh_volumes(self) -> None:
        self._mount_service.reload(force=True)
        self._reload_volumes()

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
