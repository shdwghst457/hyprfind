"""Recent folders persistence."""

from __future__ import annotations

import json
import os
from pathlib import Path

from hyprfind.utils.paths import config_dir

MAX_RECENTS = 20


class RecentFolders:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path or config_dir() / "recents.json"
        self._folders: list[str] = []

    def load(self) -> None:
        if not self._path.exists():
            self._folders = []
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            raw = data.get("folders", [])
            self._folders = [
                f for f in raw if isinstance(f, str) and os.path.isdir(f)
            ]
        except (json.JSONDecodeError, OSError, TypeError):
            self._folders = []

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps({"folders": self._folders}, indent=2) + "\n",
            encoding="utf-8",
        )

    def push(self, path: str) -> None:
        normalized = os.path.abspath(os.path.expanduser(path))
        if not os.path.isdir(normalized):
            return
        if normalized in self._folders:
            self._folders.remove(normalized)
        self._folders.insert(0, normalized)
        self._folders = self._folders[:MAX_RECENTS]
        self.save()

    def all(self) -> list[str]:
        return list(self._folders)
