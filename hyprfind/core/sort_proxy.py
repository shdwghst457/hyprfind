"""Proxy model for reliable QFileSystemModel column sorting."""

from __future__ import annotations

from PyQt6.QtCore import QSortFilterProxyModel
from PyQt6.QtGui import QFileSystemModel

from hyprfind.core.fs_columns import DATE_MODIFIED, NAME, SIZE, TYPE


class FileSortProxyModel(QSortFilterProxyModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._name_filter = ""
        if hasattr(self, "setRecursiveSortingEnabled"):
            self.setRecursiveSortingEnabled(True)

    def set_name_filter(self, text: str) -> None:
        self._name_filter = text.strip().casefold()
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent) -> bool:
        if not self._name_filter:
            return True
        source: QFileSystemModel = self.sourceModel()
        index = source.index(source_row, 0, source_parent)
        if not index.isValid():
            return True
        return self._name_filter in source.fileName(index).casefold()

    def lessThan(self, left, right) -> bool:
        source: QFileSystemModel = self.sourceModel()
        column = self.sortColumn()

        left_dir = source.isDir(left)
        right_dir = source.isDir(right)
        if left_dir != right_dir:
            return left_dir and not right_dir

        if column == NAME:
            left_key = source.fileName(left).casefold()
            right_key = source.fileName(right).casefold()
        elif column == SIZE:
            if hasattr(source, "item_byte_size"):
                left_key = source.item_byte_size(left)
                right_key = source.item_byte_size(right)
            else:
                left_key = source.size(left)
                right_key = source.size(right)
        elif column == TYPE:
            left_key = source.type(left).casefold()
            right_key = source.type(right).casefold()
        elif column == DATE_MODIFIED:
            left_key = source.lastModified(left)
            right_key = source.lastModified(right)
        else:
            return super().lessThan(left, right)

        if left_key == right_key:
            return source.fileName(left).casefold() < source.fileName(right).casefold()
        return left_key < right_key
