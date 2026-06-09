"""Persistent UI settings."""

from __future__ import annotations

import json
from pathlib import Path

from hyprfind.utils.paths import config_dir


class AppSettings:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path or config_dir() / "settings.json"
        self.sidebar_width: int | None = None
        self.show_hidden: bool = False
        self.view_mode: str = "list"
        self.icon_size: int = 48
        self.window_geometry: str | None = None
        self.sort_column: int = 0
        self.sort_order: int = 0
        self.confirm_permanent_delete: bool = True

    def load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            width = data.get("sidebar_width")
            if isinstance(width, int) and width > 0:
                self.sidebar_width = width
            self.show_hidden = bool(data.get("show_hidden", False))
            mode = data.get("view_mode")
            if isinstance(mode, str) and mode in ("list", "icon", "column"):
                self.view_mode = mode
            icon = data.get("icon_size")
            if isinstance(icon, int) and 16 <= icon <= 128:
                self.icon_size = icon
            geom = data.get("window_geometry")
            if isinstance(geom, str):
                self.window_geometry = geom
            sc = data.get("sort_column")
            if isinstance(sc, int):
                self.sort_column = sc
            so = data.get("sort_order")
            if isinstance(so, int):
                self.sort_order = so
            self.confirm_permanent_delete = bool(
                data.get("confirm_permanent_delete", True)
            )
        except (json.JSONDecodeError, OSError, TypeError):
            pass

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict = {}
        if self.sidebar_width is not None:
            payload["sidebar_width"] = self.sidebar_width
        payload["show_hidden"] = self.show_hidden
        payload["view_mode"] = self.view_mode
        payload["icon_size"] = self.icon_size
        if self.window_geometry:
            payload["window_geometry"] = self.window_geometry
        payload["sort_column"] = self.sort_column
        payload["sort_order"] = self.sort_order
        payload["confirm_permanent_delete"] = self.confirm_permanent_delete
        self._path.write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8"
        )

    def set_sidebar_width(self, width: int) -> None:
        if width < 1:
            return
        self.sidebar_width = width
        self.save()

    def set_show_hidden(self, show: bool) -> None:
        self.show_hidden = show
        self.save()

    def set_view_mode(self, mode: str) -> None:
        if mode in ("list", "icon", "column"):
            self.view_mode = mode
            self.save()

    def set_icon_size(self, size: int) -> None:
        self.icon_size = max(16, min(128, size))
        self.save()
