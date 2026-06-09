"""Saved search / smart folder definitions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from hyprfind.utils.paths import config_dir


@dataclass
class SmartFolder:
    name: str
    query: str


class SmartFolderStore:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path or config_dir() / "smart_folders.json"
        self._folders: list[SmartFolder] = []

    def load(self) -> None:
        if not self._path.exists():
            self._folders = []
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self._folders = [
                SmartFolder(name=item["name"], query=item["query"])
                for item in data.get("folders", [])
                if isinstance(item, dict)
            ]
        except (json.JSONDecodeError, OSError, KeyError, TypeError):
            self._folders = []

    def all(self) -> list[SmartFolder]:
        return list(self._folders)
