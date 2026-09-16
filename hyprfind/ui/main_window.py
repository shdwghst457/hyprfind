"""Main application window."""

from __future__ import annotations

import os
import shutil

from PyQt6.QtCore import QByteArray, QEvent, Qt, QTimer
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
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
from hyprfind.core.grouping import (
    GROUP_DATE_MODIFIED,
    GROUP_KIND,
    GROUP_LABELS,
    GROUP_NAME,
    GROUP_NONE,
    GROUP_SIZE,
)
from hyprfind.core.model import HyprFileSystemModel
from hyprfind.core.search import (
    SCOPE_EVERYWHERE,
    SCOPE_HERE,
    SearchQuery,
    search_roots,
)
from hyprfind.core.servers import ServerStore
from hyprfind.core.smart_folders import SmartFolder
from hyprfind.ui.connect_server import ConnectServerDialog
from hyprfind.ui.smart_folder_editor import SmartFolderEditor
from hyprfind.core.mounts import MountService
from hyprfind.core.recents import RecentFolders
from hyprfind.core.smart_folders import SmartFolderStore
from hyprfind.core.settings import AppSettings
from hyprfind.core.trash import empty_trash, is_trash_directory, trash_count, trash_path
from hyprfind.core.undo import UndoStack
from hyprfind.ui.browser_pane import BrowserPane
from hyprfind.ui.browser_tab import BrowserTab
from hyprfind.ui.path_bar import PathBar
from hyprfind.ui.icons import ThemeIconProvider
from hyprfind.ui.preferences import PreferencesDialog
from hyprfind.ui.preview import PreviewOverlay
from hyprfind.ui.sidebar import Sidebar
from hyprfind.utils.paths import default_favorites, expand_path


