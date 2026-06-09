"""File copy/move/alias operations."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from enum import Enum
from typing import Literal

ConflictChoice = Literal["replace", "keep_both", "skip", "stop"]


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
) -> list[str]:
    """Apply ``operation`` to each source into destination_dir.

    Returns a list of human-readable error messages (empty on full success).
    ``on_conflict(source, target)`` is called when the destination exists;
    return ``replace``, ``keep_both``, ``skip``, or ``stop``.
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
                    if not os.path.exists(target):
                        shutil.copytree(source, target)
                    else:
                        shutil.copytree(source, target, dirs_exist_ok=True)
                else:
                    shutil.copy2(source, target, follow_symlinks=False)
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
                shutil.move(source, target)
        except OSError as exc:
            errors.append(f"{os.path.basename(source)}: {exc}")

    return errors
