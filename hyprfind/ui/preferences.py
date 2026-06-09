"""Preferences dialog."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QSpinBox,
    QVBoxLayout,
)

from hyprfind.core.settings import AppSettings


class PreferencesDialog(QDialog):
    def __init__(self, settings: AppSettings, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self._settings = settings
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._hidden = QCheckBox("Show hidden files by default")
        self._hidden.setChecked(settings.show_hidden)
        form.addRow(self._hidden)

        self._confirm = QCheckBox("Confirm before permanent delete")
        self._confirm.setChecked(settings.confirm_permanent_delete)
        form.addRow(self._confirm)

        self._icon_size = QSpinBox()
        self._icon_size.setRange(16, 128)
        self._icon_size.setValue(settings.icon_size)
        form.addRow("Icon size:", self._icon_size)

        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save(self) -> None:
        self._settings.show_hidden = self._hidden.isChecked()
        self._settings.confirm_permanent_delete = self._confirm.isChecked()
        self._settings.set_icon_size(self._icon_size.value())
        self.accept()
