"""Saved search / smart folder definitions."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from hyprfind.core.search import SCOPE_EVERYWHERE, SCOPE_HERE, SearchQuery
from hyprfind.utils.paths import config_dir


@dataclass
class SmartFolder:
    """A saved search: what to look for, and where."""

    name: str
    query: str
    scope: str = SCOPE_EVERYWHERE
    root: str = ""
    include_hidden: bool = False
    directories_only: bool = False

    def roots(self, current_directory: str, home: str) -> list[str]:
        """Resolve the search roots at run time.

        A pinned root is used verbatim; otherwise the scope decides between the
        folder being browsed and the user's home.
        """
        if self.root:
            return [os.path.expanduser(self.root)]
        if self.scope == SCOPE_HERE and current_directory:
            return [current_directory]
        return [home]

    def to_query(self, current_directory: str, home: str) -> SearchQuery:
        return SearchQuery(
            text=self.query,
            roots=self.roots(current_directory, home),
            include_hidden=self.include_hidden,
            directories_only=self.directories_only,
        )

    def describe(self) -> str:
        """One-line summary for the editor list."""
        where = self.root or ("this folder" if self.scope == SCOPE_HERE else "Home")
        parts = [f"“{self.query}” in {where}"]
        if self.include_hidden:
            parts.append("including hidden")
        if self.directories_only:
            parts.append("folders only")
        return ", ".join(parts)

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "query": self.query,
            "scope": self.scope,
            "root": self.root,
            "include_hidden": self.include_hidden,
            "directories_only": self.directories_only,
        }

    @classmethod
    def from_dict(cls, item: dict) -> SmartFolder | None:
        name = item.get("name")
        query = item.get("query")
        if not isinstance(name, str) or not isinstance(query, str):
            return None
        if not name.strip() or not query.strip():
            return None
        scope = item.get("scope")
        return cls(
            name=name.strip(),
            query=query,
            # Entries saved before scopes existed searched the whole home.
            scope=scope if scope in (SCOPE_HERE, SCOPE_EVERYWHERE) else SCOPE_EVERYWHERE,
            root=item.get("root") if isinstance(item.get("root"), str) else "",
            include_hidden=bool(item.get("include_hidden", False)),
            directories_only=bool(item.get("directories_only", False)),
        )


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
        except (json.JSONDecodeError, OSError):
            self._folders = []
            return
        items = data.get("folders") if isinstance(data, dict) else None
        if not isinstance(items, list):
            self._folders = []
            return
        parsed = (
            SmartFolder.from_dict(item) for item in items if isinstance(item, dict)
        )
        self._folders = [folder for folder in parsed if folder is not None]

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"folders": [folder.as_dict() for folder in self._folders]}
        try:
            self._path.write_text(
                json.dumps(payload, indent=2) + "\n", encoding="utf-8"
            )
        except OSError:
            pass

    def all(self) -> list[SmartFolder]:
        return list(self._folders)

    def add(self, folder: SmartFolder) -> None:
        self._folders.append(folder)
        self.save()

    def replace_all(self, folders: list[SmartFolder]) -> None:
        self._folders = list(folders)
        self.save()

    def update(self, index: int, folder: SmartFolder) -> None:
        if 0 <= index < len(self._folders):
            self._folders[index] = folder
            self.save()

    def remove(self, index: int) -> None:
        if 0 <= index < len(self._folders):
            del self._folders[index]
            self.save()

    def move(self, index: int, offset: int) -> int:
        """Reorder one entry; returns its new index."""
        target = index + offset
        if not (0 <= index < len(self._folders)) or not (
            0 <= target < len(self._folders)
        ):
            return index
        folder = self._folders.pop(index)
        self._folders.insert(target, folder)
        self.save()
        return target
