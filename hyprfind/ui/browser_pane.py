"""Side-by-side browser pane with a compact header and its own tabs."""

from __future__ import annotations

from PyQt6.QtCore import QEvent, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QStackedWidget,
    QTabBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from hyprfind.core.model import HyprFileSystemModel
from hyprfind.core.mounts import MountService
from hyprfind.ui.browser_tab import BrowserTab


class BrowserPane(QWidget):
    activated = pyqtSignal()
    closeRequested = pyqtSignal()
    tabAdded = pyqtSignal(object)
    tabActivated = pyqtSignal(object)

    def __init__(
        self,
        model: HyprFileSystemModel,
        mount_service: MountService,
        initial_path: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("browserPane")
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.setMinimumWidth(280)

        self._model = model
        self._mount_service = mount_service
        self._tabs: list[BrowserTab] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._header = QWidget(self)
        self._header.setObjectName("browserPaneHeader")
        header_layout = QHBoxLayout(self._header)
        header_layout.setContentsMargins(10, 3, 4, 3)
        header_layout.setSpacing(4)

        self._title = QLabel(self._header)
        self._title.setObjectName("browserPaneTitle")
        self._title.setTextFormat(Qt.TextFormat.PlainText)
        self._title.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        header_layout.addWidget(self._title, 1)

        self._close_button = QToolButton(self._header)
        self._close_button.setObjectName("browserPaneClose")
        self._close_button.setText("×")
        self._close_button.setToolTip("Close pane")
        self._close_button.setAutoRaise(True)
        self._close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close_button.clicked.connect(self.closeRequested.emit)
        header_layout.addWidget(self._close_button)

        layout.addWidget(self._header)

        self._tab_bar = QTabBar(self)
        self._tab_bar.setObjectName("paneTabBar")
        self._tab_bar.setExpanding(False)
        self._tab_bar.setTabsClosable(True)
        self._tab_bar.setDrawBase(False)
        self._tab_bar.setElideMode(Qt.TextElideMode.ElideRight)
        self._tab_bar.setMovable(True)
        self._tab_bar.currentChanged.connect(self._on_tab_changed)
        self._tab_bar.tabCloseRequested.connect(self.close_tab)
        self._tab_bar.tabMoved.connect(self._on_tab_moved)
        self._tab_bar.hide()
        layout.addWidget(self._tab_bar)

        self._stack = QStackedWidget(self)
        layout.addWidget(self._stack, 1)

        self.add_tab(initial_path)
        self.update_title()
        self.set_active(False)

    # ---------------------------------------------------------------- tab access

    @property
    def browser_tab(self) -> BrowserTab:
        """The visible tab. Most of the app only cares about this one."""
        return self._tabs[self._stack.currentIndex()]

    def tabs(self) -> list[BrowserTab]:
        return list(self._tabs)

    def tab_count(self) -> int:
        return len(self._tabs)

    def index_of(self, tab: BrowserTab) -> int:
        return self._tabs.index(tab) if tab in self._tabs else -1

    # --------------------------------------------------------------- tab editing

    def add_tab(self, path: str) -> BrowserTab:
        tab = BrowserTab(self._model, self._mount_service, path, self)
        tab.file_list.installEventFilter(self)
        self._tabs.append(tab)
        self._stack.addWidget(tab)
        self._tab_bar.blockSignals(True)
        index = self._tab_bar.addTab(tab.tab_label())
        self._tab_bar.blockSignals(False)
        self._update_tab_bar_visibility()
        self.tabAdded.emit(tab)
        self.set_current_index(index)
        return tab

    def close_tab(self, index: int) -> None:
        """Close one tab; closing the last one closes the whole pane."""
        if not 0 <= index < len(self._tabs):
            return
        if len(self._tabs) == 1:
            self.closeRequested.emit()
            return

        tab = self._tabs.pop(index)
        tab.stop_watching()
        self._stack.removeWidget(tab)
        self._tab_bar.blockSignals(True)
        self._tab_bar.removeTab(index)
        self._tab_bar.blockSignals(False)
        tab.deleteLater()

        new_index = min(index, len(self._tabs) - 1)
        self._update_tab_bar_visibility()
        self.set_current_index(new_index)

    def close_current_tab(self) -> None:
        self.close_tab(self._stack.currentIndex())

    def set_current_index(self, index: int) -> None:
        if not 0 <= index < len(self._tabs):
            return
        self._stack.setCurrentIndex(index)
        if self._tab_bar.currentIndex() != index:
            self._tab_bar.blockSignals(True)
            self._tab_bar.setCurrentIndex(index)
            self._tab_bar.blockSignals(False)
        self.update_title()
        self.tabActivated.emit(self._tabs[index])

    def select_next_tab(self, step: int = 1) -> None:
        if len(self._tabs) < 2:
            return
        count = len(self._tabs)
        self.set_current_index((self._stack.currentIndex() + step) % count)

    def _on_tab_changed(self, index: int) -> None:
        self.set_current_index(index)
        self.activated.emit()

    def _on_tab_moved(self, from_index: int, to_index: int) -> None:
        # Keep the stack and the label order in step with the dragged tab bar.
        tab = self._tabs.pop(from_index)
        self._tabs.insert(to_index, tab)
        self._stack.removeWidget(tab)
        self._stack.insertWidget(to_index, tab)
        self._stack.setCurrentIndex(self._tab_bar.currentIndex())

    def _update_tab_bar_visibility(self) -> None:
        # A single tab needs no tab bar, matching Finder.
        self._tab_bar.setVisible(len(self._tabs) > 1)

    # ----------------------------------------------------------------- appearance

    def update_title(self) -> None:
        if not self._tabs:
            return
        current = self.browser_tab
        self._title.setText(current.tab_label())
        index = self._stack.currentIndex()
        if 0 <= index < self._tab_bar.count():
            self._tab_bar.setTabText(index, current.tab_label())
            self._tab_bar.setTabToolTip(index, current.current_path)

    def set_active(self, active: bool) -> None:
        self._header.setProperty("active", active)
        self._header.style().unpolish(self._header)
        self._header.style().polish(self._header)

    def set_header_visible(self, visible: bool) -> None:
        """With a single pane there is nothing to label or close, so hide it."""
        self._header.setVisible(visible)

    def stop_watching(self) -> None:
        for tab in self._tabs:
            tab.stop_watching()

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Type.FocusIn and any(
            obj is tab.file_list for tab in self._tabs
        ):
            self.activated.emit()
        return super().eventFilter(obj, event)

    def mousePressEvent(self, event) -> None:
        self.activated.emit()
        super().mousePressEvent(event)
