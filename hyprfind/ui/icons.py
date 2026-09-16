"""Freedesktop icon lookup with Qt built-in fallbacks.

A bare Hyprland session sets no desktop environment, so Qt detects neither an
icon theme name nor the system theme directories. Without the setup here the
sidebar renders unlabelled blanks and dated Qt fallback glyphs.
"""

from __future__ import annotations

import os
from pathlib import Path

from PyQt6.QtCore import QFileInfo, QMimeDatabase
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QFileIconProvider, QStyle

from hyprfind.core.volumes import NETWORK, OPTICAL, REMOVABLE, SYSTEM
from hyprfind.utils.paths import xdg_user_dir

# Preferred first: a full dark theme, then GNOME's, then the bare minimum.
_THEME_PREFERENCES = ("breeze-dark", "Adwaita", "breeze", "hicolor")

_VOLUME_ICON_NAMES = {
    SYSTEM: ("drive-harddisk-root", "drive-harddisk"),
    REMOVABLE: ("drive-removable-media-usb", "drive-removable-media", "drive-harddisk"),
    OPTICAL: ("media-optical",),
    NETWORK: ("folder-remote", "network-server", "folder-network"),
}

_VOLUME_FALLBACKS = {
    SYSTEM: QStyle.StandardPixmap.SP_DriveHDIcon,
    REMOVABLE: QStyle.StandardPixmap.SP_DriveFDIcon,
    OPTICAL: QStyle.StandardPixmap.SP_DriveCDIcon,
    NETWORK: QStyle.StandardPixmap.SP_DriveNetIcon,
}

_XDG_ICON_NAMES = (
    ("DESKTOP", "Desktop", "user-desktop"),
    ("DOCUMENTS", "Documents", "folder-documents"),
    ("DOWNLOAD", "Downloads", "folder-download"),
    ("PICTURES", "Pictures", "folder-pictures"),
    ("MUSIC", "Music", "folder-music"),
    ("VIDEOS", "Videos", "folder-videos"),
    ("PUBLICSHARE", "Public", "folder-publicshare"),
    ("TEMPLATES", "Templates", "folder-templates"),
)

_special_folders: dict[str, str] | None = None


def configure_icon_theme() -> None:
    """Point Qt at the system icon directories and pick a usable theme."""
    search = [
        os.path.expanduser("~/.local/share/icons"),
        "/usr/local/share/icons",
        "/usr/share/icons",
        ":/icons",
    ]
    QIcon.setThemeSearchPaths(search)
    QIcon.setFallbackThemeName("hicolor")

    if QIcon.themeName() and QIcon.hasThemeIcon("folder"):
        return

    for theme in _THEME_PREFERENCES:
        QIcon.setThemeName(theme)
        if QIcon.hasThemeIcon("folder"):
            return


def _special_folder_map() -> dict[str, str]:
    global _special_folders
    if _special_folders is None:
        home = Path.home()
        mapping = {os.path.normpath(str(home)): "user-home"}
        for xdg_name, folder, icon_name in _XDG_ICON_NAMES:
            path = xdg_user_dir(xdg_name, home / folder)
            mapping.setdefault(os.path.normpath(str(path)), icon_name)
        _special_folders = mapping
    return _special_folders


def _first_available(names: tuple[str, ...] | list[str]) -> QIcon | None:
    for name in names:
        if QIcon.hasThemeIcon(name):
            icon = QIcon.fromTheme(name)
            if not icon.isNull():
                return icon
    return None


def _standard(pixmap: QStyle.StandardPixmap) -> QIcon:
    app = QApplication.instance()
    style = app.style() if app is not None else None
    return style.standardIcon(pixmap) if style is not None else QIcon()


def folder_icon(path: str, *, is_network: bool = False) -> QIcon:
    """Icon for a sidebar favourite, honouring the XDG special folders."""
    if is_network:
        icon = _first_available(_VOLUME_ICON_NAMES[NETWORK])
        return icon or _standard(QStyle.StandardPixmap.SP_DriveNetIcon)

    normalized = os.path.normpath(os.path.abspath(os.path.expanduser(path)))
    special = _special_folder_map().get(normalized)
    names = [special, "folder"] if special else ["folder"]
    icon = _first_available([name for name in names if name])
    return icon or _standard(QStyle.StandardPixmap.SP_DirIcon)


def trash_icon(*, full: bool) -> QIcon:
    names = ("user-trash-full", "user-trash") if full else ("user-trash",)
    icon = _first_available(names)
    return icon or _standard(QStyle.StandardPixmap.SP_TrashIcon)


def volume_icon(kind: str) -> QIcon:
    icon = _first_available(_VOLUME_ICON_NAMES.get(kind, ()))
    if icon is not None:
        return icon
    fallback = _VOLUME_FALLBACKS.get(kind, QStyle.StandardPixmap.SP_DriveHDIcon)
    return _standard(fallback)


class ThemeIconProvider(QFileIconProvider):
    """File icons resolved from the icon theme by MIME type.

    Qt's stock provider asks the platform theme for icons and returns nothing
    under a bare Hyprland session, leaving the file list with blank rows.
    Resolving names ourselves keeps icons working with no desktop environment.
    """

    def __init__(self) -> None:
        super().__init__()
        self._mime_db = QMimeDatabase()
        self._cache: dict[str, QIcon] = {}

    def _cached(self, key: str, names: list[str], fallback: QStyle.StandardPixmap) -> QIcon:
        icon = self._cache.get(key)
        if icon is None:
            icon = _first_available(names) or _standard(fallback)
            self._cache[key] = icon
        return icon

    def icon(self, arg):  # type: ignore[override]
        if not isinstance(arg, QFileInfo):
            return super().icon(arg)

        path = arg.absoluteFilePath()
        if arg.isDir():
            special = _special_folder_map().get(os.path.normpath(path))
            key = special or "folder"
            names = [special, "folder"] if special else ["folder"]
            return self._cached(key, names, QStyle.StandardPixmap.SP_DirIcon)

        # Extension-only matching: content sniffing would stat every row.
        mime = self._mime_db.mimeTypeForFile(
            path, QMimeDatabase.MatchMode.MatchExtension
        )
        names = [mime.iconName(), mime.genericIconName(), "text-x-generic"]
        return self._cached(
            mime.name(),
            [name for name in names if name],
            QStyle.StandardPixmap.SP_FileIcon,
        )
