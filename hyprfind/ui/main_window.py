"""Main application window."""

from __future__ import annotations

import os
import shutil
import subprocess

from PyQt6.QtCore import QEvent, Qt, QTimer
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenuBar,
    QMessageBox,
    QSizePolicy,
    QSplitter,
    QStatusBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from hyprfind.core.bookmarks import BookmarkStore
from hyprfind.core.file_ops import TransferOp, transfer_items
from hyprfind.core.model import HyprFileSystemModel
from hyprfind.core.mounts import MountService
from hyprfind.core.recents import RecentFolders
from hyprfind.core.smart_folders import SmartFolderStore
from hyprfind.core.settings import AppSettings
from hyprfind.core.trash import empty_trash, is_trash_directory, trash_count, trash_path
from hyprfind.core.undo import UndoStack
from hyprfind.ui.browser_pane import BrowserPane
from hyprfind.ui.browser_tab import BrowserTab
from hyprfind.ui.path_bar import PathBar
from hyprfind.ui.preferences import PreferencesDialog
from hyprfind.ui.preview import PreviewOverlay
from hyprfind.ui.sidebar import Sidebar
from hyprfind.utils.paths import default_favorites, expand_path


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("HyprFind")
        self.resize(1100, 700)

        self._mount_service = MountService()
        self._bookmark_store = BookmarkStore()
        self._bookmark_store.load()
        self._settings = AppSettings()
        self._settings.load()
        self._layout_initialized = False
        self._model = HyprFileSystemModel(
            is_network_path=self._mount_service.is_network_path,
            parent=self,
        )

        home = os.path.expanduser("~")
        self._model.setRootPath(home)

        self._panes: list[BrowserPane] = []
        self._active_pane: BrowserPane | None = None
        self._undo_stack = UndoStack()
        self._recents = RecentFolders()
        self._recents.load()
        self._smart_folders = SmartFolderStore()
        self._smart_folders.load()
        self._undo_stack.add_listener(self._update_undo_actions)

        self._model.set_show_hidden(self._settings.show_hidden)

        self._build_menu_bar()
        self._build_toolbar()
        self._build_status_bar()
        self._build_ui(home)
        self._connect_signals()
        self._apply_view_mode()

        QApplication.instance().installEventFilter(self)

    def _active_tab(self) -> BrowserTab | None:
        if self._active_pane is None:
            return None
        return self._active_pane.browser_tab

    def _pane_for_tab(self, tab: BrowserTab) -> BrowserPane | None:
        for pane in self._panes:
            if pane.browser_tab is tab:
                return pane
        return None

    def _build_menu_bar(self) -> None:
        bar = QMenuBar(self)
        self.setMenuBar(bar)

        file_menu = bar.addMenu("File")
        self._new_folder_action = QAction("New Folder", self)
        self._new_folder_action.setShortcut(QKeySequence("Ctrl+Shift+N"))
        self._new_folder_action.triggered.connect(self._menu_new_folder)
        file_menu.addAction(self._new_folder_action)

        new_pane_menu = QAction("New Pane", self)
        new_pane_menu.setShortcut(QKeySequence("Ctrl+T"))
        new_pane_menu.triggered.connect(self._new_pane)
        file_menu.addAction(new_pane_menu)

        file_menu.addSeparator()
        self._empty_trash_action = QAction("Empty Trash", self)
        self._empty_trash_action.setShortcut(QKeySequence("Ctrl+Shift+Delete"))
        self._empty_trash_action.triggered.connect(self._empty_trash)
        file_menu.addAction(self._empty_trash_action)

        file_menu.addSeparator()
        prefs_action = QAction("Preferences…", self)
        prefs_action.triggered.connect(self._show_preferences)
        file_menu.addAction(prefs_action)

        edit_menu = bar.addMenu("Edit")
        self._undo_action = QAction("Undo", self)
        self._undo_action.setShortcut(QKeySequence("Ctrl+Z"))
        self._undo_action.triggered.connect(self._undo)
        edit_menu.addAction(self._undo_action)

        self._redo_action = QAction("Redo", self)
        self._redo_action.setShortcut(QKeySequence("Ctrl+Shift+Z"))
        self._redo_action.triggered.connect(self._redo)
        edit_menu.addAction(self._redo_action)

        edit_menu.addSeparator()
        cut_action = QAction("Cut", self)
        cut_action.setShortcut(QKeySequence("Ctrl+X"))
        cut_action.triggered.connect(self._menu_cut)
        edit_menu.addAction(cut_action)

        copy_action = QAction("Copy", self)
        copy_action.setShortcut(QKeySequence("Ctrl+C"))
        copy_action.triggered.connect(self._menu_copy)
        edit_menu.addAction(copy_action)

        paste_action = QAction("Paste", self)
        paste_action.setShortcut(QKeySequence("Ctrl+V"))
        paste_action.triggered.connect(self._menu_paste)
        edit_menu.addAction(paste_action)

        dup_action = QAction("Duplicate", self)
        dup_action.setShortcut(QKeySequence("Ctrl+D"))
        dup_action.triggered.connect(self._menu_duplicate)
        edit_menu.addAction(dup_action)

        view_menu = bar.addMenu("View")
        self._hidden_action = QAction("Show Hidden Files", self)
        self._hidden_action.setCheckable(True)
        self._hidden_action.setChecked(self._settings.show_hidden)
        self._hidden_action.setShortcut(QKeySequence("Ctrl+Shift+."))
        self._hidden_action.triggered.connect(self._toggle_hidden_files)
        view_menu.addAction(self._hidden_action)

        view_menu.addSeparator()
        list_view = QAction("as List", self)
        list_view.triggered.connect(lambda: self._set_view_mode("list"))
        view_menu.addAction(list_view)

        icon_view = QAction("as Icons", self)
        icon_view.triggered.connect(lambda: self._set_view_mode("icon"))
        view_menu.addAction(icon_view)

        column_view = QAction("as Columns", self)
        column_view.triggered.connect(lambda: self._set_view_mode("column"))
        view_menu.addAction(column_view)

        go_menu = bar.addMenu("Go")
        back_menu = QAction("Back", self)
        back_menu.setShortcut(QKeySequence("Ctrl+["))
        back_menu.triggered.connect(self._go_back)
        go_menu.addAction(back_menu)

        fwd_menu = QAction("Forward", self)
        fwd_menu.setShortcut(QKeySequence("Ctrl+]"))
        fwd_menu.triggered.connect(self._go_forward)
        go_menu.addAction(fwd_menu)

        parent_menu = QAction("Enclosing Folder", self)
        parent_menu.setShortcut(QKeySequence("Alt+Up"))
        parent_menu.triggered.connect(self._go_parent_active)
        go_menu.addAction(parent_menu)

        go_menu.addSeparator()
        for name, path in default_favorites():
            act = QAction(name, self)
            act.triggered.connect(lambda _c=False, p=path: self.navigate_to(p, push_history=True))
            go_menu.addAction(act)

        self._recents_menu = go_menu.addMenu("Recent Folders")
        self._rebuild_recents_menu()

        self._smart_menu = go_menu.addMenu("Smart Folders")
        self._rebuild_smart_menu()

        go_menu.addSeparator()
        connect_action = QAction("Connect to Server…", self)
        connect_action.triggered.connect(self._connect_to_server)
        go_menu.addAction(connect_action)

        self._update_undo_actions()

    def eventFilter(self, obj, event) -> bool:
        if (
            self._preview.isVisible()
            and event.type() == QEvent.Type.MouseButtonPress
        ):
            widget = obj if hasattr(obj, "isAncestorOf") else None
            if widget and not self._preview.isAncestorOf(widget) and widget is not self._preview:
                self._preview.hide()
        return super().eventFilter(obj, event)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Navigation", self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        self._back_action = QAction("◀", self)
        self._back_action.setToolTip("Back — previous folder (Ctrl+[)")
        self._back_action.setStatusTip("Go to the previous folder in this pane")
        self._back_action.triggered.connect(self._go_back)
        toolbar.addAction(self._back_action)

        self._forward_action = QAction("▶", self)
        self._forward_action.setToolTip("Forward — next folder (Ctrl+])")
        self._forward_action.setStatusTip("Go to the next folder in this pane")
        self._forward_action.triggered.connect(self._go_forward)
        toolbar.addAction(self._forward_action)

        self._refresh_action = QAction("↻", self)
        self._refresh_action.setToolTip("Refresh — reload this folder (F5)")
        self._refresh_action.setStatusTip("Reload the current folder listing")
        self._refresh_action.triggered.connect(self._force_refresh)
        toolbar.addAction(self._refresh_action)

        self._new_pane_action = QAction("+", self)
        self._new_pane_action.setToolTip("New pane — side-by-side column (Ctrl+T)")
        self._new_pane_action.setStatusTip("Open another folder column beside this one")
        self._new_pane_action.triggered.connect(self._new_pane)
        toolbar.addAction(self._new_pane_action)

        self._empty_trash_toolbar = QAction("🗑", self)
        self._empty_trash_toolbar.setToolTip("Empty Trash")
        self._empty_trash_toolbar.setStatusTip("Permanently erase all items in the Trash")
        self._empty_trash_toolbar.triggered.connect(self._empty_trash)
        self._empty_trash_toolbar.setVisible(False)
        toolbar.addAction(self._empty_trash_toolbar)

        toolbar.addSeparator()

        self._filter_bar = QLineEdit()
        self._filter_bar.setPlaceholderText("Filter")
        self._filter_bar.setClearButtonEnabled(True)
        self._filter_bar.setMaximumWidth(200)
        self._filter_bar.textChanged.connect(self._on_filter_changed)
        toolbar.addWidget(self._filter_bar)

        filter_shortcut = QAction(self)
        filter_shortcut.setShortcut(QKeySequence("Ctrl+F"))
        filter_shortcut.triggered.connect(lambda: self._filter_bar.setFocus())
        self.addAction(filter_shortcut)

        toolbar.addSeparator()

        self._path_bar = PathBar(self)
        self._path_bar.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        toolbar.addWidget(self._path_bar)

    def _build_ui(self, home: str) -> None:
        central = QWidget()
        central.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setChildrenCollapsible(False)
        self._splitter.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        layout.addWidget(self._splitter, 1)

        self._sidebar = Sidebar(self._bookmark_store, self._mount_service)
        self._sidebar.setMinimumWidth(88)
        self._splitter.addWidget(self._sidebar)

        right = QWidget()
        right.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        self._pane_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._pane_splitter.setChildrenCollapsible(False)
        self._pane_splitter.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._pane_splitter.setHandleWidth(1)
        right_layout.addWidget(self._pane_splitter, 1)
        self._splitter.addWidget(right)
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.splitterMoved.connect(self._on_sidebar_splitter_moved)

        self._preview = PreviewOverlay(self)
        self._add_pane(home)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self._apply_splitter_sizes)

    def _apply_splitter_sizes(self) -> None:
        if not hasattr(self, "_splitter"):
            return
        total = self._splitter.width()
        if total <= 0:
            return

        if self._layout_initialized:
            self._equalize_pane_sizes()
            return

        min_content = 320
        if self._settings.sidebar_width is not None:
            sidebar = self._settings.sidebar_width
        else:
            sidebar = self._sidebar.preferred_width()

        sidebar = max(self._sidebar.minimumWidth(), sidebar)
        sidebar = min(sidebar, max(self._sidebar.minimumWidth(), total - min_content))
        self._splitter.setSizes([sidebar, max(1, total - sidebar)])
        self._layout_initialized = True
        self._equalize_pane_sizes()

    def _on_sidebar_splitter_moved(self, _pos: int, _index: int) -> None:
        sizes = self._splitter.sizes()
        if sizes:
            self._settings.set_sidebar_width(sizes[0])

    def _equalize_pane_sizes(self) -> None:
        count = len(self._panes)
        if count == 0:
            return
        width = self._pane_splitter.width()
        if width <= 0:
            return
        each = max(280, width // count)
        self._pane_splitter.setSizes([each] * count)

    def _build_status_bar(self) -> None:
        self._status_bar = QStatusBar(self)
        self.setStatusBar(self._status_bar)
        self._count_label = QLabel("")
        self._space_label = QLabel("")
        self._size_label = QLabel("")
        self._refresh_label = QLabel("")
        self._status_bar.addPermanentWidget(self._count_label)
        self._status_bar.addPermanentWidget(self._space_label)
        self._status_bar.addPermanentWidget(self._size_label)
        self._status_bar.addPermanentWidget(self._refresh_label)

    def _connect_signals(self) -> None:
        self._path_bar.navigate.connect(self._navigate_from_bar)
        self._sidebar.pathSelected.connect(
            lambda p: self.navigate_to(p, push_history=True)
        )
        self._sidebar.addFavoriteRequested.connect(self._add_favorite)
        self._sidebar.openInNewPaneRequested.connect(self._open_in_new_pane)
        self._sidebar.removeFavoriteRequested.connect(self._remove_favorite)
        self._sidebar.filesDropped.connect(self._on_sidebar_files_dropped)
        self._sidebar.emptyTrashRequested.connect(self._empty_trash)

        self._model.directoryRefreshed.connect(self._on_model_refreshed)
        calc = self._model.folder_size_calculator()
        self._folder_size_pending = 0
        self._folder_size_status_timer = QTimer(self)
        self._folder_size_status_timer.setSingleShot(True)
        self._folder_size_status_timer.setInterval(250)
        self._folder_size_status_timer.timeout.connect(self._flush_folder_size_status)
        calc.queueChanged.connect(self._on_folder_size_queue_changed)

        refresh_shortcut = QAction(self)
        refresh_shortcut.setShortcut(QKeySequence("Ctrl+R"))
        refresh_shortcut.triggered.connect(self._force_refresh)
        self.addAction(refresh_shortcut)

        f5_shortcut = QAction(self)
        f5_shortcut.setShortcut(QKeySequence("F5"))
        f5_shortcut.triggered.connect(self._force_refresh)
        self.addAction(f5_shortcut)

        back_shortcut = QAction(self)
        back_shortcut.setShortcut(QKeySequence("Ctrl+["))
        back_shortcut.triggered.connect(self._go_back)
        self.addAction(back_shortcut)

        forward_shortcut = QAction(self)
        forward_shortcut.setShortcut(QKeySequence("Ctrl+]"))
        forward_shortcut.triggered.connect(self._go_forward)
        self.addAction(forward_shortcut)

        path_shortcut = QAction(self)
        path_shortcut.setShortcut(QKeySequence("Ctrl+L"))
        path_shortcut.triggered.connect(lambda: self._path_bar.focus_editor())
        self.addAction(path_shortcut)

        parent_shortcut = QAction(self)
        parent_shortcut.setShortcut(QKeySequence("Alt+Up"))
        parent_shortcut.triggered.connect(self._go_parent_active)
        self.addAction(parent_shortcut)

        hidden_shortcut = QAction(self)
        hidden_shortcut.setShortcut(QKeySequence("Ctrl+Shift+."))
        hidden_shortcut.triggered.connect(self._toggle_hidden_files)
        self.addAction(hidden_shortcut)

        new_pane_shortcut = QAction(self)
        new_pane_shortcut.setShortcut(QKeySequence("Ctrl+T"))
        new_pane_shortcut.triggered.connect(self._new_pane)
        self.addAction(new_pane_shortcut)

        close_pane_shortcut = QAction(self)
        close_pane_shortcut.setShortcut(QKeySequence("Ctrl+W"))
        close_pane_shortcut.triggered.connect(self._close_active_pane)
        self.addAction(close_pane_shortcut)

        esc_shortcut = QAction(self)
        esc_shortcut.setShortcut(QKeySequence("Escape"))
        esc_shortcut.triggered.connect(self._hide_preview)
        self.addAction(esc_shortcut)

    def _add_pane(self, path: str | None = None) -> BrowserPane:
        start_path = path or os.path.expanduser("~")
        pane = BrowserPane(self._model, self._mount_service, start_path)
        self._panes.append(pane)
        self._pane_splitter.addWidget(pane)
        self._wire_pane(pane)
        pane.activated.connect(lambda p=pane: self._set_active_pane(p))
        pane.closeRequested.connect(lambda p=pane: self._close_pane(p))
        self._equalize_pane_sizes()
        self._set_active_pane(pane)
        return pane

    def _wire_pane(self, pane: BrowserPane) -> None:
        tab = pane.browser_tab
        fl = tab.file_list
        fl.set_undo_stack(self._undo_stack)
        fl.set_confirm_permanent_delete(self._settings.confirm_permanent_delete)
        vs = tab.view_stack
        fl.pathActivated.connect(
            lambda p, t=tab: self._navigate_tab(t, p, push_history=True)
        )
        vs.pathActivated.connect(
            lambda p, t=tab: self._navigate_tab(t, p, push_history=True)
        )
        fl.openParentRequested.connect(
            lambda t=tab: self._go_parent_tab(t)
        )
        fl.previewRequested.connect(self._toggle_preview)
        fl.addFavoriteRequested.connect(self._add_favorite)
        fl.statusMessage.connect(self._show_status)
        fl.filesTransferred.connect(self._on_files_transferred)
        fl.dragSourceFinished.connect(self._end_foreign_drag_sessions)
        fl.emptyTrashRequested.connect(self._empty_trash)
        fl.selectionChangedSignal.connect(self._update_selection_status)
        vs.selectionChanged.connect(self._update_selection_status)
        tab.refresh_service.changed.connect(
            lambda path, t=tab: self._on_directory_changed(t, path)
        )
        tab.refresh_service.strategyChanged.connect(
            lambda _path, _strategy, t=tab: self._on_strategy_changed(t)
        )

    def _new_pane(self) -> None:
        active = self._active_tab()
        path = active.current_path if active else os.path.expanduser("~")
        self._add_pane(path)

    def _close_pane(self, pane: BrowserPane) -> None:
        if len(self._panes) <= 1:
            return
        pane.browser_tab.stop_watching()
        self._panes.remove(pane)
        pane.setParent(None)
        pane.deleteLater()
        if self._active_pane is pane:
            self._active_pane = self._panes[-1]
            self._sync_active_pane_ui()
        self._equalize_pane_sizes()

    def _close_active_pane(self) -> None:
        if self._active_pane is not None:
            self._close_pane(self._active_pane)

    def _set_active_pane(self, pane: BrowserPane) -> None:
        if pane not in self._panes:
            return
        self._active_pane = pane
        for item in self._panes:
            item.set_active(item is pane)
        self._sync_active_pane_ui()

    def _sync_active_pane_ui(self) -> None:
        tab = self._active_tab()
        if not tab:
            return
        self._path_bar.set_path(tab.current_path)
        self._update_refresh_label(tab)
        self._update_nav_buttons(tab)
        if tab.current_path:
            self._model.set_active_directory(tab.current_path)
        tab.view_stack.setFocus()
        self._update_selection_status()
        self._update_disk_space(tab.current_path)
        self._update_trash_ui(tab.current_path)

    def navigate_to(self, path: str, *, push_history: bool = False) -> None:
        tab = self._active_tab()
        if not tab:
            return
        self._navigate_tab(tab, path, push_history=push_history)

    def _navigate_tab(
        self, tab: BrowserTab, path: str, *, push_history: bool = False
    ) -> None:
        normalized = expand_path(path)
        if not tab.navigate_to(normalized, push_history=push_history):
            self._show_status(f"Not a directory: {normalized}")
            return

        pane = self._pane_for_tab(tab)
        if pane is not None:
            pane.update_title()
        self._recents.push(normalized)
        self._rebuild_recents_menu()
        if tab is self._active_tab():
            self._path_bar.set_path(normalized)
            self._update_refresh_label(tab)
            self._update_nav_buttons(tab)
            self._update_disk_space(normalized)
            self._update_trash_ui(normalized)
            tab.view_stack.setFocus()

    def _navigate_from_bar(self, path: str) -> None:
        self.navigate_to(path, push_history=True)

    def _go_back(self) -> None:
        tab = self._active_tab()
        if not tab:
            return
        path = tab.history.back()
        if path:
            self._navigate_tab(tab, path, push_history=False)
            self._update_nav_buttons(tab)

    def _go_forward(self) -> None:
        tab = self._active_tab()
        if not tab:
            return
        path = tab.history.forward()
        if path:
            self._navigate_tab(tab, path, push_history=False)
            self._update_nav_buttons(tab)

    def _go_parent_tab(self, tab: BrowserTab) -> None:
        current = tab.current_path
        parent = os.path.dirname(current)
        if parent and parent != current:
            self._navigate_tab(tab, parent, push_history=True)

    def _force_refresh(self) -> None:
        tab = self._active_tab()
        if not tab:
            return
        current = tab.current_path
        if not current:
            return
        self._model.refresh_directory(current)
        tab.refresh_service.force_poll_check()
        self._show_status("Refreshed")

    def _on_directory_changed(self, tab: BrowserTab, path: str) -> None:
        if os.path.normpath(path) == os.path.normpath(tab.current_path):
            self._model.refresh_directory(path)

    def _on_model_refreshed(self, path: str) -> None:
        for pane in self._panes:
            tab = pane.browser_tab
            if os.path.normpath(path) == os.path.normpath(tab.current_path):
                tab.view_stack.set_current_directory(path)

    def _on_files_transferred(self, _source: str, _dest: str) -> None:
        for pane in self._panes:
            pane.browser_tab.file_list._apply_sort()

    def _end_foreign_drag_sessions(self) -> None:
        for pane in self._panes:
            pane.browser_tab.file_list.end_foreign_drag_session()

    def _on_strategy_changed(self, tab: BrowserTab) -> None:
        if tab is self._active_tab():
            self._update_refresh_label(tab)

    def _update_refresh_label(self, tab: BrowserTab) -> None:
        self._refresh_label.setText(tab.refresh_service.status_label())

    def _on_folder_size_queue_changed(self, count: int) -> None:
        self._folder_size_pending = count
        if not self._folder_size_status_timer.isActive():
            self._folder_size_status_timer.start()

    def _flush_folder_size_status(self) -> None:
        count = self._folder_size_pending
        if count <= 0:
            self._size_label.setText("")
            return
        tab = self._active_tab()
        on_cifs = (
            tab is not None
            and self._mount_service.is_network_path(tab.current_path)
        )
        if on_cifs:
            self._size_label.setText(f"Calculating CIFS sizes ({count})…")
        else:
            self._size_label.setText(f"Calculating sizes ({count})…")

    def _update_nav_buttons(self, tab: BrowserTab) -> None:
        self._back_action.setEnabled(tab.history.can_back())
        self._forward_action.setEnabled(tab.history.can_forward())

    def _toggle_preview(self, path: str) -> None:
        tab = self._active_tab()
        paths = tab.file_list.selected_paths() if tab else [path]
        if path not in paths:
            paths = [path]
        self._preview.toggle(path, paths)

    def _hide_preview(self) -> None:
        if self._preview.isVisible():
            self._preview.hide()

    def _add_favorite(self, name: str, path: str) -> None:
        self._bookmark_store.add(name, path)
        self._sidebar.reload()
        self._show_status(f"Added to favorites: {name}")

    def _on_sidebar_files_dropped(
        self, sources: list, dest_dir: str, op_value: str
    ) -> None:
        from hyprfind.core.file_ops import TransferOp, transfer_items

        try:
            operation = TransferOp(op_value)
        except ValueError:
            return
        dest_abs = os.path.abspath(dest_dir)
        filtered = [
            str(source)
            for source in sources
            if os.path.abspath(str(source)) != dest_abs
            and os.path.dirname(os.path.abspath(str(source))) != dest_abs
        ]
        if not filtered and operation is TransferOp.MOVE:
            return
        targets = filtered or [str(s) for s in sources]
        errors = transfer_items(targets, dest_dir, operation=operation)
        if errors:
            self._show_status("; ".join(errors[:3]))
        else:
            verbs = {
                TransferOp.MOVE: "Moved",
                TransferOp.COPY: "Copied",
                TransferOp.ALIAS: "Aliased",
            }
            name = os.path.basename(dest_dir.rstrip("/")) or dest_dir
            self._show_status(
                f"{verbs[operation]} {len(targets)} item(s) to {name}"
            )

        calc = self._model.folder_size_calculator()
        for parent in {os.path.dirname(os.path.abspath(s)) for s in targets}:
            self._model.refresh_directory(parent)
            calc.invalidate(parent)
        self._model.refresh_directory(dest_dir)
        calc.invalidate(dest_dir)
        for pane in self._panes:
            pane.browser_tab.file_list._apply_sort()

    def _open_in_new_pane(self, path: str) -> None:
        normalized = expand_path(path)
        if not os.path.isdir(normalized):
            self._show_status(f"Not a directory: {normalized}")
            return
        self._add_pane(normalized)

    def _remove_favorite(self, path: str) -> None:
        if not self._bookmark_store.is_removable(path):
            self._show_status("Built-in favorites cannot be removed")
            return
        name = os.path.basename(path.rstrip("/")) or path
        self._bookmark_store.remove(path)
        self._sidebar.reload()
        self._show_status(f"Removed from favorites: {name}")

    def _show_status(self, message: str) -> None:
        self._status_bar.showMessage(message, 5000)

    def _menu_new_folder(self) -> None:
        tab = self._active_tab()
        if tab:
            tab.file_list._new_folder()

    def _menu_cut(self) -> None:
        tab = self._active_tab()
        if tab:
            tab.file_list._cut_selection()

    def _menu_copy(self) -> None:
        tab = self._active_tab()
        if tab:
            tab.file_list._copy_selection()

    def _menu_paste(self) -> None:
        tab = self._active_tab()
        if tab:
            tab.file_list._paste()

    def _menu_duplicate(self) -> None:
        tab = self._active_tab()
        if tab:
            tab.file_list._duplicate_selection()

    def _undo(self) -> None:
        desc = self._undo_stack.undo()
        if desc:
            self._refresh_all_panes()
            self._show_status(f"Undo: {desc}")

    def _redo(self) -> None:
        desc = self._undo_stack.redo()
        if desc:
            self._refresh_all_panes()
            self._show_status(f"Redo: {desc}")

    def _update_undo_actions(self) -> None:
        if hasattr(self, "_undo_action"):
            self._undo_action.setEnabled(self._undo_stack.can_undo())
            self._redo_action.setEnabled(self._undo_stack.can_redo())

    def _refresh_all_panes(self) -> None:
        for pane in self._panes:
            path = pane.browser_tab.current_path
            if path:
                self._model.refresh_directory(path)

    def _toggle_hidden_files(self) -> None:
        if hasattr(self, "_hidden_action") and self.sender() is self._hidden_action:
            show = self._hidden_action.isChecked()
        else:
            show = not self._settings.show_hidden
        self._settings.set_show_hidden(show)
        self._model.set_show_hidden(show)
        if hasattr(self, "_hidden_action"):
            self._hidden_action.setChecked(show)
        for pane in self._panes:
            path = pane.browser_tab.current_path
            if path:
                pane.browser_tab.view_stack.set_current_directory(path)

    def _on_filter_changed(self, text: str) -> None:
        tab = self._active_tab()
        if tab:
            tab.view_stack.set_name_filter(text)

    def _set_view_mode(self, mode: str) -> None:
        self._settings.set_view_mode(mode)
        self._apply_view_mode()

    def _apply_view_mode(self) -> None:
        for pane in self._panes:
            pane.browser_tab.view_stack.set_view_mode(
                self._settings.view_mode, self._settings.icon_size
            )

    def _go_parent_active(self) -> None:
        tab = self._active_tab()
        if tab:
            self._go_parent_tab(tab)

    def _rebuild_smart_menu(self) -> None:
        if not hasattr(self, "_smart_menu"):
            return
        self._smart_menu.clear()
        for folder in self._smart_folders.all():
            act = QAction(folder.name, self)
            act.triggered.connect(
                lambda _c=False, q=folder.query: self._apply_smart_search(q)
            )
            self._smart_menu.addAction(act)

    def _apply_smart_search(self, query: str) -> None:
        self._filter_bar.setText(query)
        self._on_filter_changed(query)

    def _rebuild_recents_menu(self) -> None:
        if not hasattr(self, "_recents_menu"):
            return
        self._recents_menu.clear()
        for path in self._recents.all()[:15]:
            name = os.path.basename(path.rstrip("/")) or path
            act = QAction(name, self)
            act.setToolTip(path)
            act.triggered.connect(
                lambda _c=False, p=path: self.navigate_to(p, push_history=True)
            )
            self._recents_menu.addAction(act)

    def _connect_to_server(self) -> None:
        url, ok = QInputDialog.getText(
            self, "Connect to Server", "Server address (smb://…):"
        )
        if not ok or not url.strip():
            return
        address = url.strip()
        if not address.startswith(("smb://", "ftp://", "sftp://")):
            address = f"smb://{address}"
        try:
            subprocess.Popen(
                ["gio", "mount", address],
                start_new_session=True,
            )
            self._show_status(f"Connecting to {address}…")
            QTimer.singleShot(2000, self._sidebar.reload)
        except OSError as exc:
            self._show_status(f"Connect failed: {exc}")

    def _update_trash_ui(self, path: str) -> None:
        in_trash = is_trash_directory(path)
        count = trash_count()
        if hasattr(self, "_empty_trash_toolbar"):
            self._empty_trash_toolbar.setVisible(in_trash)
            self._empty_trash_toolbar.setEnabled(count > 0)
        if hasattr(self, "_empty_trash_action"):
            self._empty_trash_action.setEnabled(count > 0)

    def _empty_trash(self) -> None:
        if trash_count() == 0:
            self._show_status("Trash is already empty")
            return
        answer = QMessageBox.question(
            self,
            "Empty Trash",
            "Permanently erase all items in the Trash?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        errors = empty_trash()
        if errors:
            self._show_status("; ".join(errors[:3]))
        else:
            self._show_status("Trash emptied")
        self._model.refresh_directory(trash_path())
        self._refresh_all_panes()
        self._update_trash_ui(trash_path())

    def _show_preferences(self) -> None:
        dialog = PreferencesDialog(self._settings, self)
        if dialog.exec() != PreferencesDialog.DialogCode.Accepted:
            return
        self._model.set_show_hidden(self._settings.show_hidden)
        if hasattr(self, "_hidden_action"):
            self._hidden_action.setChecked(self._settings.show_hidden)
        for pane in self._panes:
            pane.browser_tab.file_list.set_confirm_permanent_delete(
                self._settings.confirm_permanent_delete
            )
        self._apply_view_mode()

    def _update_selection_status(self) -> None:
        tab = self._active_tab()
        if not tab:
            return
        paths = tab.view_stack.selected_paths()
        root = tab.file_list._proxy.rowCount(tab.file_list.rootIndex())
        sel = len(paths)
        if sel:
            self._count_label.setText(f"{sel} selected")
        else:
            self._count_label.setText(f"{root} items")

    def _update_disk_space(self, path: str) -> None:
        if not path:
            self._space_label.setText("")
            return
        try:
            usage = shutil.disk_usage(path)
            free_gb = usage.free / (1000**3)
            self._space_label.setText(f"{free_gb:.1f} GB free")
        except OSError:
            self._space_label.setText("")

    def closeEvent(self, event) -> None:
        for pane in self._panes:
            pane.browser_tab.stop_watching()
        self._model.folder_size_calculator().flush()
        super().closeEvent(event)
