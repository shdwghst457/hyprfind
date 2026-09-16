"""File copy/move/alias operations."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from enum import Enum
from typing import Literal

ConflictChoice = Literal["replace", "keep_both", "skip", "stop"]

# Copy granularity. Small enough that cancelling a multi-gigabyte SMB copy feels
# immediate, large enough not to add measurable syscall overhead.
COPY_CHUNK_BYTES = 1024 * 1024


class TransferCancelled(Exception):
    """Raised internally to unwind a transfer the user cancelled."""


class TransferMonitor:
    """Progress sink and cancellation source for a transfer.

    Transfers run on a worker thread, so this is the only channel between the
    copy loop and the dialog. Both callbacks must be cheap and thread-safe.
    """

    def __init__(
        self,
        *,
        total_bytes: int = 0,
        total_items: int = 0,
        on_progress: Callable[[int, int, str], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> None:
        self.total_bytes = total_bytes
        self.total_items = total_items
        self.copied_bytes = 0
        self.completed_items = 0
        self.current_name = ""
        self.cancelled = False
        self._on_progress = on_progress
        self._should_cancel = should_cancel

    def check_cancelled(self) -> None:
        if self._should_cancel is not None and self._should_cancel():
            self.cancelled = True
        if self.cancelled:
            raise TransferCancelled

    def start_item(self, name: str) -> None:
        self.current_name = name
        self._emit()

    def finish_item(self) -> None:
        self.completed_items += 1

    def advance(self, amount: int) -> None:
        self.copied_bytes += amount
        self._emit()

    def _emit(self) -> None:
        if self._on_progress is not None:
            self._on_progress(self.copied_bytes, self.total_bytes, self.current_name)


def estimate_transfer_size(sources: list[str]) -> tuple[int, int]:
    """Return ``(total_bytes, file_count)`` for a set of sources.

    Walks directories, so it is only worth calling when a progress dialog will
    actually be shown. Unreadable entries are skipped rather than failing.
    """
    total = 0
    count = 0
    for source in sources:
        if os.path.islink(source):
            count += 1
            continue
        if os.path.isdir(source):
            for root, _dirs, files in os.walk(source, onerror=lambda _e: None):
                for name in files:
                    path = os.path.join(root, name)
                    try:
                        if not os.path.islink(path):
                            total += os.path.getsize(path)
                    except OSError:
                        continue
                    count += 1
            continue
        try:
            total += os.path.getsize(source)
        except OSError:
            pass
        count += 1
    return total, count


def _copy_file(source: str, target: str, monitor: TransferMonitor | None) -> None:
    """Copy one file, reporting progress and honouring cancellation."""
    if monitor is None:
        shutil.copy2(source, target, follow_symlinks=False)
        return
    if os.path.islink(source):
        os.symlink(os.readlink(source), target)
        monitor.check_cancelled()
        return

    monitor.start_item(os.path.basename(source))
    with open(source, "rb") as src, open(target, "wb") as dst:
        while True:
            monitor.check_cancelled()
            chunk = src.read(COPY_CHUNK_BYTES)
            if not chunk:
                break
            dst.write(chunk)
            monitor.advance(len(chunk))
    shutil.copystat(source, target, follow_symlinks=False)


def _copy_tree(source: str, target: str, monitor: TransferMonitor | None) -> None:
    """Recursive copy that streams through _copy_file for progress/cancel."""
    if monitor is None:
        shutil.copytree(source, target, dirs_exist_ok=True, symlinks=True)
        return

    os.makedirs(target, exist_ok=True)
    with os.scandir(source) as entries:
        for entry in entries:
            monitor.check_cancelled()
            destination = os.path.join(target, entry.name)
            if entry.is_dir(follow_symlinks=False):
                _copy_tree(entry.path, destination, monitor)
            else:
                _copy_file(entry.path, destination, monitor)
    shutil.copystat(source, target)


def _move(source: str, target: str, monitor: TransferMonitor | None) -> None:
    """Move, falling back to a progress-reporting copy across filesystems."""
    try:
        os.rename(source, target)
        if monitor is not None:
            # A rename moves no bytes, so credit the whole item at once.
            monitor.start_item(os.path.basename(source))
        return
    except OSError:
        pass

    if os.path.isdir(source) and not os.path.islink(source):
        _copy_tree(source, target, monitor)
        shutil.rmtree(source)
    else:
        _copy_file(source, target, monitor)
        os.remove(source)


class TransferOp(Enum):
    """How dropped items should be transferred, mirroring Finder."""

    MOVE = "move"
    COPY = "copy"
    ALIAS = "alias"


def _unique_target(target: str, word: str = "copy") -> str:
    """Finder-style "keep both" naming: ``name copy``, ``name copy 2``, …"""
    if not os.path.lexists(target):
        return target
    directory = os.path.dirname(target)
    name = os.path.basename(target)
    if os.path.isdir(target) and not os.path.islink(target):
        stem, ext = name, ""
    else:
        stem, ext = os.path.splitext(name)
    candidate = os.path.join(directory, f"{stem} {word}{ext}")
    index = 2
    while os.path.lexists(candidate):
        candidate = os.path.join(directory, f"{stem} {word} {index}{ext}")
        index += 1
    return candidate


def unique_directory(parent: str, base_name: str) -> str:
    """Return a not-yet-existing folder path: ``base``, ``base 2``, ``base 3``…"""
    candidate = os.path.join(parent, base_name)
    index = 2
    while os.path.lexists(candidate):
        candidate = os.path.join(parent, f"{base_name} {index}")
        index += 1
    return candidate


def _places_folder_inside_itself(source: str, destination_dir: str) -> bool:
    if not os.path.isdir(source):
        return False
    try:
        return os.path.commonpath([source, destination_dir]) == source
    except ValueError:
        # Different drives on platforms where commonpath rejects them.
        return False


def transfer_items(
    sources: list[str],
    destination_dir: str,
    *,
    operation: TransferOp,
    on_conflict: Callable[[str, str], ConflictChoice] | None = None,
    monitor: TransferMonitor | None = None,
) -> list[str]:
    """Apply ``operation`` to each source into destination_dir.

    Returns a list of human-readable error messages (empty on full success).
    ``on_conflict(source, target)`` is called when the destination exists;
    return ``replace``, ``keep_both``, ``skip``, or ``stop``.

    Pass ``monitor`` to report progress and allow cancellation; check
    ``monitor.cancelled`` afterwards to distinguish a cancel from a failure.
    """
    destination_dir = os.path.abspath(destination_dir)
    errors: list[str] = []
    apply_all: ConflictChoice | None = None

    for source in sources:
        source = os.path.abspath(source)
        if not os.path.lexists(source):
            errors.append(f"Not found: {source}")
            continue
        if _places_folder_inside_itself(source, destination_dir):
            errors.append(f"Cannot place a folder inside itself: {source}")
            continue

        target = os.path.join(destination_dir, os.path.basename(source))
        try:
            if monitor is not None:
                monitor.check_cancelled()
                monitor.start_item(os.path.basename(source))
            if operation is TransferOp.ALIAS:
                if os.path.lexists(target):
                    choice = apply_all or (on_conflict(source, target) if on_conflict else "keep_both")
                    if choice == "stop":
                        break
                    if choice == "skip":
                        continue
                    if choice == "keep_both":
                        target = _unique_target(target, "alias")
                    elif choice == "replace":
                        if os.path.isdir(target) and not os.path.islink(target):
                            shutil.rmtree(target)
                        else:
                            os.remove(target)
                os.symlink(source, target)
            elif operation is TransferOp.COPY:
                if os.path.lexists(target):
                    choice = apply_all or (on_conflict(source, target) if on_conflict else "keep_both")
                    if choice == "stop":
                        break
                    if choice == "skip":
                        continue
                    if choice == "keep_both":
                        target = _unique_target(target, "copy")
                    elif choice == "replace":
                        if os.path.isdir(target) and not os.path.islink(target):
                            shutil.rmtree(target)
                        else:
                            os.remove(target)
                    if on_conflict and not apply_all:
                        apply_all = choice if choice in ("replace", "keep_both", "skip") else None
                if os.path.isdir(source) and not os.path.islink(source):
                    _copy_tree(source, target, monitor)
                else:
                    _copy_file(source, target, monitor)
            else:  # MOVE
                if os.path.lexists(target):
                    choice = apply_all or (on_conflict(source, target) if on_conflict else None)
                    if choice is None:
                        errors.append(f"Already exists: {target}")
                        continue
                    if choice == "stop":
                        break
                    if choice == "skip":
                        continue
                    if choice == "replace":
                        if os.path.isdir(target) and not os.path.islink(target):
                            shutil.rmtree(target)
                        else:
                            os.remove(target)
                    elif choice == "keep_both":
                        target = _unique_target(target, "copy")
                    if on_conflict and not apply_all:
                        apply_all = choice if choice in ("replace", "keep_both", "skip") else None
                _move(source, target, monitor)
        except TransferCancelled:
            # Leave the partially written target; the caller reports the cancel.
            break
        except OSError as exc:
            errors.append(f"{os.path.basename(source)}: {exc}")
        else:
            if monitor is not None:
                monitor.finish_item()

    return errors
