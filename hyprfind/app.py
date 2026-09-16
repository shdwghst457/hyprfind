"""Application entry point."""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication

from hyprfind.ui.icons import configure_icon_theme
from hyprfind.ui.main_window import MainWindow


def _style_path() -> Path:
    return Path(__file__).parent / "ui" / "styles" / "dark.qss"


def _branch_style() -> str:
    icons = Path(__file__).parent / "ui" / "styles" / "icons"
    closed = (icons / "branch-closed.svg").as_posix()
    open_ = (icons / "branch-open.svg").as_posix()
    return f"""
QTreeView::branch {{
    background: transparent;
    border: none;
}}
QTreeView::branch:selected {{
    background: transparent;
}}
QTreeView::branch:has-children:closed,
QTreeView::branch:closed:has-children {{
    image: url({closed});
}}
QTreeView::branch:open:has-children,
QTreeView::branch:open {{
    image: url({open_});
}}
"""


def _apply_dark_palette(app: QApplication) -> None:
    """Match the palette to dark.qss so native-drawn widgets blend in."""
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#1c1c1e"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#e8e8ea"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#1c1c1e"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#202023"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#2c2c2e"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#e8e8ea"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#e8e8ea"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#3a3a3d"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#e8e8ea"))
    palette.setColor(QPalette.ColorRole.BrightText, Qt.GlobalColor.red)
    palette.setColor(QPalette.ColorRole.Link, QColor("#0a6cf0"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#0a6cf0"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#8e8e93"))
    palette.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#5a5a5e")
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor("#5a5a5e")
    )
    app.setPalette(palette)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("HyprFind")
    app.setOrganizationName("hyprfind")
    app.setDesktopFileName("hyprfind")

    _apply_dark_palette(app)
    configure_icon_theme()

    stylesheet = ""
    qss_path = _style_path()
    if qss_path.exists():
        stylesheet += qss_path.read_text(encoding="utf-8")
    stylesheet += _branch_style()
    app.setStyleSheet(stylesheet)

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
