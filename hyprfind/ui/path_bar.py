"""Breadcrumb path bar with editable fallback."""

from __future__ import annotations

import os

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QWidget,
)


class PathBar(QWidget):
    navigate = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._path = ""
        self._edit_mode = False
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(2)

        self._crumb_container = QWidget()
        self._crumb_layout = QHBoxLayout(self._crumb_container)
        self._crumb_layout.setContentsMargins(0, 0, 0, 0)
        self._crumb_layout.setSpacing(2)
        self._layout.addWidget(self._crumb_container, 1)

        self._editor = QLineEdit()
        self._editor.setPlaceholderText("Path")
        self._editor.returnPressed.connect(self._on_editor_return)
        self._editor.setVisible(False)
        self._layout.addWidget(self._editor, 1)

    def set_path(self, path: str) -> None:
        self._path = path
        if self._edit_mode:
            self._editor.setText(path)
            return
        self._rebuild_crumbs(path)

    def _rebuild_crumbs(self, path: str) -> None:
        while self._crumb_layout.count():
            item = self._crumb_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not path:
            return
        parts: list[tuple[str, str]] = []
        normalized = os.path.abspath(os.path.expanduser(path))
        if normalized == "/":
            parts = [("/", "/")]
        else:
            head, tail = os.path.split(normalized)
            segments = []
            current = normalized
            while current and current != "/":
                segments.append(current)
                current = os.path.dirname(current)
            segments.reverse()
            for seg in segments:
                label = os.path.basename(seg.rstrip("/")) or seg
                parts.append((label, seg))
        for i, (label, full) in enumerate(parts):
            if i > 0:
                sep = QPushButton("›")
                sep.setFlat(True)
                sep.setEnabled(False)
                sep.setFixedWidth(16)
                self._crumb_layout.addWidget(sep)
            btn = QPushButton(label)
            btn.setFlat(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _checked=False, p=full: self.navigate.emit(p))
            self._crumb_layout.addWidget(btn)
        self._crumb_layout.addStretch(1)

    def _on_editor_return(self) -> None:
        text = self._editor.text().strip()
        if text:
            self.navigate.emit(text)
        self._set_edit_mode(False)

    def _set_edit_mode(self, editing: bool) -> None:
        self._edit_mode = editing
        self._crumb_container.setVisible(not editing)
        self._editor.setVisible(editing)
        if editing:
            self._editor.setText(self._path)
            self._editor.setFocus()
            self._editor.selectAll()

    def mouseDoubleClickEvent(self, event) -> None:
        self._set_edit_mode(True)
        super().mouseDoubleClickEvent(event)

    def focus_editor(self) -> None:
        self._set_edit_mode(True)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape and self._edit_mode:
            self._set_edit_mode(False)
            event.accept()
            return
        super().keyPressEvent(event)
