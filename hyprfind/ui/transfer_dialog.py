"""Progress dialog for copy/move transfers.

Transfers run on a worker thread so the window keeps painting; a large copy to
an SMB share would otherwise freeze the UI for minutes with no way out.
"""

from __future__ import annotations

import os
import time

from PyQt6.QtCore import QObject, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from hyprfind.core.file_ops import (
    ConflictChoice,
    TransferMonitor,
    TransferOp,
    estimate_transfer_size,
    transfer_items,
)
from hyprfind.utils.formatting import format_bytes

# Below this the copy finishes faster than a dialog can usefully appear.
PROGRESS_THRESHOLD_BYTES = 8 * 1024 * 1024
PROGRESS_THRESHOLD_ITEMS = 25

_OP_TITLES = {
    TransferOp.COPY: "Copying",
    TransferOp.MOVE: "Moving",
    TransferOp.ALIAS: "Creating aliases",
}


def should_show_progress(total_bytes: int, total_items: int) -> bool:
    return (
        total_bytes >= PROGRESS_THRESHOLD_BYTES or total_items >= PROGRESS_THRESHOLD_ITEMS
    )


class _TransferWorker(QObject):
    """Runs one transfer_items call on a worker thread."""

    # qint64, not int: byte counts above 2 GiB wrap in a 32-bit signal parameter.
    progress = pyqtSignal("qint64", "qint64", str)
    finished = pyqtSignal(list, bool)

    def __init__(
        self,
        sources: list[str],
        destination: str,
        operation: TransferOp,
        total_bytes: int,
        total_items: int,
        on_conflict,
    ) -> None:
        super().__init__()
        self._sources = sources
        self._destination = destination
        self._operation = operation
        self._on_conflict = on_conflict
        self._cancelled = False
        self._monitor = TransferMonitor(
            total_bytes=total_bytes,
            total_items=total_items,
            on_progress=self._on_progress,
            should_cancel=lambda: self._cancelled,
        )
        self._last_emit = 0.0

    def cancel(self) -> None:
        """Safe to call from the GUI thread; only flips a flag."""
        self._cancelled = True

    def _on_progress(self, copied: int, total: int, name: str) -> None:
        # Chunk callbacks arrive thousands of times a second; throttle to ~20Hz
        # so the event queue is not flooded with paint requests.
        now = time.monotonic()
        if now - self._last_emit < 0.05:
            return
        self._last_emit = now
        self.progress.emit(copied, total, name)

    def run(self) -> None:
        errors = transfer_items(
            self._sources,
            self._destination,
            operation=self._operation,
            on_conflict=self._on_conflict,
            monitor=self._monitor,
        )
        self.finished.emit(errors, self._monitor.cancelled)


class TransferProgressDialog(QDialog):
    """Modal progress for a single transfer, with a working Cancel."""

    def __init__(
        self,
        sources: list[str],
        destination: str,
        operation: TransferOp,
        *,
        total_bytes: int,
        total_items: int,
        on_conflict=None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(_OP_TITLES.get(operation, "Transferring"))
        self.setModal(True)
        self.setMinimumWidth(420)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)

        self.errors: list[str] = []
        self.cancelled = False
        self._total_bytes = total_bytes
        self._total_items = total_items

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        verb = _OP_TITLES.get(operation, "Transferring")
        self._heading = QLabel(
            f"{verb} {total_items} item{'s' if total_items != 1 else ''} "
            f"to {os.path.basename(destination.rstrip(os.sep)) or destination}"
        )
        self._heading.setObjectName("transferHeading")
        layout.addWidget(self._heading)

        self._bar = QProgressBar()
        self._bar.setRange(0, 100 if total_bytes > 0 else 0)
        self._bar.setTextVisible(False)
        layout.addWidget(self._bar)

        self._detail = QLabel("Preparing…")
        self._detail.setObjectName("transferDetail")
        self._detail.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._detail)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self._cancel_button = QPushButton("Cancel")
        self._cancel_button.clicked.connect(self._on_cancel)
        buttons.addWidget(self._cancel_button)
        layout.addLayout(buttons)

        self._thread = QThread(self)
        self._worker = _TransferWorker(
            sources, destination, operation, total_bytes, total_items, on_conflict
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        QTimer.singleShot(0, self._thread.start)

    def _on_progress(self, copied: int, total: int, name: str) -> None:
        if total > 0:
            self._bar.setRange(0, 100)
            self._bar.setValue(min(100, int(copied * 100 / total)))
            self._detail.setText(
                f"{name} — {format_bytes(copied)} of {format_bytes(total)}"
            )
        else:
            self._detail.setText(name)

    def _on_cancel(self) -> None:
        self._cancel_button.setEnabled(False)
        self._cancel_button.setText("Cancelling…")
        self._detail.setText("Finishing the current file…")
        self._worker.cancel()

    def _on_finished(self, errors: list, cancelled: bool) -> None:
        self.errors = list(errors)
        self.cancelled = cancelled
        self._thread.quit()
        self._thread.wait(3000)
        self.accept()

    def closeEvent(self, event) -> None:
        # Never leave the worker running behind a dismissed dialog.
        if self._thread.isRunning():
            self._worker.cancel()
            self._thread.quit()
            self._thread.wait(3000)
        super().closeEvent(event)


def _prompt_conflicts(
    sources: list[str], destination: str, on_conflict
) -> ConflictChoice | None:
    """Ask about the first colliding target, on the GUI thread.

    The worker thread cannot raise dialogs, so the decision has to be made
    before it starts. transfer_items already applies the first answer to the
    whole batch, so one prompt is all it would have shown anyway.
    """
    if on_conflict is None:
        return None
    for source in sources:
        target = os.path.join(destination, os.path.basename(source))
        if os.path.lexists(target):
            return on_conflict(source, target)
    return None


def run_transfer(
    sources: list[str],
    destination: str,
    operation: TransferOp,
    *,
    on_conflict=None,
    parent=None,
) -> tuple[list[str], bool]:
    """Transfer items, showing progress only when the job is big enough.

    Returns ``(errors, cancelled)``. Small transfers run inline to avoid a
    dialog that flashes up and vanishes.
    """
    if operation is TransferOp.ALIAS:
        return transfer_items(
            sources, destination, operation=operation, on_conflict=on_conflict
        ), False

    total_bytes, total_items = estimate_transfer_size(sources)
    if not should_show_progress(total_bytes, total_items):
        return transfer_items(
            sources, destination, operation=operation, on_conflict=on_conflict
        ), False

    choice = _prompt_conflicts(sources, destination, on_conflict)
    if choice == "stop":
        return [], True

    dialog = TransferProgressDialog(
        sources,
        destination,
        operation,
        total_bytes=total_bytes,
        total_items=total_items,
        # Fixed answer: safe to call from the worker, no GUI work involved.
        on_conflict=(lambda _s, _t: choice) if choice is not None else None,
        parent=parent,
    )
    dialog.exec()
    return dialog.errors, dialog.cancelled
