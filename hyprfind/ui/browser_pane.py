"""Side-by-side browser pane with a compact header."""

from __future__ import annotations

from PyQt6.QtCore import QEvent, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSizePolicy,
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

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._header = QWidget(self)
        self._header.setObjectName("browserPaneHeader")
        header_layout = QHBoxLayout(self._header)
        header_layout.setContentsMargins(10, 6, 6, 6)
        header_layout.setSpacing(6)

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
        self._close_button.setToolTip("Close pane (Ctrl+W)")
        self._close_button.setAutoRaise(True)
        self._close_button.clicked.connect(self.closeRequested.emit)
        header_layout.addWidget(self._close_button)

        layout.addWidget(self._header)

        self._browser = BrowserTab(model, mount_service, initial_path, self)
        self._browser.file_list.installEventFilter(self)
        layout.addWidget(self._browser, 1)

        self.update_title()
        self.set_active(False)

    @property
    def browser_tab(self) -> BrowserTab:
        return self._browser

    def update_title(self) -> None:
        self._title.setText(self._browser.tab_label())

    def set_active(self, active: bool) -> None:
        self._header.setProperty("active", active)
        self._header.style().unpolish(self._header)
        self._header.style().polish(self._header)

    def eventFilter(self, obj, event) -> bool:
        if obj is self._browser.file_list and event.type() == QEvent.Type.FocusIn:
            self.activated.emit()
        return super().eventFilter(obj, event)

    def mousePressEvent(self, event) -> None:
        self.activated.emit()
        super().mousePressEvent(event)
