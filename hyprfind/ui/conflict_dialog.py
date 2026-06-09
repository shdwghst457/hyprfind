"""Copy/move conflict resolution dialog."""

from __future__ import annotations

import os

from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
)


class ConflictAction:
    STOP = "stop"
    REPLACE = "replace"
    KEEP_BOTH = "keep_both"
    SKIP = "skip"


class ConflictDialog(QDialog):
    def __init__(
        self,
        source: str,
        destination: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("File Already Exists")
        self._action = ConflictAction.STOP
        self._apply_all = False

        layout = QVBoxLayout(self)
        src_name = os.path.basename(source)
        dest_name = os.path.basename(destination)
        layout.addWidget(
            QLabel(
                f'"{src_name}" already exists in this location.\n'
                f"Do you want to replace it with the one you're moving?"
            )
        )
        layout.addWidget(QLabel(f"Existing: {destination}"))

        self._apply_checkbox = QCheckBox("Apply to all")
        layout.addWidget(self._apply_checkbox)

        buttons = QDialogButtonBox()
        stop_btn = buttons.addButton("Stop", QDialogButtonBox.ButtonRole.RejectRole)
        keep_btn = buttons.addButton(
            "Keep Both", QDialogButtonBox.ButtonRole.ActionRole
        )
        replace_btn = buttons.addButton(
            "Replace", QDialogButtonBox.ButtonRole.AcceptRole
        )
        stop_btn.clicked.connect(lambda: self._finish(ConflictAction.STOP))
        keep_btn.clicked.connect(lambda: self._finish(ConflictAction.KEEP_BOTH))
        replace_btn.clicked.connect(lambda: self._finish(ConflictAction.REPLACE))
        layout.addWidget(buttons)

    def _finish(self, action: str) -> None:
        self._action = action
        self._apply_all = self._apply_checkbox.isChecked()
        self.accept()

    @property
    def action(self) -> str:
        return self._action

    @property
    def apply_to_all(self) -> bool:
        return self._apply_all
