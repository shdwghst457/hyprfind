"""Application file clipboard for cut/copy/paste."""

from __future__ import annotations

import os

from PyQt6.QtCore import QMimeData, QUrl
from PyQt6.QtGui import QClipboard
from PyQt6.QtWidgets import QApplication

MIME_CUT = "application/x-hyprfind-cut"


class FileClipboard:
    """Singleton-style file clipboard tracking cut vs copy."""

    _instance: FileClipboard | None = None

    def __init__(self) -> None:
        self._paths: list[str] = []
        self._cut = False

    @classmethod
    def instance(cls) -> FileClipboard:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @property
    def paths(self) -> list[str]:
        return list(self._paths)

    @property
    def is_cut(self) -> bool:
        return self._cut and bool(self._paths)

    def copy(self, paths: list[str]) -> None:
        self._paths = [os.path.abspath(p) for p in paths if p]
        self._cut = False
        self._sync_qt_clipboard()

    def cut(self, paths: list[str]) -> None:
        self._paths = [os.path.abspath(p) for p in paths if p]
        self._cut = True
        self._sync_qt_clipboard()

    def clear(self) -> None:
        self._paths = []
        self._cut = False

    def has_content(self) -> bool:
        return bool(self._paths)

    def _sync_qt_clipboard(self) -> None:
        app = QApplication.instance()
        if app is None:
            return
        mime = QMimeData()
        urls = [QUrl.fromLocalFile(p) for p in self._paths]
        mime.setUrls(urls)
        if self._cut:
            mime.setData(MIME_CUT, b"1")
        app.clipboard().setMimeData(mime, QClipboard.Mode.Clipboard)

    def read_from_system(self) -> tuple[list[str], bool]:
        """Read paths from Qt clipboard; returns (paths, is_cut)."""
        app = QApplication.instance()
        if app is None:
            return [], False
        mime = app.clipboard().mimeData()
        if mime is None or not mime.hasUrls():
            return [], False
        paths = [
            url.toLocalFile()
            for url in mime.urls()
            if url.isLocalFile() and url.toLocalFile()
        ]
        is_cut = mime.hasFormat(MIME_CUT)
        self._paths = paths
        self._cut = is_cut
        return paths, is_cut
