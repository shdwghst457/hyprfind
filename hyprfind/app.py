"""Application entry point."""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication

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
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(30, 30, 30))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(224, 224, 224))
    palette.setColor(QPalette.ColorRole.Base, QColor(25, 25, 25))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(37, 37, 37))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(42, 42, 42))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(224, 224, 224))
    palette.setColor(QPalette.ColorRole.Text, QColor(224, 224, 224))
    palette.setColor(QPalette.ColorRole.Button, QColor(42, 42, 42))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(224, 224, 224))
    palette.setColor(QPalette.ColorRole.BrightText, Qt.GlobalColor.red)
    palette.setColor(QPalette.ColorRole.Link, QColor(74, 122, 184))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(61, 90, 128))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    app.setPalette(palette)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("HyprFind")
    app.setOrganizationName("hyprfind")
    app.setDesktopFileName("hyprfind")

    _apply_dark_palette(app)

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
