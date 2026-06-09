"""Shared list delegates for file rows."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QStyledItemDelegate

from hyprfind.core.file_ops import TransferOp
from hyprfind.ui.drag_support import highlight_colors


class DropHighlightDelegate(QStyledItemDelegate):
    def __init__(self, view, parent=None) -> None:
        super().__init__(parent)
        self._view = view

    def paint(self, painter: QPainter, option, index) -> None:
        view = self._view
        if view is not None:
            rect = option.rect

            if view._is_spring_open_row(index):
                painter.save()
                painter.fillRect(rect, QColor(88, 148, 220, 52))
                painter.restore()

            if view._is_spring_hover_row(index) and not view._is_drop_target_row(
                index
            ):
                painter.save()
                painter.fillRect(rect, QColor(110, 168, 235, 38))
                accent = rect.adjusted(0, 3, 0, -3)
                accent.setWidth(3)
                painter.fillRect(accent, QColor(130, 190, 255, 200))
                painter.restore()

            if view._is_drop_target_row(index):
                painter.save()
                operation = getattr(view, "_drag_op", TransferOp.MOVE)
                fill, border = highlight_colors(operation)
                inner = rect.adjusted(2, 2, -2, -2)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(fill)
                painter.drawRoundedRect(inner, 6, 6)
                painter.setPen(QPen(border, 2))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(inner, 6, 6)
                painter.restore()

        super().paint(painter, option, index)
