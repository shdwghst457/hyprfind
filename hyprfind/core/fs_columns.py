"""QFileSystemModel column indices (stable across PyQt6 versions)."""

from __future__ import annotations

from PyQt6.QtGui import QFileSystemModel


def _resolve(name: str, fallback: int) -> int:
    column_enum = getattr(QFileSystemModel, "Column", None)
    if column_enum is not None and hasattr(column_enum, name):
        return int(getattr(column_enum, name))
    if hasattr(QFileSystemModel, name):
        return int(getattr(QFileSystemModel, name))
    return fallback


NAME = _resolve("Name", 0)
SIZE = _resolve("Size", 1)
TYPE = _resolve("Type", 2)
DATE_MODIFIED = _resolve("DateModified", 3)
