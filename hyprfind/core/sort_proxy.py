"""Proxy model for reliable QFileSystemModel column sorting."""

from __future__ import annotations

from PyQt6.QtCore import Qt, QSortFilterProxyModel
from PyQt6.QtGui import QFileSystemModel

from hyprfind.core.fs_columns import DATE_MODIFIED, NAME, SIZE, TYPE
from hyprfind.core.grouping import GROUP_NONE, group_for


class FileSortProxyModel(QSortFilterProxyModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._name_filter = ""
        self._group_by = GROUP_NONE
        if hasattr(self, "setRecursiveSortingEnabled"):
            self.setRecursiveSortingEnabled(True)

    def set_name_filter(self, text: str) -> None:
        self._name_filter = text.strip().casefold()
        self.invalidateFilter()

    def set_group_by(self, key: str) -> None:
        if key == self._group_by:
            return
        self._group_by = key
        self.invalidate()
        self.sort(self.sortColumn(), self.sortOrder())

    @property
    def group_by(self) -> str:
        return self._group_by

    def group_of(self, proxy_index) -> tuple[int, str]:
        """Group of a row, addressed in proxy coordinates."""
        return self._group_for_source(self.mapToSource(proxy_index))

    def _group_for_source(self, source_index) -> tuple[int, str]:
        if self._group_by == GROUP_NONE or not source_index.isValid():
            return (0, "")
        source: QFileSystemModel = self.sourceModel()
        size = (
            source.item_byte_size(source_index)
            if hasattr(source, "item_byte_size")
            else source.size(source_index)
        )
        modified = source.lastModified(source_index)
        return group_for(
            key=self._group_by,
            name=source.fileName(source_index),
            is_dir=source.isDir(source_index),
            kind=source.type(source_index),
            size=size or 0,
            mtime=modified.toSecsSinceEpoch() if modified.isValid() else 0.0,
        )

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

        if self._group_by != GROUP_NONE:
            # Grouping outranks the sort column so buckets stay contiguous; the
            # column then orders items inside each bucket.
            left_group = self._group_for_source(left)
            right_group = self._group_for_source(right)
            if left_group != right_group:
                if self.sortOrder() == Qt.SortOrder.DescendingOrder:
                    # Qt reverses the result of lessThan for a descending sort,
                    # so pre-invert to keep group order stable either way.
                    return left_group > right_group
                return left_group < right_group

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
