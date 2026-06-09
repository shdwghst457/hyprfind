"""Freedesktop trash spec — move to trash, restore, empty."""

from __future__ import annotations

import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, unquote


def trash_dir() -> Path:
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / "Trash"


def trash_files_dir() -> Path:
    return trash_dir() / "files"


def trash_info_dir() -> Path:
    return trash_dir() / "info"


@dataclass
class TrashedItem:
    trash_path: str
    original_path: str
    deletion_date: str
    name: str


def ensure_trash() -> None:
    trash_files_dir().mkdir(parents=True, exist_ok=True)
    trash_info_dir().mkdir(parents=True, exist_ok=True)


def _ensure_trash() -> None:
    ensure_trash()


def _unique_trash_name(name: str) -> str:
    files = trash_files_dir()
    candidate = name
    index = 2
    while (files / candidate).exists() or (trash_info_dir() / f"{candidate}.trashinfo").exists():
        stem, ext = os.path.splitext(name) if "." in name and not name.startswith(".") else (name, "")
        if not ext and os.path.splitext(name)[0] == name and name.startswith("."):
            stem, ext = name, ""
        candidate = f"{stem}.{index}{ext}" if ext else f"{name}.{index}"
        index += 1
    return candidate


def _write_trashinfo(trash_name: str, original_path: str) -> None:
    deletion = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
    encoded = quote(original_path, safe="/")
    content = f"[Trash Info]\nPath={encoded}\nDeletionDate={deletion}\n"
    info_path = trash_info_dir() / f"{trash_name}.trashinfo"
    info_path.write_text(content, encoding="utf-8")


def move_to_trash(path: str) -> tuple[str, str] | None:
    """Move path to trash. Returns (trash_path, original_path) or None on failure."""
    path = os.path.abspath(os.path.expanduser(path))
    if not os.path.lexists(path):
        return None
    _ensure_trash()
    name = os.path.basename(path.rstrip(os.sep)) or path
    trash_name = _unique_trash_name(name)
    dest = trash_files_dir() / trash_name
    try:
        shutil.move(path, dest)
    except OSError:
        return None
    _write_trashinfo(trash_name, path)
    return str(dest), path


def move_paths_to_trash(paths: list[str]) -> list[tuple[str, str]]:
    """Move multiple paths; returns list of (trash_path, original_path) pairs."""
    results: list[tuple[str, str]] = []
    for path in paths:
        result = move_to_trash(path)
        if result:
            results.append(result)
    return results


def restore_from_trash(trash_path: str) -> str | None:
    """Restore a trashed item to its original location. Returns restored path."""
    trash_path = os.path.abspath(trash_path)
    name = os.path.basename(trash_path)
    info_path = trash_info_dir() / f"{name}.trashinfo"
    if not info_path.exists():
        return None
    original = _parse_trashinfo(info_path)
    if not original:
        return None
    original = unquote(original)
    if os.path.lexists(original):
        parent = os.path.dirname(original)
        base = os.path.basename(original)
        from hyprfind.core.file_ops import _unique_target

        original = _unique_target(os.path.join(parent, base), "restored")
    parent = os.path.dirname(original)
    if parent:
        os.makedirs(parent, exist_ok=True)
    try:
        shutil.move(trash_path, original)
    except OSError:
        return None
    info_path.unlink(missing_ok=True)
    return original


def _parse_trashinfo(info_path: Path) -> str | None:
    try:
        for line in info_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("Path="):
                return line[5:]
    except OSError:
        pass
    return None


def list_trash() -> list[TrashedItem]:
    items: list[TrashedItem] = []
    files = trash_files_dir()
    if not files.is_dir():
        return items
    for entry in files.iterdir():
        info_path = trash_info_dir() / f"{entry.name}.trashinfo"
        original = _parse_trashinfo(info_path) if info_path.exists() else ""
        deletion = ""
        if info_path.exists():
            try:
                for line in info_path.read_text(encoding="utf-8").splitlines():
                    if line.startswith("DeletionDate="):
                        deletion = line[13:]
            except OSError:
                pass
        items.append(
            TrashedItem(
                trash_path=str(entry),
                original_path=unquote(original) if original else "",
                deletion_date=deletion,
                name=entry.name,
            )
        )
    return items


def empty_trash() -> list[str]:
    """Empty trash; returns error messages."""
    errors: list[str] = []
    for item in list_trash():
        try:
            if os.path.isdir(item.trash_path) and not os.path.islink(item.trash_path):
                shutil.rmtree(item.trash_path)
            else:
                os.remove(item.trash_path)
            info = trash_info_dir() / f"{item.name}.trashinfo"
            info.unlink(missing_ok=True)
        except OSError as exc:
            errors.append(f"{item.name}: {exc}")
    return errors


def trash_path() -> str:
    return str(trash_files_dir())


def is_trash_directory(path: str) -> bool:
    return os.path.normpath(os.path.abspath(path)) == os.path.normpath(trash_path())


def trash_count() -> int:
    return len(list_trash())
