"""Shared drag-and-drop helpers: modifier semantics, colors, status text.

Modifier semantics mirror Finder while respecting Linux conventions:

  * Default — move within the same volume, copy across volumes.
  * Copy   — Ctrl or Alt (Option).
  * Move   — Shift (force move even across volumes).
  * Alias  — Ctrl+Shift (a symlink, the Linux equivalent of a Finder alias).

On macOS the bindings shift to Option=copy, Cmd=move, Cmd+Option=alias.
"""

from __future__ import annotations

import os
import sys

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

from hyprfind.core.file_ops import TransferOp

_IS_DARWIN = sys.platform == "darwin"


def same_device(source: str, destination_dir: str) -> bool:
    """Best-effort check whether two paths live on the same volume."""
    try:
        return os.stat(source).st_dev == os.stat(destination_dir).st_dev
    except OSError:
        return True


def operation_for_modifiers(
    modifiers: Qt.KeyboardModifier, *, cross_device: bool
) -> TransferOp:
    meta = bool(modifiers & Qt.KeyboardModifier.MetaModifier)
    alt = bool(modifiers & Qt.KeyboardModifier.AltModifier)
    ctrl = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
    shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)

    if _IS_DARWIN:
        if meta and alt:
            return TransferOp.ALIAS
        if alt:
            return TransferOp.COPY
        if meta:
            return TransferOp.MOVE
    else:
        if ctrl and shift:
            return TransferOp.ALIAS
        if shift:
            return TransferOp.MOVE
        if ctrl or alt:
            return TransferOp.COPY

    return TransferOp.COPY if cross_device else TransferOp.MOVE


def status_verb(operation: TransferOp) -> str:
    return {
        TransferOp.MOVE: "move",
        TransferOp.COPY: "copy",
        TransferOp.ALIAS: "alias",
    }[operation]


def status_text(operation: TransferOp, destination_name: str) -> str:
    verbs = {
        TransferOp.MOVE: "Move to",
        TransferOp.COPY: "Copy to",
        TransferOp.ALIAS: "Alias in",
    }
    return f"{verbs[operation]} {destination_name}"


def highlight_colors(operation: TransferOp) -> tuple[QColor, QColor]:
    """(fill, border) used to paint a drop target for the given operation."""
    if operation is TransferOp.COPY:
        return QColor(72, 168, 108, 150), QColor(120, 220, 150)
    if operation is TransferOp.ALIAS:
        return QColor(150, 110, 210, 150), QColor(190, 150, 240)
    return QColor(74, 132, 210, 155), QColor(130, 190, 255)
