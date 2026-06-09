"""Get Info panel for files and folders."""

from __future__ import annotations

import os
import stat
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QFormLayout,
    QLabel,
    QVBoxLayout,
)

from hyprfind.utils.formatting import format_bytes


class InfoPanel(QDialog):
    def __init__(self, path: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Get Info")
        self.setMinimumWidth(380)
        layout = QVBoxLayout(self)
        name = os.path.basename(path.rstrip(os.sep)) or path
        title = QLabel(name)
        title.setStyleSheet("font-size: 16px; font-weight: 600;")
        layout.addWidget(title)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        try:
            st = os.stat(path, follow_symlinks=False)
            is_link = os.path.islink(path)
            is_dir = os.path.isdir(path) and not is_link
            kind = "Alias" if is_link else ("Folder" if is_dir else "Document")
            form.addRow("Kind:", QLabel(kind))
            if is_dir:
                size_text = "—"
            else:
                size_text = format_bytes(st.st_size)
            form.addRow("Size:", QLabel(size_text))
            form.addRow(
                "Created:",
                QLabel(datetime.fromtimestamp(st.st_ctime).strftime("%Y-%m-%d %H:%M")),
            )
            form.addRow(
                "Modified:",
                QLabel(datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")),
            )
            mode = stat.filemode(st.st_mode)
            form.addRow("Permissions:", QLabel(mode))
            if is_link:
                target = os.readlink(path)
                form.addRow("Original:", QLabel(target))
        except OSError as exc:
            form.addRow("Error:", QLabel(str(exc)))
        form.addRow("Where:", QLabel(path))
        tags = self._read_tags(path)
        if tags:
            form.addRow("Tags:", QLabel(", ".join(tags)))
        layout.addLayout(form)

    @staticmethod
    def _read_tags(path: str) -> list[str]:
        tags: list[str] = []
        try:
            names = os.listxattr(path)
            for name in names:
                if name.startswith(b"user.") or name.startswith(b"trusted."):
                    decoded = name.decode("utf-8", errors="replace")
                    if "tag" in decoded.lower():
                        raw = os.getxattr(path, name)
                        tags.append(raw.decode("utf-8", errors="replace"))
        except (OSError, AttributeError):
            pass
        return tags