class _StatusField(QLabel):
    """Status reading that hides its leading divider while it has no text.

    Several readings populate at once, so without dividers they run together;
    without this hiding, empty readings leave stray dots behind.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.divider = QLabel("·", parent)
        self.divider.setObjectName("statusDivider")
        self.divider.hide()

    def setText(self, text: str) -> None:
        super().setText(text)
        self.divider.setVisible(bool(text))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("HyprFind")
        self.resize(1100, 700)
        self.setMinimumSize(640, 400)

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
        self._icon_provider = ThemeIconProvider()
        self._model.setIconProvider(self._icon_provider)

        home = os.path.expanduser("~")
        self._model.setRootPath(home)

        self._panes: list[BrowserPane] = []
        self._active_pane: BrowserPane | None = None
        self._undo_stack = UndoStack()
        self._recents = RecentFolders()
        self._recents.load()
        self._smart_folders = SmartFolderStore()
        self._smart_folders.load()
        self._server_store = ServerStore()
        self._server_store.load()
        self._undo_stack.add_listener(self._update_undo_actions)

        self._model.set_show_hidden(self._settings.show_hidden)

        self._build_menu_bar()
        self._build_toolbar()
        self._build_status_bar()
        self._build_ui(home)
        self._connect_signals()
        self._apply_view_mode()
        self._restore_window_geometry()

        QApplication.instance().installEventFilter(self)

    def _active_tab(self) -> BrowserTab | None:
        if self._active_pane is None:
            return None
        return self._active_pane.browser_tab

    def _pane_for_tab(self, tab: BrowserTab) -> BrowserPane | None:
        for pane in self._panes:
            if pane.index_of(tab) >= 0:
                return pane
        return None

    def _all_tabs(self) -> list[BrowserTab]:
        """Every tab in every pane; background tabs still need refreshing."""
        return [tab for pane in self._panes for tab in pane.tabs()]

    def _build_menu_bar(self) -> None:
        bar = QMenuBar(self)
        self.setMenuBar(bar)

        file_menu = bar.addMenu("File")
        self._new_folder_action = QAction("New Folder", self)
        self._new_folder_action.setShortcut(QKeySequence("Ctrl+Shift+N"))
        self._new_folder_action.triggered.connect(self._menu_new_folder)
        file_menu.addAction(self._new_folder_action)

        new_tab_menu = QAction("New Tab", self)
        new_tab_menu.setShortcut(QKeySequence("Ctrl+T"))
        new_tab_menu.triggered.connect(self._new_tab)
        file_menu.addAction(new_tab_menu)

        new_pane_menu = QAction("New Pane", self)
        new_pane_menu.setShortcut(QKeySequence("Ctrl+Alt+T"))
        new_pane_menu.triggered.connect(self._new_pane)
        file_menu.addAction(new_pane_menu)

        file_menu.addSeparator()
        close_tab_menu = QAction("Close Tab", self)
        close_tab_menu.setShortcut(QKeySequence("Ctrl+W"))
        close_tab_menu.triggered.connect(self._close_active_tab)
        file_menu.addAction(close_tab_menu)

        close_pane_menu = QAction("Close Pane", self)
        close_pane_menu.setShortcut(QKeySequence("Ctrl+Alt+W"))
        close_pane_menu.triggered.connect(self._close_active_pane)
        file_menu.addAction(close_pane_menu)

        next_tab = QAction("Next Tab", self)
        next_tab.setShortcut(QKeySequence("Ctrl+Tab"))
        next_tab.triggered.connect(lambda: self._cycle_tab(1))
        file_menu.addAction(next_tab)

        prev_tab = QAction("Previous Tab", self)
        prev_tab.setShortcut(QKeySequence("Ctrl+Shift+Tab"))
        prev_tab.triggered.connect(lambda: self._cycle_tab(-1))
        file_menu.addAction(prev_tab)

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

        edit_menu.addSeparator()
        find_action = QAction("Find…", self)
        find_action.setShortcut(QKeySequence("Ctrl+Shift+F"))
        find_action.triggered.connect(self._focus_search)
        edit_menu.addAction(find_action)

        filter_action = QAction("Filter This Folder", self)
        filter_action.setShortcut(QKeySequence("Ctrl+F"))
        filter_action.triggered.connect(lambda: self._filter_bar.setFocus())
        edit_menu.addAction(filter_action)

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

        view_menu.addSeparator()
        group_menu = view_menu.addMenu("Group By")
        self._group_actions: dict[str, QAction] = {}
        group_keys = (
            GROUP_NONE,
            GROUP_KIND,
            GROUP_DATE_MODIFIED,
            GROUP_SIZE,
            GROUP_NAME,
        )
        for key in group_keys:
            action = QAction(GROUP_LABELS[key], self)
            action.setCheckable(True)
            action.setChecked(key == self._settings.group_by)
            action.triggered.connect(lambda _c=False, k=key: self._set_group_by(k))
            group_menu.addAction(action)
            self._group_actions[key] = action

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
        # Rebuilt on open so "Save Current Search" reflects the search field.
        self._smart_menu.aboutToShow.connect(self._rebuild_smart_menu)
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
        if (
            event.type() == QEvent.Type.KeyPress
            and event.key() == Qt.Key.Key_Escape
            and not self._preview.isVisible()
        ):
            # Escape leaves search results; the preview claims it first when open.
            tab = self._active_tab()
            if tab is not None and tab.view_stack.is_searching:
                self._stop_search()
                return True
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
        self._new_pane_action.setToolTip("New pane — side-by-side column (Ctrl+Alt+T)")
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

        # Recursive search is a separate field: the filter above is instant and
        # scoped to one folder, while this walks the tree on a worker thread.
        self._search_bar = QLineEdit()
        self._search_bar.setPlaceholderText("Search")
        self._search_bar.setClearButtonEnabled(True)
        self._search_bar.setMaximumWidth(200)
        self._search_bar.returnPressed.connect(self._start_search)
        toolbar.addWidget(self._search_bar)

        self._search_scope = QComboBox()
        self._search_scope.addItem("This Folder", SCOPE_HERE)
        self._search_scope.addItem("Home", SCOPE_EVERYWHERE)
        self._search_scope.setToolTip("Where to search")
        toolbar.addWidget(self._search_scope)

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
        self._status_bar.setSizeGripEnabled(False)
        self.setStatusBar(self._status_bar)

        self._count_label = QLabel("")
        self._space_label = _StatusField()
        self._size_label = _StatusField()
        self._refresh_label = _StatusField()

        self._status_bar.addPermanentWidget(self._count_label)
        for field in (self._space_label, self._size_label, self._refresh_label):
            self._status_bar.addPermanentWidget(field.divider)
            self._status_bar.addPermanentWidget(field)

    def _connect_signals(self) -> None:
        self._path_bar.navigate.connect(self._navigate_from_bar)
        self._sidebar.pathSelected.connect(
            lambda p: self.navigate_to(p, push_history=True)
        )
        self._sidebar.addFavoriteRequested.connect(self._add_favorite)
        self._sidebar.openInNewPaneRequested.connect(self._open_in_new_pane)
        self._sidebar.openInNewTabRequested.connect(self._open_in_new_tab)
        self._sidebar.removeFavoriteRequested.connect(self._remove_favorite)
        self._sidebar.filesDropped.connect(self._on_sidebar_files_dropped)
        self._sidebar.emptyTrashRequested.connect(self._empty_trash)
        self._sidebar.statusMessage.connect(self._show_status)

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
        # The pane's first tab already exists; later ones arrive via tabAdded.
        pane.tabAdded.connect(self._wire_tab)
        pane.tabActivated.connect(lambda _tab, p=pane: self._on_tab_activated(p))
        for tab in pane.tabs():
            self._wire_tab(tab)

    def _on_tab_activated(self, pane: BrowserPane) -> None:
        if pane is self._active_pane:
            self._sync_active_pane_ui()
            self._update_selection_status()

    def _new_tab(self) -> None:
        pane = self._active_pane
        if pane is None:
            return
        tab = pane.browser_tab
        pane.add_tab(tab.current_path or os.path.expanduser("~"))

    def _close_active_tab(self) -> None:
        if self._active_pane is not None:
            self._active_pane.close_current_tab()

    def _cycle_tab(self, step: int) -> None:
        if self._active_pane is not None:
            self._active_pane.select_next_tab(step)

    def _open_in_new_tab(self, path: str) -> None:
        normalized = expand_path(path)
        if not os.path.isdir(normalized):
            self._show_status(f"Not a directory: {normalized}")
            return
        pane = self._active_pane or self._add_pane(normalized)
        pane.add_tab(normalized)

    def _wire_tab(self, tab: BrowserTab) -> None:
        fl = tab.file_list
        fl.set_undo_stack(self._undo_stack)
        fl.set_confirm_permanent_delete(self._settings.confirm_permanent_delete)
        fl.set_settings(self._settings)
        vs = tab.view_stack
        fl.openInNewTabRequested.connect(self._open_in_new_tab)
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
        vs.revealRequested.connect(self._reveal_path)
        vs.statusMessage.connect(self._show_status)
        vs.searchFinished.connect(
            lambda count: self._show_status(
                f"{count} result{'s' if count != 1 else ''} found"
            )
        )
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
        pane.stop_watching()
        self._panes.remove(pane)
        pane.setParent(None)
        pane.deleteLater()
        self._set_active_pane(
            self._panes[-1] if self._active_pane is pane else self._active_pane
        )
        self._equalize_pane_sizes()

    def _close_active_pane(self) -> None:
        if self._active_pane is not None:
            self._close_pane(self._active_pane)

    def _set_active_pane(self, pane: BrowserPane) -> None:
        if pane not in self._panes:
            return
        self._active_pane = pane
        multi = len(self._panes) > 1
        for item in self._panes:
            item.set_active(item is pane)
            item.set_header_visible(multi)
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
        for tab in self._all_tabs():
            if os.path.normpath(path) == os.path.normpath(tab.current_path):
                tab.view_stack.set_current_directory(path)

    def _on_files_transferred(self, _source: str, _dest: str) -> None:
        for tab in self._all_tabs():
            tab.file_list._apply_sort()

    def _end_foreign_drag_sessions(self) -> None:
        for tab in self._all_tabs():
            tab.file_list.end_foreign_drag_session()

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
        for tab in self._all_tabs():
            tab.file_list._apply_sort()

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
        for tab in self._all_tabs():
            if tab.current_path:
                self._model.refresh_directory(tab.current_path)

    def _toggle_hidden_files(self) -> None:
        if hasattr(self, "_hidden_action") and self.sender() is self._hidden_action:
            show = self._hidden_action.isChecked()
        else:
            show = not self._settings.show_hidden
        self._settings.set_show_hidden(show)
        self._model.set_show_hidden(show)
        if hasattr(self, "_hidden_action"):
            self._hidden_action.setChecked(show)
        for tab in self._all_tabs():
            if tab.current_path:
                tab.view_stack.set_current_directory(tab.current_path)

    def _on_filter_changed(self, text: str) -> None:
        tab = self._active_tab()
        if tab:
            tab.view_stack.set_name_filter(text)

    def _focus_search(self) -> None:
        self._search_bar.setFocus()
        self._search_bar.selectAll()

    def _start_search(self) -> None:
        text = self._search_bar.text().strip()
        tab = self._active_tab()
        if tab is None:
            return
        if not text:
            tab.view_stack.end_search()
            return

        scope = self._search_scope.currentData() or SCOPE_HERE
        roots = search_roots(scope, tab.current_path, os.path.expanduser("~"))
        tab.view_stack.start_search(
            SearchQuery(
                text=text,
                roots=roots,
                include_hidden=self._settings.show_hidden,
            )
        )
        self._show_status(f"Searching for “{text}”…")

    def _stop_search(self) -> None:
        tab = self._active_tab()
        if tab is not None and tab.view_stack.is_searching:
            tab.view_stack.end_search()
            self._search_bar.clear()
            self._show_status("Search cleared")

    def _reveal_path(self, path: str) -> None:
        """Open the folder containing `path` and select it."""
        parent = os.path.dirname(path)
        if not os.path.isdir(parent):
            return
        tab = self._active_tab()
        if tab is None:
            return
        self._navigate_tab(tab, parent, push_history=True)
        QTimer.singleShot(120, lambda: tab.file_list.select_path(path))

    def _set_group_by(self, key: str) -> None:
        self._settings.set_group_by(key)
        for group_key, action in self._group_actions.items():
            action.setChecked(group_key == key)
        for tab in self._all_tabs():
            tab.file_list.set_group_by(key, persist=False)
        label = GROUP_LABELS.get(key, key)
        self._show_status(
            "Grouping off" if key == GROUP_NONE else f"Grouped by {label}"
        )

    def _set_view_mode(self, mode: str) -> None:
        self._settings.set_view_mode(mode)
        self._apply_view_mode()

    def _apply_view_mode(self) -> None:
        for tab in self._all_tabs():
            tab.view_stack.set_view_mode(
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
        folders = self._smart_folders.all()
        for folder in folders:
            act = QAction(folder.name, self)
            act.setToolTip(folder.describe())
            act.triggered.connect(
                lambda _c=False, f=folder: self._run_smart_folder(f)
            )
            self._smart_menu.addAction(act)
        if folders:
            self._smart_menu.addSeparator()
        edit_action = QAction("Edit Smart Folders…", self)
        edit_action.triggered.connect(self._edit_smart_folders)
        self._smart_menu.addAction(edit_action)

        save_action = QAction("Save Current Search…", self)
        # The menu bar is built before the toolbar, so the field may not exist yet.
        pending = getattr(self, "_search_bar", None)
        save_action.setEnabled(bool(pending is not None and pending.text().strip()))
        save_action.triggered.connect(self._save_current_search)
        self._smart_menu.addAction(save_action)

    def _run_smart_folder(self, folder: SmartFolder) -> None:
        tab = self._active_tab()
        if tab is None:
            return
        query = folder.to_query(tab.current_path, os.path.expanduser("~"))
        if not query.text.strip():
            self._show_status(f"{folder.name} has no search text")
            return
        self._search_bar.setText(folder.query)
        tab.view_stack.start_search(query)
        self._show_status(f"Searching: {folder.name}")

    def _edit_smart_folders(self) -> None:
        dialog = SmartFolderEditor(self._smart_folders, self)
        if dialog.exec() == SmartFolderEditor.DialogCode.Accepted:
            self._rebuild_smart_menu()
            self._show_status("Smart folders saved")

    def _save_current_search(self) -> None:
        text = self._search_bar.text().strip()
        if not text:
            return
        name, ok = QInputDialog.getText(
            self, "Save Search", "Smart folder name:", text=text
        )
        if not ok or not name.strip():
            return
        self._smart_folders.add(
            SmartFolder(
                name=name.strip(),
                query=text,
                scope=self._search_scope.currentData() or SCOPE_HERE,
                include_hidden=self._settings.show_hidden,
            )
        )
        self._rebuild_smart_menu()
        self._show_status(f"Saved smart folder “{name.strip()}”")

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
        dialog = ConnectServerDialog(self._server_store, self)
        if dialog.exec() != ConnectServerDialog.DialogCode.Accepted:
            return
        point = dialog.mount_point
        if not point:
            return
        self._mount_service.reload(force=True)
        self._sidebar.reload()
        self.navigate_to(point, push_history=True)
        name = os.path.basename(point) or point
        if dialog.partial_error:
            self._show_status(f"Connected to {name}, but {dialog.partial_error}")
        else:
            self._show_status(f"Connected to {name}")

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
        for tab in self._all_tabs():
            tab.file_list.set_confirm_permanent_delete(
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
        self._save_window_geometry()
        for pane in self._panes:
            pane.stop_watching()
        self._model.folder_size_calculator().flush()
        super().closeEvent(event)

    def _save_window_geometry(self) -> None:
        geometry = bytes(self.saveGeometry().toBase64()).decode("ascii")
        self._settings.set_window_geometry(geometry)

    def _restore_window_geometry(self) -> bool:
        """Return True when a saved geometry was applied."""
        saved = self._settings.window_geometry
        if not saved:
            return False
        try:
            data = QByteArray.fromBase64(saved.encode("ascii"))
        except (UnicodeEncodeError, ValueError):
            return False
        if data.isEmpty():
            return False
        return self.restoreGeometry(data)
