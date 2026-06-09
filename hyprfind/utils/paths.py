"""XDG paths and user directory helpers."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def config_dir() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "hyprfind"
    return Path.home() / ".config" / "hyprfind"


def cache_dir() -> Path:
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        return Path(xdg) / "hyprfind"
    return Path.home() / ".cache" / "hyprfind"


def expand_path(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path))


def xdg_user_dir(name: str, fallback: Path) -> Path:
    try:
        result = subprocess.run(
            ["xdg-user-dir", name],
            capture_output=True,
            text=True,
            check=False,
            timeout=2,
        )
        if result.returncode == 0:
            candidate = result.stdout.strip()
            if candidate:
                return Path(candidate)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return fallback


def bookmark_name_for_path(path: str) -> str:
    """Short sidebar label — folder name, not the full mount path."""
    normalized = os.path.abspath(os.path.expanduser(path)).rstrip(os.sep)
    name = os.path.basename(normalized)
    return name or normalized


def default_favorites() -> list[tuple[str, str]]:
    home = Path.home()
    return [
        ("Home", str(home)),
        ("Desktop", str(xdg_user_dir("DESKTOP", home / "Desktop"))),
        ("Documents", str(xdg_user_dir("DOCUMENTS", home / "Documents"))),
        ("Downloads", str(xdg_user_dir("DOWNLOAD", home / "Downloads"))),
    ]


def gvfs_base() -> str:
    uid = os.getuid()
    return f"/run/user/{uid}/gvfs/"
