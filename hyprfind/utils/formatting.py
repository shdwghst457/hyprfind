"""Human-readable size and date formatting."""

from __future__ import annotations

from PyQt6.QtCore import QDateTime


def format_date_modified(dt: QDateTime, column_width: int) -> str:
    """Finder-style date text that shortens as the column narrows."""
    if not dt.isValid():
        return ""

    now = QDateTime.currentDateTime()
    today = now.date()
    file_date = dt.date()
    time_text = dt.toString("h:mm AP")
    date_text = file_date.toString("M/d/yy")
    short_date = file_date.toString("M/d")

    if column_width >= 168:
        if file_date == today:
            return f"Today at {time_text}"
        yesterday = today.addDays(-1)
        if file_date == yesterday:
            return f"Yesterday at {time_text}"
        days_ago = file_date.daysTo(today)
        if 2 <= days_ago <= 6:
            return f"{file_date.toString('dddd')} at {time_text}"
        return f"{date_text} {time_text}"

    if column_width >= 112:
        return f"{date_text} {time_text}"

    if column_width >= 68:
        return date_text

    return short_date


def format_bytes(size: int) -> str:
    """Finder-style size text using decimal (base-1000) KB/MB/GB units."""
    if size < 0:
        return ""
    if size < 1000:
        return "1 byte" if size == 1 else f"{size} bytes"
    units = ["KB", "MB", "GB", "TB"]
    value = float(size)
    for unit in units:
        value /= 1000.0
        if value < 1000.0:
            return f"{value:.2f} {unit}"
    return f"{value:.2f} PB"
