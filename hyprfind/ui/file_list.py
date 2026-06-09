"""QTreeView wrapper for filesystem listing."""

from __future__ import annotations

import logging
import mimetypes
import os
import tempfile
import time

from PyQt6.QtCore import (
    QMimeData,
    QModelIndex,
    QPersistentModelIndex,
    QRect,
    QSize,
    Qt,
    QTimer,
    QUrl,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QAction,
    QColor,
    QDrag,
    QDesktopServices,
    QPainter,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHeaderView,
    QMenu,
    QMessageBox,
    QSizePolicy,
    QStyle,
    QTreeView,
)

from hyprfind.core.clipboard import FileClipboard
from hyprfind.core.compress import compress_items
from hyprfind.core.file_ops import ConflictChoice, TransferOp, transfer_items, unique_directory
from hyprfind.core.open_with import apps_for_mime, launch_app
from hyprfind.core.trash import (
    is_trash_directory,
    move_paths_to_trash,
    restore_from_trash,
    trash_count,
)
from hyprfind.core.undo import MkdirCommand, MoveCommand, TrashCommand, UndoStack
from hyprfind.utils.paths import bookmark_name_for_path
from hyprfind.core.fs_columns import DATE_MODIFIED, NAME, SIZE, TYPE
from hyprfind.core.model import HyprFileSystemModel
from hyprfind.core.sort_proxy import FileSortProxyModel
from hyprfind.ui.conflict_dialog import ConflictAction, ConflictDialog
from hyprfind.ui.date_delegate import DateModifiedDelegate
from hyprfind.ui.drag_support import operation_for_modifiers, status_verb
from hyprfind.ui.info_panel import InfoPanel
from hyprfind.ui.list_delegate import DropHighlightDelegate

# How long the cursor must rest over a closed folder before it springs open.
SPRING_LOAD_DELAY_MS = 650
# Cadence of the reconcile loop that performs spring expand/collapse safely.
SPRING_RECONCILE_INTERVAL_MS = 70


def _build_spring_logger() -> logging.Logger:
    """Verbose spring-load logger (opt-in).

    Off by default. Set ``HYPRFIND_SPRING_LOG=1`` to enable; logs then go to
    both stderr and ``$HYPRFIND_SPRING_LOG_FILE`` (default:
    <tmp>/hyprfind-spring.log). Each record is flushed immediately so the
    trailing lines survive a hard crash such as a SIGSEGV/address-boundary
    error — handy if a drag-related crash ever resurfaces.
    """
    logger = logging.getLogger("hyprfind.spring")
    if getattr(logger, "_hyprfind_configured", False):
        return logger
    logger._hyprfind_configured = True  # type: ignore[attr-defined]
    enabled = os.environ.get("HYPRFIND_SPRING_LOG", "") not in ("", "0")
    logger.setLevel(logging.DEBUG if enabled else logging.CRITICAL)
    logger.propagate = False
    if not enabled:
        return logger
    fmt = logging.Formatter("%(asctime)s.%(msecs)03d %(message)s", "%H:%M:%S")
    log_path = os.environ.get(
        "HYPRFIND_SPRING_LOG_FILE",
        os.path.join(tempfile.gettempdir(), "hyprfind-spring.log"),
    )
    try:
        file_handler = logging.FileHandler(log_path, mode="w")
        file_handler.setFormatter(fmt)
        logger.addHandler(file_handler)
    except OSError:
        pass
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(fmt)
    logger.addHandler(stream_handler)
    logger.info("=== spring log started (pid=%s) -> %s", os.getpid(), log_path)
    return logger


_spring_log = _build_spring_logger()


