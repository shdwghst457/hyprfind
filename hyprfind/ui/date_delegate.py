"""Column delegate for adaptive date display."""

from __future__ import annotations

from PyQt6.QtWidgets import QStyleOptionViewItem

from hyprfind.core.sort_proxy import FileSortProxyModel
from hyprfind.ui.list_delegate import DropHighlightDelegate
from hyprfind.utils.formatting import format_date_modified


class DateModifiedDelegate(DropHighlightDelegate):
    def __init__(
        self, proxy: FileSortProxyModel, view, parent=None
    ) -> None:
        super().__init__(view, parent)
        self._proxy = proxy

    def initStyleOption(
        self, option: QStyleOptionViewItem, index
    ) -> None:
        super().initStyleOption(option, index)
        source = self._proxy.mapToSource(index)
        if not source.isValid():
            return
        model = self._proxy.sourceModel()
        if model is None or not hasattr(model, "lastModified"):
            return
        width = option.rect.width() if option.rect.isValid() else 168
        option.text = format_date_modified(model.lastModified(source), width)
