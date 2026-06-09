"""Spacebar Quick Look overlay."""

from __future__ import annotations

import mimetypes
import os
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QLabel,
    QPlainTextEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}
TEXT_EXTENSIONS = {
    ".txt", ".md", ".py", ".json", ".log", ".yaml", ".yml", ".toml",
    ".rs", ".c", ".h", ".cpp", ".js", ".ts", ".sh", ".xml", ".csv",
}
PDF_EXTENSIONS = {".pdf"}
MAX_TEXT_BYTES = 512 * 1024


class PreviewOverlay(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Dialog
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setModal(False)
        self.resize(640, 480)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(12, 12, 12, 12)
        self._content: QWidget | None = None
        self._pdf_document = None
        self._pdf_view = None
        self._current_path: str | None = None
        self._all_paths: list[str] = []
        self._path_index = 0

        self.setObjectName("PreviewOverlay")
        self.setStyleSheet(
            "#PreviewOverlay { background-color: #2a2a2a; border: 1px solid #4a4a4a; "
            "border-radius: 8px; }"
        )

    @property
    def current_path(self) -> str | None:
        return self._current_path

    def toggle(self, path: str, paths: list[str] | None = None) -> None:
        if self.isVisible() and self._current_path == path:
            self.hide()
            self._current_path = None
            return
        self.show_preview(path, paths)

    def show_preview(self, path: str, paths: list[str] | None = None) -> None:
        self._all_paths = paths or [path]
        try:
            self._path_index = self._all_paths.index(path)
        except ValueError:
            self._path_index = 0
        self._clear_content()
        self._current_path = path
        preview_type = self._detect_type(path)

        if preview_type == "image":
            self._show_image(path)
        elif preview_type == "text":
            self._show_text(path)
        elif preview_type == "pdf":
            self._show_pdf(path)
        else:
            self._show_metadata(path)

        self._center_on_parent()
        self.show()
        self.raise_()
        self.activateWindow()

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_Space):
            self.hide()
            self._current_path = None
            event.accept()
            return
        if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Up) and len(self._all_paths) > 1:
            self._path_index = (self._path_index - 1) % len(self._all_paths)
            self.show_preview(self._all_paths[self._path_index], self._all_paths)
            event.accept()
            return
        if event.key() in (Qt.Key.Key_Right, Qt.Key.Key_Down) and len(self._all_paths) > 1:
            self._path_index = (self._path_index + 1) % len(self._all_paths)
            self.show_preview(self._all_paths[self._path_index], self._all_paths)
            event.accept()
            return
        super().keyPressEvent(event)

    def _clear_content(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self._pdf_document = None
        self._pdf_view = None
        self._content = None

    def _detect_type(self, path: str) -> str:
        ext = Path(path).suffix.lower()
        if ext in IMAGE_EXTENSIONS:
            return "image"
        if ext in TEXT_EXTENSIONS:
            return "text"
        if ext in PDF_EXTENSIONS:
            return "pdf"
        mime, _ = mimetypes.guess_type(path)
        if mime:
            if mime.startswith("image/"):
                return "image"
            if mime.startswith("text/"):
                return "text"
            if mime == "application/pdf":
                return "pdf"
        return "metadata"

    def _show_image(self, path: str) -> None:
        label = QLabel()
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pixmap = QPixmap(path)
        if pixmap.isNull():
            self._show_metadata(path)
            return
        max_size = QSize(600, 420)
        label.setPixmap(
            pixmap.scaled(
                max_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(label)
        self._layout.addWidget(scroll)
        self._content = scroll

    def _show_text(self, path: str) -> None:
        editor = QPlainTextEdit()
        editor.setReadOnly(True)
        editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        try:
            with open(path, "rb") as fh:
                data = fh.read(MAX_TEXT_BYTES)
            text = data.decode("utf-8", errors="replace")
            if os.path.getsize(path) > MAX_TEXT_BYTES:
                text += "\n\n[... truncated ...]"
            editor.setPlainText(text)
        except OSError as exc:
            editor.setPlainText(f"Could not read file: {exc}")
        self._layout.addWidget(editor)
        self._content = editor

    def _show_pdf(self, path: str) -> None:
        try:
            from PyQt6.QtPdf import QPdfDocument
            from PyQt6.QtPdfWidgets import QPdfView
        except ImportError:
            self._show_metadata(path, note="PDF module not available")
            return

        self._pdf_document = QPdfDocument(self)
        status = self._pdf_document.load(path)
        if status != QPdfDocument.Error.None_:
            self._show_metadata(path, note="Could not load PDF")
            self._pdf_document = None
            return

        self._pdf_view = QPdfView(self)
        self._pdf_view.setDocument(self._pdf_document)
        self._pdf_view.setPageMode(QPdfView.PageMode.MultiPage)
        self._layout.addWidget(self._pdf_view)
        self._content = self._pdf_view

    def _show_metadata(self, path: str, note: str = "") -> None:
        label = QLabel()
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        try:
            stat = os.stat(path)
            mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            size = stat.st_size
            mime, _ = mimetypes.guess_type(path)
        except OSError as exc:
            label.setText(f"Error: {exc}")
            self._layout.addWidget(label)
            return

        lines = [
            Path(path).name,
            "",
            f"Path: {path}",
            f"Size: {size:,} bytes",
            f"Modified: {mtime}",
            f"Type: {mime or 'unknown'}",
        ]
        if note:
            lines.extend(["", note])
        label.setText("\n".join(lines))
        self._layout.addWidget(label)
        self._content = label

    def _center_on_parent(self) -> None:
        parent = self.parentWidget()
        if parent:
            geo = parent.geometry()
            x = geo.x() + (geo.width() - self.width()) // 2
            y = geo.y() + (geo.height() - self.height()) // 2
            self.move(x, y)
