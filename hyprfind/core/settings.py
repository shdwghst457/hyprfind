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
        # Column index -> pixel width. Name is omitted; it always flexes.
        self.column_widths: dict[int, int] = {}
        self.group_by: str = "none"

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
            widths = data.get("column_widths")
            if isinstance(widths, dict):
                # JSON object keys are strings; the UI indexes columns by int.
                self.column_widths = {
                    int(key): int(value)
                    for key, value in widths.items()
                    if str(key).lstrip("-").isdigit() and int(value) > 0
                }
            group = data.get("group_by")
            if isinstance(group, str):
                self.group_by = group
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
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
        if self.column_widths:
            payload["column_widths"] = {
                str(key): value for key, value in sorted(self.column_widths.items())
            }
        payload["group_by"] = self.group_by
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

    def set_window_geometry(self, geometry: str) -> None:
        self.window_geometry = geometry
        self.save()

    def set_sort(self, column: int, order: int) -> None:
        self.sort_column = column
        self.sort_order = order
        self.save()

    def set_column_widths(self, widths: dict[int, int]) -> None:
        self.column_widths = {
            int(column): int(width) for column, width in widths.items() if width > 0
        }
        self.save()

    def set_group_by(self, key: str) -> None:
        self.group_by = key
        self.save()
