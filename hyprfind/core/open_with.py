"""Discover applications that can open a file."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class AppEntry:
    name: str
    exec_line: str
    desktop_path: str


def _parse_desktop_file(path: Path) -> AppEntry | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    name = ""
    exec_line = ""
    hidden = False
    nodisplay = False
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("Name=") and not name:
            name = line[5:]
        elif line.startswith("Exec="):
            exec_line = line[5:]
        elif line == "Hidden=true":
            hidden = True
        elif line == "NoDisplay=true":
            nodisplay = True
    if not name or not exec_line or hidden or nodisplay:
        return None
    exec_line = exec_line.replace("%f", "").replace("%F", "").replace("%u", "").replace("%U", "")
    exec_line = exec_line.replace("%k", "").strip()
    return AppEntry(name=name, exec_line=exec_line, desktop_path=str(path))


def apps_for_mime(mime: str) -> list[AppEntry]:
    apps: list[AppEntry] = []
    seen: set[str] = set()
    try:
        result = subprocess.run(
            ["xdg-mime", "query", "default", mime],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if result.returncode == 0:
            default = result.stdout.strip()
            if default:
                for base in _desktop_dirs():
                    path = base / default
                    if path.exists():
                        entry = _parse_desktop_file(path)
                        if entry and entry.name not in seen:
                            seen.add(entry.name)
                            apps.append(entry)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass

    for base in _desktop_dirs():
        for path in base.glob("*.desktop"):
            entry = _parse_desktop_file(path)
            if entry and entry.name not in seen:
                seen.add(entry.name)
                apps.append(entry)
            if len(apps) >= 30:
                break
    return apps[:30]


def _desktop_dirs() -> list[Path]:
    dirs: list[Path] = []
    xdg = os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share")
    home = Path.home()
    dirs.append(home / ".local" / "share" / "applications")
    for part in xdg.split(":"):
        dirs.append(Path(part) / "applications")
    return [d for d in dirs if d.is_dir()]


def launch_app(entry: AppEntry, file_path: str) -> bool:
    cmd = entry.exec_line.split() + [file_path]
    try:
        subprocess.Popen(cmd, start_new_session=True)
        return True
    except OSError:
        return False
