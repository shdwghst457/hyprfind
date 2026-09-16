"""Column delegate for adaptive date display."""

from __future__ import annotations

from PyQt6.QtGui import QFontMetrics
from PyQt6.QtWidgets import QStyleOptionViewItem

from hyprfind.core.sort_proxy import FileSortProxyModel
from hyprfind.ui.list_delegate import DropHighlightDelegate
from hyprfind.utils.formatting import DATE_TIER_SAMPLES, date_modified_tiers

# Cell padding from the stylesheet plus the style's own text margin.
_TEXT_INSET = 22


def _tier_for_width(available: int, metrics: QFontMetrics) -> int:
    """Most detailed tier whose worst-case text fits in `available` pixels.

    Measuring the tier's widest possible string (rather than this row's text)
    keeps every row in a column on the same format.
    """
    for tier, sample in enumerate(DATE_TIER_SAMPLES):
        if metrics.horizontalAdvance(sample) <= available:
            return tier
    return len(DATE_TIER_SAMPLES) - 1


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
        tier = _tier_for_width(width - _TEXT_INSET, QFontMetrics(option.font))
        option.text = date_modified_tiers(model.lastModified(source))[tier]