class FileListView(QTreeView):
    pathActivated = pyqtSignal(str)
    openParentRequested = pyqtSignal()
    previewRequested = pyqtSignal(str)
    addFavoriteRequested = pyqtSignal(str, str)
    statusMessage = pyqtSignal(str)
    filesTransferred = pyqtSignal(str, str)
    dragSourceFinished = pyqtSignal()
    selectionChangedSignal = pyqtSignal()
    undoStateChanged = pyqtSignal()
    emptyTrashRequested = pyqtSignal()

    def __init__(self, model: HyprFileSystemModel, parent=None) -> None:
        super().__init__(parent)
        self._model = model
        self._proxy = FileSortProxyModel(self)
        self._proxy.setSourceModel(model)
        self._sort_column = NAME
        self._sort_order = Qt.SortOrder.AscendingOrder
        self._columns_initialized = False
        # Held across drag events and dereferenced during paint, so it MUST be
        # persistent: a plain QModelIndex dangles when a spring expand inserts
        # rows into the proxy, and the next paint would crash.
        self._drop_target_index = QPersistentModelIndex()
        # --- Spring-loaded folder state (see the "Spring-loaded folders" section) ---
        # All structural mutations happen in _reconcile_spring on a timer tick,
        # never directly inside a drag event, and at most one per tick.
        self._drag_active = False
        self._drag_op: TransferOp = TransferOp.MOVE
        self._device_cache: dict[str, int | None] = {}
        self._drag_hover_path: str | None = None
        self._hover_changed_at = 0.0
        self._pre_expanded: set[str] = set()
        self._spring_opened: list[str] = []
        self._pending_collapse: list[str] = []
        self._pre_drag_animated = True
        self._mutating = False
        self._reconcile_timer = QTimer(self)
        self._reconcile_timer.setInterval(SPRING_RECONCILE_INTERVAL_MS)
        self._reconcile_timer.timeout.connect(self._reconcile_spring)
        self.setModel(self._proxy)
        # We drive spring-loading ourselves; disable Qt's native auto-expand.
        self.setAutoExpandDelay(-1)
        self.expanded.connect(lambda: self.viewport().update())
        self.collapsed.connect(lambda: self.viewport().update())
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setRootIsDecorated(True)
        self.setItemsExpandable(True)
        self.setExpandsOnDoubleClick(False)
        self.setIndentation(12)
        self.setAnimated(True)
        self.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.setIconSize(QSize(16, 16))
        self.setAlternatingRowColors(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setSortingEnabled(False)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setDragDropOverwriteMode(False)
        self.setUniformRowHeights(True)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(False)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self.doubleClicked.connect(self._on_double_click)
        self._list_delegate = DropHighlightDelegate(self, self)
        self._date_delegate = DateModifiedDelegate(self._proxy, self, self)
        self.setItemDelegate(self._list_delegate)
        self.setItemDelegateForColumn(DATE_MODIFIED, self._date_delegate)
        self.header().sectionClicked.connect(self._on_header_clicked)
        self._apply_sort()
        self._undo_stack: UndoStack | None = None
        self._confirm_permanent_delete = True
        self.selectionModel().selectionChanged.connect(
            lambda *_: self.selectionChangedSignal.emit()
        )

    def set_undo_stack(self, stack: UndoStack) -> None:
        self._undo_stack = stack

    def set_confirm_permanent_delete(self, confirm: bool) -> None:
        self._confirm_permanent_delete = confirm

    def _resolve_conflict(self, source: str, target: str) -> ConflictChoice:
        dialog = ConflictDialog(source, target, self)
        if dialog.exec() != ConflictDialog.DialogCode.Accepted:
            return "stop"
        mapping = {
            ConflictAction.REPLACE: "replace",
            ConflictAction.KEEP_BOTH: "keep_both",
            ConflictAction.STOP: "stop",
            ConflictAction.SKIP: "skip",
        }
        return mapping.get(dialog.action, "stop")

    def _intelligent_column_widths(self) -> dict[int, int]:
        """Proportional starting widths; Name flexes to fill leftover space."""
        view_width = max(self.viewport().width(), self.width(), 640)
        date_w = min(240, max(168, int(view_width * 0.22)))
        size_w = min(116, max(96, int(view_width * 0.13)))
        type_w = min(100, max(84, int(view_width * 0.09)))
        target_meta = int(view_width * 0.44)
        meta_total = date_w + size_w + type_w
        if meta_total < target_meta:
            scale = target_meta / meta_total
            date_w = min(240, max(168, int(date_w * scale)))
            size_w = min(116, max(96, int(size_w * scale)))
            type_w = min(100, max(84, int(type_w * scale)))
        name_w = max(int(view_width * 0.52), view_width - date_w - size_w - type_w)
        return {
            NAME: name_w,
            DATE_MODIFIED: date_w,
            SIZE: size_w,
            TYPE: type_w,
        }

    def _flex_name_column(self) -> None:
        """Keep Name as the flexible column that fills the viewport."""
        header = self.header()
        others = sum(
            header.sectionSize(column)
            for column in (DATE_MODIFIED, SIZE, TYPE)
        )
        name_w = max(header.minimumSectionSize(), self.viewport().width() - others)
        if header.sectionSize(NAME) == name_w:
            return
        header.blockSignals(True)
        header.resizeSection(NAME, name_w)
        header.blockSignals(False)

    def _on_section_resized(self, logical_index: int, _old: int, _new: int) -> None:
        # Dragging a metadata divider adjusts Name; dragging Name stays put.
        if logical_index != NAME:
            self._flex_name_column()

    def _configure_columns(self) -> None:
        if self._columns_initialized:
            return
        self._columns_initialized = True

        header = self.header()
        header.setSectionsClickable(True)
        header.setSortIndicatorShown(True)
        header.setHighlightSections(True)
        header.setSectionsMovable(True)
        header.setCascadingSectionResizes(False)
        header.setStretchLastSection(False)
        if hasattr(header, "setFirstSectionMovable"):
            header.setFirstSectionMovable(True)
        header.setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        header.setMinimumSectionSize(44)

        # All columns draggable; Name flexes when the pane or other columns change.
        desired_order = (NAME, DATE_MODIFIED, SIZE, TYPE)
        for visual, logical in enumerate(desired_order):
            current = header.visualIndex(logical)
            if current >= 0 and current != visual:
                header.moveSection(current, visual)

        for column, width in self._intelligent_column_widths().items():
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
            header.resizeSection(column, width)

        self._flex_name_column()
        header.sectionResized.connect(self._on_section_resized)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._columns_initialized:
            QTimer.singleShot(0, self._try_configure_columns)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._columns_initialized:
            self._flex_name_column()

    def _try_configure_columns(self) -> None:
        if self._columns_initialized:
            return
        if max(self.viewport().width(), self.width()) < 240:
            QTimer.singleShot(50, self._try_configure_columns)
            return
        self._configure_columns()

    def _source_index(self, index: QModelIndex) -> QModelIndex:
        if not index.isValid():
            return QModelIndex()
        return self._proxy.mapToSource(index)

    def _proxy_index(self, source_index: QModelIndex) -> QModelIndex:
        if not source_index.isValid():
            return QModelIndex()
        return self._proxy.mapFromSource(source_index)

    def _apply_directory_root(self, proxy_index: QModelIndex, normalized: str) -> None:
        self.collapseAll()
        self.setRootIndex(proxy_index)
        self._apply_sort()
        self._model.set_active_directory(normalized)

    def set_current_directory(self, path: str) -> None:
        normalized = os.path.abspath(os.path.expanduser(path))
        if not os.path.isdir(normalized):
            return
        self._model.notify_user_activity()
        source_index = self._model.resolve_directory_index(normalized)
        proxy_index = self._proxy_index(source_index)
        if proxy_index.isValid():
            self._apply_directory_root(proxy_index, normalized)
            if is_trash_directory(normalized):
                self._verify_trash_root(normalized)
            return

        def _retry(loaded_path: str = "") -> None:
            if loaded_path and os.path.normpath(loaded_path) not in (
                os.path.normpath(normalized),
                os.path.normpath(os.path.dirname(normalized)),
            ):
                return
            source = self._model.resolve_directory_index(normalized)
            proxy = self._proxy_index(source)
            if not proxy.isValid():
                return
            try:
                self._model.directoryLoaded.disconnect(_retry)
            except TypeError:
                pass
            self._apply_directory_root(proxy, normalized)
            if is_trash_directory(normalized):
                self._verify_trash_root(normalized)

        try:
            self._model.directoryLoaded.disconnect(_retry)
        except TypeError:
            pass
        self._model.directoryLoaded.connect(_retry)
        QTimer.singleShot(0, _retry)

    def _verify_trash_root(self, expected: str) -> None:
        """Ensure the list root is the trash folder, not a stale directory."""
        if os.path.normpath(self.current_directory()) == os.path.normpath(expected):
            return

        def _fix() -> None:
            if os.path.normpath(self.current_directory()) == os.path.normpath(expected):
                return
            source = self._model.resolve_directory_index(expected)
            proxy = self._proxy_index(source)
            if proxy.isValid():
                self._apply_directory_root(proxy, expected)

        QTimer.singleShot(0, _fix)
        QTimer.singleShot(100, _fix)

    def _notify_user_activity(self) -> None:
        self._model.notify_user_activity()

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        self._notify_user_activity()
        super().scrollContentsBy(dx, dy)

    def wheelEvent(self, event) -> None:
        self._notify_user_activity()
        super().wheelEvent(event)

    def mousePressEvent(self, event) -> None:
        self._notify_user_activity()
        super().mousePressEvent(event)

    def current_directory(self) -> str:
        root = self._source_index(self.rootIndex())
        if root.isValid():
            return self._model.filePath(root)
        return ""

    def selected_paths(self) -> list[str]:
        paths: list[str] = []
        seen: set[str] = set()
        for index in self.selectedIndexes():
            if index.column() != 0:
                continue
            source = self._source_index(index)
            path = self._model.filePath(source)
            if path and path not in seen:
                seen.add(path)
                paths.append(path)
        return paths

    def selected_path(self) -> str | None:
        paths = self.selected_paths()
        return paths[0] if paths else None

    def keyPressEvent(self, event) -> None:
        self._notify_user_activity()
        key = event.key()
        mods = event.modifiers()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        alt = bool(mods & Qt.KeyboardModifier.AltModifier)
        if key == Qt.Key.Key_N and ctrl:
            if alt:
                self._new_folder_with_selection()
            elif shift:
                self._new_folder()
            else:
                super().keyPressEvent(event)
                return
            event.accept()
            return
        if key == Qt.Key.Key_C and ctrl and not shift:
            self._copy_selection()
            event.accept()
            return
        if key == Qt.Key.Key_X and ctrl:
            self._cut_selection()
            event.accept()
            return
        if key == Qt.Key.Key_V and ctrl:
            self._paste()
            event.accept()
            return
        if key == Qt.Key.Key_D and ctrl:
            self._duplicate_selection()
            event.accept()
            return
        if key == Qt.Key.Key_A and ctrl:
            self.selectAll()
            event.accept()
            return
        if key == Qt.Key.Key_F2:
            if len(self.selected_paths()) == 1:
                for index in self.selectedIndexes():
                    if index.column() == 0:
                        self._start_inline_rename(index)
                        break
            event.accept()
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self.state() == QAbstractItemView.State.EditingState:
                super().keyPressEvent(event)
                return
            for path in self.selected_paths():
                self._activate_path(path)
                break
            event.accept()
            return
        if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and shift:
            self._delete_permanent()
            event.accept()
            return
        if key in (Qt.Key.Key_Delete,):
            self._move_selection_to_trash()
            event.accept()
            return
        if key == Qt.Key.Key_Backspace:
            self.openParentRequested.emit()
            event.accept()
            return
        if key == Qt.Key.Key_Space:
            path = self.selected_path()
            if path:
                self.previewRequested.emit(path)
            event.accept()
            return
        if key == Qt.Key.Key_Right:
            index = self.currentIndex()
            source = self._source_index(index)
            if source.isValid() and self._model.isDir(source) and not self.isExpanded(index):
                self.expand(index)
                event.accept()
                return
        if key == Qt.Key.Key_Left:
            index = self.currentIndex()
            if index.isValid() and self.isExpanded(index):
                self.collapse(index)
                event.accept()
                return
        super().keyPressEvent(event)

    def _is_drop_target_row(self, index: QModelIndex) -> bool:
        target = self._drop_target_index
        if not target.isValid() or not index.isValid():
            return False
        return index.row() == target.row() and index.parent() == QModelIndex(
            target.parent()
        )

    def _is_spring_open_row(self, index: QModelIndex) -> bool:
        if not self._drag_active or not index.isValid():
            return False
        path = self._path_for_index(index)
        return bool(path and path in self._spring_opened)

    def _is_spring_hover_row(self, index: QModelIndex) -> bool:
        if not self._drag_active or not self._drag_hover_path:
            return False
        path = self._path_for_index(index)
        return bool(path and path == self._drag_hover_path)

    def _make_drag_pixmap(self, paths: list[str]) -> QPixmap:
        primary = os.path.basename(paths[0].rstrip(os.sep)) or paths[0]
        extra = len(paths) - 1
        label = primary if extra <= 0 else f"{primary}  +{extra}"

        is_dir = os.path.isdir(paths[0])
        icon = self.style().standardIcon(
            QStyle.StandardPixmap.SP_DirIcon
            if is_dir
            else QStyle.StandardPixmap.SP_FileIcon
        )

        metrics = self.fontMetrics()
        icon_size = 22
        text_width = metrics.horizontalAdvance(label)
        width = min(360, icon_size + text_width + 44)
        height = 38
        pixmap = QPixmap(width + 4, height + 4)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        shadow = QRect(4, 4, width, height)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 70))
        painter.drawRoundedRect(shadow, 10, 10)

        body = QRect(0, 0, width, height)
        painter.setBrush(QColor(48, 72, 104, 230))
        painter.drawRoundedRect(body, 10, 10)

        icon.paint(painter, QRect(10, 8, icon_size, icon_size))
        painter.setPen(QColor(255, 255, 255, 245))
        painter.drawText(icon_size + 16, 24, label)
        painter.end()
        return pixmap

    @staticmethod
    def _normalize_path(path: str) -> str:
        return os.path.normpath(os.path.abspath(os.path.expanduser(path)))

    def _name_index(self, index: QModelIndex) -> QModelIndex:
        if not index.isValid():
            return QModelIndex()
        if index.column() == 0:
            return index
        return index.siblingAtColumn(0)

    def _path_for_index(self, index: QModelIndex) -> str | None:
        name_index = self._name_index(index)
        if not name_index.isValid():
            return None
        source = self._source_index(name_index)
        if not source.isValid():
            return None
        return self._normalize_path(self._model.filePath(source))

    def _snapshot_expanded_paths(self) -> set[str]:
        paths: set[str] = set()

        def visit(parent: QModelIndex) -> None:
            rows = self.model().rowCount(parent)
            for row in range(rows):
                idx = self.model().index(row, 0, parent)
                if not idx.isValid():
                    continue
                if self.isExpanded(idx):
                    path = self._path_for_index(idx)
                    if path:
                        paths.add(path)
                    visit(idx)

        root = self.rootIndex()
        if root.isValid():
            visit(root)
        return paths

    # ------------------------------------------------------------------
    # Spring-loaded folders
    #
    # While a drag is in progress, resting the cursor over a closed folder
    # for SPRING_LOAD_DELAY_MS expands it in place. Moving on to a folder on
    # a different branch collapses the folders that were sprung open earlier,
    # while the ancestor chain being drilled into stays open. At drag end,
    # anything sprung open during the drag is collapsed back.
    #
    # Robustness rules (earlier revisions segfaulted by breaking these):
    #   * Every structural change goes through _reconcile_spring on a timer,
    #     never directly from a drag event handler, and at most one expand or
    #     collapse happens per tick — so tree mutations never nest.
    #   * Indices are always resolved fresh from a path via
    #     QFileSystemModel.index(); QModelIndex values are never cached across
    #     ticks and the proxy tree is never walked recursively.
    #   * No signal disconnects, no dynamicSortFilter toggling, no fetchMore
    #     busy-loops — the things that made prior versions crash.
    # ------------------------------------------------------------------

    def _is_path_ancestor_of(self, ancestor_path: str, descendant_path: str) -> bool:
        ancestor = self._normalize_path(ancestor_path)
        descendant = self._normalize_path(descendant_path)
        return descendant == ancestor or descendant.startswith(ancestor + os.sep)

    def _resolve_proxy_name_index(self, path: str) -> QModelIndex:
        """Map a filesystem path straight to its column-0 proxy index."""
        source = self._model.index(path)
        if not source.isValid():
            _spring_log.debug("    resolve FAIL (source invalid): %s", path)
            return QModelIndex()
        proxy = self._proxy.mapFromSource(source)
        if not proxy.isValid():
            _spring_log.debug("    resolve FAIL (proxy invalid): %s", path)
            return QModelIndex()
        return self._name_index(proxy)

    def _safe_set_expanded(self, path: str, expanded: bool) -> None:
        verb = "EXPAND" if expanded else "COLLAPSE"
        index = self._resolve_proxy_name_index(path)
        if not index.isValid():
            _spring_log.debug("  %s skip (no index): %s", verb, path)
            return
        if self.isExpanded(index) == expanded:
            _spring_log.debug("  %s skip (already %s): %s", verb, expanded, path)
            return
        if expanded:
            source = self._source_index(index)
            if not source.isValid() or not self._model.isDir(source):
                _spring_log.debug("  %s skip (not a dir): %s", verb, path)
                return
        _spring_log.debug(
            "  %s begin: %s (row=%s col=%s)",
            verb,
            path,
            index.row(),
            index.column(),
        )
        self._mutating = True
        self.setUpdatesEnabled(False)
        try:
            self.setExpanded(index, expanded)
        finally:
            self.setUpdatesEnabled(True)
            self._mutating = False
        _spring_log.debug("  %s done:  %s", verb, path)
        self.viewport().update()

    def _begin_drag_session(self) -> None:
        if self._drag_active:
            _spring_log.debug("begin_session SKIP (already active)")
            return
        self._pre_expanded = self._snapshot_expanded_paths()
        self._spring_opened = []
        self._pending_collapse = []
        self._drag_hover_path = None
        self._hover_changed_at = time.monotonic()
        self._mutating = False
        self._drag_active = True
        self._pre_drag_animated = self.isAnimated()
        self.setAnimated(False)
        self._reconcile_timer.start()
        _spring_log.debug(
            "BEGIN session dir=%s pre_expanded=%s",
            self.current_directory(),
            sorted(self._pre_expanded),
        )

    def _end_drag_session(self) -> None:
        if not self._drag_active:
            self._clear_drop_highlight()
            return
        _spring_log.debug("END session opened=%s", list(self._spring_opened))
        self._drag_active = False
        self._reconcile_timer.stop()
        # Collapse everything we sprang open (deepest first), leaving folders
        # the user had already expanded before the drag alone. This runs after
        # the drag's nested event loop has unwound, so a synchronous pass is
        # safe here.
        opened = sorted(
            self._spring_opened, key=lambda p: p.count(os.sep), reverse=True
        )
        self._spring_opened = []
        self._pending_collapse = []
        for path in opened:
            if path not in self._pre_expanded:
                self._safe_set_expanded(path, False)
        self.setAnimated(self._pre_drag_animated)
        self._pre_expanded = set()
        self._clear_drop_highlight()

    def end_foreign_drag_session(self) -> None:
        """Called on every pane when a drag started elsewhere finishes."""
        self._end_drag_session()

    def _queue_irrelevant_collapses(self, opening_path: str) -> None:
        """Schedule sprung folders off the opening folder's branch to close."""
        for path in self._spring_opened:
            if path == opening_path or self._is_path_ancestor_of(path, opening_path):
                continue  # ancestor chain we just drilled into stays open
            if path not in self._pending_collapse:
                self._pending_collapse.append(path)
        self._pending_collapse.sort(key=lambda p: p.count(os.sep), reverse=True)

    def _reconcile_spring(self) -> None:
        if not self._drag_active or self._mutating:
            return

        # 1) Service any pending sibling collapse first — one per tick.
        while self._pending_collapse:
            target = self._pending_collapse.pop(0)
            if target in self._spring_opened and target not in self._pre_expanded:
                _spring_log.debug("reconcile -> collapse sibling: %s", target)
                self._spring_opened.remove(target)
                self._safe_set_expanded(target, False)
                return

        # 2) Otherwise spring the hovered folder open once it has been stable.
        hover = self._drag_hover_path
        if not hover or hover in self._spring_opened or hover in self._pre_expanded:
            return
        if (time.monotonic() - self._hover_changed_at) * 1000 < SPRING_LOAD_DELAY_MS:
            return
        index = self._resolve_proxy_name_index(hover)
        if not index.isValid() or self.isExpanded(index):
            return
        source = self._source_index(index)
        if not source.isValid() or not self._model.isDir(source):
            return
        _spring_log.debug("reconcile -> spring open: %s", hover)
        self._spring_opened.append(hover)
        self._safe_set_expanded(hover, True)
        # Now that a new folder has opened, retire ones from other branches.
        self._queue_irrelevant_collapses(hover)
        if self._pending_collapse:
            _spring_log.debug("  queued collapses: %s", list(self._pending_collapse))

    def _clear_drop_highlight(self) -> None:
        self._drop_target_index = QPersistentModelIndex()
        self._drag_hover_path = None
        self._drag_op = TransferOp.MOVE
        self._device_cache.clear()
        self.viewport().update()

    def _update_drag_hover(self, index: QModelIndex, operation: TransferOp) -> None:
        hover_path: str | None = None
        if index.isValid():
            source = self._source_index(index)
            if source.isValid() and self._model.isDir(source):
                hover_path = self._path_for_index(index)
        changed = operation != self._drag_op
        if hover_path != self._drag_hover_path:
            _spring_log.debug("hover -> %s", hover_path)
            self._drag_hover_path = hover_path
            self._hover_changed_at = time.monotonic()
            changed = True
        self._drag_op = operation
        if changed:
            self.viewport().update()

    def _set_drop_target(self, index: QModelIndex) -> None:
        target = QModelIndex()
        if index.isValid():
            source = self._source_index(index)
            path = self._model.filePath(source)
            if os.path.isdir(path):
                target = index.siblingAtColumn(0)
        new_target = QPersistentModelIndex(target)
        if new_target == self._drop_target_index:
            return
        self._drop_target_index = new_target
        self.viewport().update()

    def startDrag(self, supportedActions) -> None:
        paths = self.selected_paths()
        if not paths:
            return

        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(path) for path in paths])

        drag = QDrag(self)
        drag.setMimeData(mime)
        pixmap = self._make_drag_pixmap(paths)
        drag.setPixmap(pixmap)
        drag.setHotSpot(pixmap.rect().center())
        actions = (
            Qt.DropAction.MoveAction
            | Qt.DropAction.CopyAction
            | Qt.DropAction.LinkAction
        )
        self._begin_drag_session()
        _spring_log.debug("startDrag exec begin: %s", paths)
        drag.exec(actions, Qt.DropAction.MoveAction)
        _spring_log.debug("startDrag exec returned")
        self._end_drag_session()
        self.dragSourceFinished.emit()

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            self._begin_drag_session()
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            pos = event.position().toPoint()
            index = self.indexAt(pos)
            target_dir = self._drop_target_dir(pos)
            operation = self._operation_for_event(event, target_dir)
            event.setDropAction(self._drop_action_for(operation))
            self._set_drop_target(index)
            # Spring-loading itself happens in _reconcile_spring; here we only
            # record where the cursor is. No model mutation in a drag handler.
            self._update_drag_hover(index, operation)
            dest_name = (
                bookmark_name_for_path(target_dir) if target_dir else "here"
            )
            self.statusMessage.emit(
                f"Release to {status_verb(operation)} into {dest_name}"
            )
            event.accept()
            return
        super().dragMoveEvent(event)

    def dragLeaveEvent(self, event) -> None:
        # Spurious dragLeave during drag must not clear hover state or spring timer.
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:
        if not event.mimeData().hasUrls():
            super().dropEvent(event)
            return

        _spring_log.debug("dropEvent begin")
        target_dir = self._drop_target_dir(event.position().toPoint())
        if not target_dir:
            self._end_drag_session()
            event.ignore()
            return

        sources = [
            url.toLocalFile()
            for url in event.mimeData().urls()
            if url.isLocalFile() and url.toLocalFile()
        ]
        if not sources:
            self._end_drag_session()
            event.ignore()
            return

        operation = self._operation_for_event(event, target_dir)
        event.setDropAction(self._drop_action_for(operation))

        filtered = [
            source
            for source in sources
            if not self._invalid_drop(source, target_dir, operation)
        ]
        if not filtered:
            self._end_drag_session()
            event.ignore()
            return

        self._end_drag_session()
        self.statusMessage.emit(f"Transferring {len(filtered)} item(s)…")
        errors = transfer_items(
            filtered,
            target_dir,
            operation=operation,
            on_conflict=self._resolve_conflict,
        )
        if errors:
            self.statusMessage.emit("; ".join(errors[:3]))
        else:
            verbs = {
                TransferOp.MOVE: "Moved",
                TransferOp.COPY: "Copied",
                TransferOp.ALIAS: "Aliased",
            }
            self.statusMessage.emit(f"{verbs[operation]} {len(filtered)} item(s)")

        parents = {os.path.dirname(source) for source in filtered}
        for parent in parents:
            self._model.refresh_directory(parent)
            self._model.folder_size_calculator().invalidate(parent)
        self._model.refresh_directory(target_dir)
        self.filesTransferred.emit(filtered[0], target_dir)
        event.acceptProposedAction()

    @staticmethod
    def _invalid_drop(source: str, target_dir: str, operation: TransferOp) -> bool:
        source = os.path.abspath(source)
        target_dir = os.path.abspath(target_dir)
        if source == target_dir:
            return True
        if os.path.isdir(source):
            try:
                if os.path.commonpath([source, target_dir]) == source:
                    return True
            except ValueError:
                pass
        # A plain move into the folder the item already lives in is a no-op,
        # but a copy/alias there is a legitimate "duplicate in place".
        if (
            operation is TransferOp.MOVE
            and os.path.dirname(source) == target_dir
        ):
            return True
        return False

    def _drag_modifiers(self, event) -> Qt.KeyboardModifier:
        if hasattr(event, "modifiers"):
            return event.modifiers()
        app = QApplication.instance()
        if app is not None:
            return app.keyboardModifiers()
        return Qt.KeyboardModifier.NoModifier

    def _first_local_source(self, event) -> str | None:
        for url in event.mimeData().urls():
            if url.isLocalFile():
                path = url.toLocalFile()
                if path:
                    return os.path.abspath(path)
        return None

    def _path_device(self, path: str) -> int | None:
        if path in self._device_cache:
            return self._device_cache[path]
        try:
            device: int | None = os.stat(path).st_dev
        except OSError:
            device = None
        self._device_cache[path] = device
        return device

    def _operation_for_event(self, event, target_dir: str | None) -> TransferOp:
        cross_device = False
        source = self._first_local_source(event)
        if source and target_dir:
            source_dev = self._path_device(source)
            target_dev = self._path_device(target_dir)
            cross_device = (
                source_dev is not None
                and target_dev is not None
                and source_dev != target_dev
            )
        return operation_for_modifiers(
            self._drag_modifiers(event), cross_device=cross_device
        )

    @staticmethod
    def _drop_action_for(operation: TransferOp) -> Qt.DropAction:
        if operation is TransferOp.COPY:
            return Qt.DropAction.CopyAction
        if operation is TransferOp.ALIAS:
            return Qt.DropAction.LinkAction
        return Qt.DropAction.MoveAction

    def _drop_target_dir(self, pos) -> str | None:
        index = self.indexAt(pos)
        if index.isValid():
            source = self._source_index(index)
            path = self._model.filePath(source)
            if os.path.isdir(path):
                return path
        current = self.current_directory()
        return current or None

    def _on_header_clicked(self, logical_index: int) -> None:
        # sectionClicked already emits the logical column index
        logical = logical_index
        if self._sort_column == logical:
            self._sort_order = (
                Qt.SortOrder.DescendingOrder
                if self._sort_order == Qt.SortOrder.AscendingOrder
                else Qt.SortOrder.AscendingOrder
            )
        else:
            self._sort_column = logical
            self._sort_order = Qt.SortOrder.AscendingOrder
        self._apply_sort()

    def _apply_sort(self) -> None:
        self._proxy.sort(self._sort_column, self._sort_order)
        self.header().setSortIndicator(self._sort_column, self._sort_order)

    def _can_rename_index(self, source_index: QModelIndex) -> bool:
        if not source_index.isValid():
            return False
        return bool(source_index.flags() & Qt.ItemFlag.ItemIsEditable)

    def _start_inline_rename(self, name_index: QModelIndex) -> None:
        source = self._source_index(name_index)
        if not self._can_rename_index(source):
            return
        proxy_index = self._proxy_index(source)
        if not proxy_index.isValid():
            return
        if not (proxy_index.flags() & Qt.ItemFlag.ItemIsEditable):
            return
        self.edit(proxy_index)

    def _on_double_click(self, index: QModelIndex) -> None:
        if not index.isValid():
            return
        source = self._source_index(index.siblingAtColumn(0))
        self._activate_path(self._model.filePath(source))

    def _activate_path(self, path: str) -> None:
        if os.path.isdir(path):
            self.pathActivated.emit(path)
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _is_viewing_trash(self) -> bool:
        current = self.current_directory()
        return bool(current) and is_trash_directory(current)

    def _put_back_from_trash(self) -> None:
        paths = self.selected_paths()
        if not paths:
            return
        restored = 0
        parents: set[str] = set()
        for path in paths:
            dest = restore_from_trash(path)
            if dest:
                restored += 1
                parents.add(os.path.dirname(dest))
        if self._is_viewing_trash():
            self._model.refresh_directory(self.current_directory())
        for parent in parents:
            self._model.refresh_directory(parent)
        self.statusMessage.emit(f"Restored {restored} item(s)")

    def _show_context_menu(self, pos) -> None:
        index = self.indexAt(pos)
        menu = QMenu(self)
        selected = self.selected_paths()
        in_trash = self._is_viewing_trash()

        if in_trash:
            empty_action = QAction("Empty Trash", self)
            empty_action.setEnabled(trash_count() > 0)
            empty_action.triggered.connect(self.emptyTrashRequested.emit)
            menu.addAction(empty_action)
            if selected:
                put_back = QAction("Put Back", self)
                put_back.triggered.connect(self._put_back_from_trash)
                menu.addAction(put_back)
                delete_now = QAction("Delete Immediately", self)
                delete_now.triggered.connect(self._delete_permanent)
                menu.addAction(delete_now)
            menu.addSeparator()

        if index.isValid():
            source = self._source_index(index)
            path = self._model.filePath(source)
            name = (
                bookmark_name_for_path(path)
                if os.path.isdir(path)
                else self._model.fileName(source)
            )

            open_action = QAction("Open", self)
            open_action.triggered.connect(lambda: self._activate_path(path))
            menu.addAction(open_action)

            open_with_menu = menu.addMenu("Open With")
            mime, _ = mimetypes.guess_type(path)
            for app in apps_for_mime(mime or "application/octet-stream")[:12]:
                act = QAction(app.name, self)
                act.triggered.connect(
                    lambda _checked=False, a=app, p=path: launch_app(a, p)
                )
                open_with_menu.addAction(act)

            info_action = QAction("Get Info", self)
            info_action.triggered.connect(lambda: InfoPanel(path, self).exec())
            menu.addAction(info_action)

            dup_action = QAction("Duplicate", self)
            dup_action.triggered.connect(self._duplicate_selection)
            menu.addAction(dup_action)

            copy_path = QAction("Copy Path", self)
            copy_path.triggered.connect(lambda: self._copy_path(path))
            menu.addAction(copy_path)

            add_fav = QAction("Add to Favorites", self)
            add_fav.triggered.connect(
                lambda: self.addFavoriteRequested.emit(name, path)
            )
            menu.addAction(add_fav)

            menu.addSeparator()

            rename_action = QAction("Rename", self)
            rename_action.triggered.connect(
                lambda: self._start_inline_rename(self._proxy_index(source))
            )
            menu.addAction(rename_action)

            if not in_trash:
                trash_action = QAction("Move to Trash", self)
                trash_action.triggered.connect(self._move_selection_to_trash)
                menu.addAction(trash_action)

            menu.addSeparator()

        if selected and not in_trash:
            compress_action = QAction(
                f"Compress {len(selected)} Items" if len(selected) > 1 else "Compress",
                self,
            )
            compress_action.triggered.connect(self._compress_selection)
            menu.addAction(compress_action)

            menu.addSeparator()

            count = len(selected)
            label = (
                f"New Folder with {count} Items"
                if count > 1
                else "New Folder with Selection"
            )
            new_with_sel = QAction(label, self)
            new_with_sel.triggered.connect(self._new_folder_with_selection)
            menu.addAction(new_with_sel)

        if not in_trash:
            new_folder = QAction("New Folder", self)
            new_folder.triggered.connect(self._new_folder)
            menu.addAction(new_folder)

        if not menu.actions():
            return
        menu.exec(self.viewport().mapToGlobal(pos))

    def _copy_path(self, path: str) -> None:
        from PyQt6.QtWidgets import QApplication

        QApplication.clipboard().setText(path)
        self.statusMessage.emit(f"Copied: {path}")

    def _copy_selection(self) -> None:
        paths = self.selected_paths()
        if paths:
            FileClipboard.instance().copy(paths)
            self.statusMessage.emit(f"Copied {len(paths)} item(s)")

    def _cut_selection(self) -> None:
        paths = self.selected_paths()
        if paths:
            FileClipboard.instance().cut(paths)
            self.statusMessage.emit(f"Cut {len(paths)} item(s)")
            self.viewport().update()

    def _paste(self) -> None:
        clipboard = FileClipboard.instance()
        paths, is_cut = clipboard.read_from_system()
        if not paths:
            paths = clipboard.paths
            is_cut = clipboard.is_cut
        dest = self.current_directory()
        if not dest or not paths:
            return
        op = TransferOp.MOVE if is_cut else TransferOp.COPY
        self.statusMessage.emit(f"Transferring {len(paths)} item(s)…")
        errors = transfer_items(
            paths, dest, operation=op, on_conflict=self._resolve_conflict
        )
        if errors:
            self.statusMessage.emit("; ".join(errors[:3]))
        else:
            verb = "Moved" if is_cut else "Pasted"
            self.statusMessage.emit(f"{verb} {len(paths)} item(s)")
            if is_cut:
                clipboard.clear()
            if self._undo_stack and op is TransferOp.MOVE:
                pairs = [
                    (os.path.join(dest, os.path.basename(p)), p) for p in paths
                ]
                self._undo_stack.push(MoveCommand(pairs=pairs))
            parent = os.path.dirname(paths[0]) if paths else dest
            self._model.refresh_directory(parent)
            self._model.refresh_directory(dest)
            self.filesTransferred.emit(paths[0], dest)

    def _duplicate_selection(self) -> None:
        paths = self.selected_paths()
        if not paths:
            return
        parent = self.current_directory()
        if not parent:
            return
        errors = transfer_items(
            paths, parent, operation=TransferOp.COPY, on_conflict=self._resolve_conflict
        )
        if errors:
            self.statusMessage.emit("; ".join(errors[:3]))
        else:
            self.statusMessage.emit(f"Duplicated {len(paths)} item(s)")
            self._model.refresh_directory(parent)

    def _compress_selection(self) -> None:
        paths = self.selected_paths()
        dest = self.current_directory()
        if not paths or not dest:
            return
        archive, error = compress_items(paths, dest)
        if error:
            self.statusMessage.emit(f"Compress failed: {error}")
        else:
            self.statusMessage.emit(f"Created {os.path.basename(archive)}")
            self._model.refresh_directory(dest)

    def _move_selection_to_trash(self) -> None:
        paths = self.selected_paths()
        if not paths:
            return
        trashed = move_paths_to_trash(paths)
        if not trashed:
            self.statusMessage.emit("Move to Trash failed")
            return
        if self._undo_stack:
            self._undo_stack.push(TrashCommand(trashed=trashed))
        for path in paths:
            parent = os.path.dirname(path)
            if parent:
                self._model.refresh_directory(parent)
        self.statusMessage.emit(f"Moved {len(trashed)} item(s) to Trash")

    def _delete_permanent(self) -> None:
        paths = self.selected_paths()
        if not paths:
            return
        if self._confirm_permanent_delete:
            answer = QMessageBox.question(
                self,
                "Delete Permanently",
                f"Delete {len(paths)} item(s) permanently?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        for path in paths:
            source = self._model.index(path)
            if source.isValid():
                self._model.remove(source)
        self.statusMessage.emit(f"Deleted {len(paths)} item(s) permanently")

    def _new_folder(self) -> None:
        parent = self.current_directory()
        if not parent or not os.path.isdir(parent):
            return
        path = unique_directory(parent, "untitled folder")
        try:
            os.mkdir(path)
        except OSError as exc:
            self.statusMessage.emit(f"New Folder failed: {exc}")
            return
        self._model.refresh_directory(parent)
        if self._undo_stack:
            self._undo_stack.push(MkdirCommand(path=path))
        self.statusMessage.emit("New folder created")
        self._select_and_rename_path(path)

    def _new_folder_with_selection(self) -> None:
        sources = self.selected_paths()
        if not sources:
            self._new_folder()
            return
        parent = self.current_directory()
        if not parent or not os.path.isdir(parent):
            return
        path = unique_directory(parent, "New Folder With Items")
        try:
            os.mkdir(path)
        except OSError as exc:
            self.statusMessage.emit(f"New Folder failed: {exc}")
            return
        errors = transfer_items(
            sources, path, operation=TransferOp.MOVE, on_conflict=self._resolve_conflict
        )
        if errors:
            self.statusMessage.emit("; ".join(errors[:3]))
        else:
            self.statusMessage.emit(
                f"New folder with {len(sources)} item(s)"
            )
        self._model.refresh_directory(parent)
        self._model.refresh_directory(path)
        self._model.folder_size_calculator().invalidate(parent)
        self.filesTransferred.emit(sources[0], path)
        self._select_and_rename_path(path)

    def _select_and_rename_path(self, path: str, attempts: int = 12) -> None:
        """Select a freshly created folder and open it for inline rename.

        The model repopulates a refreshed directory asynchronously, so the new
        row may not exist yet; retry a few times on the event loop before
        giving up.
        """
        source = self._model.index(path)
        proxy = self._proxy_index(source)
        if proxy.isValid():
            name_index = self._name_index(proxy)
            self.setCurrentIndex(name_index)
            self.scrollTo(name_index)
            self._start_inline_rename(name_index)
            return
        if attempts > 0:
            QTimer.singleShot(
                50, lambda: self._select_and_rename_path(path, attempts - 1)
            )
