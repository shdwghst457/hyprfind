"""Shared list delegates for file rows."""

from __future__ import annotations

import os

from PyQt6.QtCore import QRect, Qt, QTimer
from PyQt6.QtGui import QColor, QFileSystemModel, QFont, QPainter, QPen
from PyQt6.QtWidgets import QLineEdit, QStyledItemDelegate, QStyleOptionViewItem

from hyprfind.core.file_ops import TransferOp
from hyprfind.core.grouping import GROUP_NONE
from hyprfind.core.model import CUT_ITEM_OPACITY, TAGS_ROLE
from hyprfind.core.tags import color_for
from hyprfind.ui.drag_support import highlight_colors


def _is_cut(index) -> bool:
    """True when the row is on the clipboard as a cut."""
    model = index.model()
    while model is not None:
        checker = getattr(model, "is_cut_index", None)
        if checker is not None:
            return bool(checker(index))
        # Walk through proxies to reach the file system model.
        map_to_source = getattr(model, "mapToSource", None)
        if map_to_source is None:
            return False
        index = map_to_source(index)
        model = index.model()
    return False


# Set on a rename editor once the user types, so a directory refresh that
# re-pushes data into the editor does not fight their cursor.
_TYPED_PROPERTY = "hyprfindUserTyped"


def _apply_selection(editor, length: int) -> None:
    """Select the first ``length`` characters, unless the user has begun typing."""
    try:
        if editor.property(_TYPED_PROPERTY) or not editor.text():
            return
        editor.setSelection(0, length)
    except RuntimeError:
        # The editor closed before the deferred call ran.
        return


def _rename_selection_length(index, name: str) -> int:
    """How much of a name to preselect: the stem, or all of a folder name."""
    if not name:
        return 0
    path = index.data(QFileSystemModel.Roles.FilePathRole)
    if isinstance(path, str) and path and os.path.isdir(path):
        return len(name)
    stem = os.path.splitext(name)[0]
    # A dotfile with no further extension (".bashrc") has an empty stem.
    return len(stem) or len(name)


GROUP_HEADER_HEIGHT = 22
GROUP_HEADER_COLOR = QColor("#8e8e93")
GROUP_RULE_COLOR = QColor("#3a3a3f")

TAG_DOT_SIZE = 8
TAG_DOT_GAP = 3
# Beyond a handful the dots stop being readable and start eating the filename.
MAX_TAG_DOTS = 4


class DropHighlightDelegate(QStyledItemDelegate):
    def __init__(self, view, parent=None) -> None:
        super().__init__(parent)
        self._view = view

    # ------------------------------------------------------------------- editing

    def createEditor(self, parent, option, index):
        editor = super().createEditor(parent, option, index)
        if isinstance(editor, QLineEdit):
            # textEdited fires only for typing, never for setText, so it marks
            # the point after which the selection must be left alone.
            editor.textEdited.connect(
                lambda _text, ed=editor: ed.setProperty(_TYPED_PROPERTY, True)
            )
        return editor

    def setEditorData(self, editor, index) -> None:
        super().setEditorData(editor, index)
        if not isinstance(editor, QLineEdit):
            return
        if editor.property(_TYPED_PROPERTY):
            return
        # Refreshing the directory makes the view push data into the open editor
        # again, and setText clears the selection, so it has to be reapplied.
        # Deferred because the view selects the whole line right after this
        # returns, which would otherwise win.
        length = _rename_selection_length(index, editor.text())
        QTimer.singleShot(0, lambda ed=editor: _apply_selection(ed, length))

    # ------------------------------------------------------------- group headers

    @staticmethod
    def _heading_for_row(index) -> str | None:
        """Heading above this row, or None when it continues the group above."""
        proxy = index.model()
        if proxy is None or not hasattr(proxy, "group_of"):
            return None
        if proxy.group_by == GROUP_NONE:
            return None
        first = index.sibling(index.row(), 0)
        group = proxy.group_of(first)
        if not group[1]:
            return None
        if index.row() == 0:
            return group[1]
        previous = proxy.group_of(index.sibling(index.row() - 1, 0))
        return group[1] if group != previous else None

    def _row_has_heading(self, index) -> bool:
        return self._heading_for_row(index) is not None

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        if self._row_has_heading(index):
            size.setHeight(size.height() + GROUP_HEADER_HEIGHT + 1)
        return size

    def _draw_group_heading(self, painter: QPainter, option, heading: str) -> QRect:
        """Draw the heading band and return the rect left for the row itself."""
        band = QRect(option.rect)
        band.setHeight(GROUP_HEADER_HEIGHT)

        painter.save()
        font = QFont(option.font)
        font.setBold(True)
        font.setPointSizeF(max(7.5, font.pointSizeF() - 1.0))
        painter.setFont(font)
        painter.setPen(GROUP_HEADER_COLOR)
        text_rect = band.adjusted(4, 0, -6, 0)
        painter.drawText(
            text_rect,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            heading,
        )
        baseline = band.bottom() - 1
        painter.setPen(QPen(GROUP_RULE_COLOR, 1))
        painter.drawLine(band.left(), baseline, band.right(), baseline)
        painter.restore()

        remainder = QRect(option.rect)
        remainder.setTop(band.bottom() + 1)
        return remainder

    # ---------------------------------------------------------------- tag swatches

    @staticmethod
    def _tags_for(index) -> list[str]:
        value = index.data(TAGS_ROLE)
        return value if isinstance(value, list) else []

    def _draw_tag_dots(self, painter: QPainter, rect: QRect, tags: list[str]) -> int:
        """Draw colour dots at the right of the name cell; returns width used."""
        colors = [color_for(tag) for tag in tags]
        colors = [c for c in colors if c][:MAX_TAG_DOTS]
        if not colors:
            return 0

        width = len(colors) * (TAG_DOT_SIZE + TAG_DOT_GAP) + TAG_DOT_GAP
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        x = rect.right() - width + TAG_DOT_GAP
        y = rect.center().y() - TAG_DOT_SIZE // 2
        for color in colors:
            painter.setBrush(QColor(color))
            painter.drawEllipse(x, y, TAG_DOT_SIZE, TAG_DOT_SIZE)
            x += TAG_DOT_SIZE + TAG_DOT_GAP
        painter.restore()
        return width

    def paint(self, painter: QPainter, option, index) -> None:
        if self._row_has_heading(index):
            # QStyledItemDelegate.paint honours the rect it is handed, so
            # shrinking it here reserves the band above the row.
            option = QStyleOptionViewItem(option)
            if index.column() == 0:
                option.rect = self._draw_group_heading(
                    painter, option, self._heading_for_row(index)
                )
            else:
                option.rect = option.rect.adjusted(0, GROUP_HEADER_HEIGHT + 1, 0, 0)

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

        if index.column() == 0:
            tags = self._tags_for(index)
            if tags:
                used = self._draw_tag_dots(painter, option.rect, tags)
                if used:
                    # Let the name elide before it reaches the dots.
                    option = QStyleOptionViewItem(option)
                    option.rect = option.rect.adjusted(0, 0, -used, 0)

        if _is_cut(index):
            # Fades the icon as well; the model dims only the text.
            painter.save()
            painter.setOpacity(CUT_ITEM_OPACITY)
            super().paint(painter, option, index)
            painter.restore()
            return

        super().paint(painter, option, index)
