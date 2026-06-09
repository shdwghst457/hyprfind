"""Persistent sidebar favorites."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from hyprfind.utils.paths import config_dir, default_favorites


@dataclass
class Bookmark:
    name: str
    path: str


class BookmarkStore:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path or config_dir() / "bookmarks.json"
        self._custom: list[Bookmark] = []
        self._order: list[str] | None = None

    @property
    def file_path(self) -> Path:
        return self._path

    def load(self) -> None:
        if not self._path.exists():
            self._custom = []
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self._custom = [
                Bookmark(name=item["name"], path=item["path"])
                for item in data.get("custom", [])
            ]
            order = data.get("order")
            if isinstance(order, list):
                self._order = [str(path) for path in order]
        except (json.JSONDecodeError, KeyError, TypeError):
            self._custom = []

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict = {
            "custom": [{"name": b.name, "path": b.path} for b in self._custom],
        }
        if self._order is not None:
            payload["order"] = self._order
        self._path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    @staticmethod
    def _normalize_path(path: str) -> str:
        return os.path.normpath(os.path.abspath(os.path.expanduser(path)))

    def _merged_bookmarks(self) -> list[Bookmark]:
        defaults = [Bookmark(name=n, path=p) for n, p in default_favorites()]
        seen = {b.path for b in defaults}
        merged = list(defaults)
        for bookmark in self._custom:
            if bookmark.path not in seen:
                merged.append(bookmark)
                seen.add(bookmark.path)
        return merged

    def all_bookmarks(self) -> list[Bookmark]:
        merged = self._merged_bookmarks()
        if not self._order:
            return merged
        by_path = {self._normalize_path(b.path): b for b in merged}
        ordered: list[Bookmark] = []
        for path in self._order:
            bookmark = by_path.pop(self._normalize_path(path), None)
            if bookmark is not None:
                ordered.append(bookmark)
        ordered.extend(by_path.values())
        return ordered

    def reorder(self, paths: list[str]) -> None:
        """Persist sidebar favorite order (Trash is managed separately)."""
        self._order = [self._normalize_path(path) for path in paths]
        self.save()

    def add(self, name: str, path: str) -> None:
        path = str(Path(path).expanduser())
        for bookmark in self._custom:
            if bookmark.path == path:
                bookmark.name = name
                self.save()
                return
        self._custom.append(Bookmark(name=name, path=path))
        normalized = self._normalize_path(path)
        if self._order is not None and normalized not in self._order:
            self._order.append(normalized)
        self.save()

    def remove(self, path: str) -> None:
        path = str(Path(path).expanduser())
        normalized = self._normalize_path(path)
        self._custom = [b for b in self._custom if b.path != path]
        if self._order is not None:
            self._order = [p for p in self._order if p != normalized]
        self.save()

    def is_removable(self, path: str) -> bool:
        """True for user-added favorites; built-in defaults cannot be removed."""
        normalized = os.path.normpath(os.path.abspath(os.path.expanduser(path)))
        default_paths = {
            os.path.normpath(os.path.abspath(p)) for _, p in default_favorites()
        }
        if normalized in default_paths:
            return False
        return any(
            os.path.normpath(os.path.abspath(b.path)) == normalized
            for b in self._custom
        )
