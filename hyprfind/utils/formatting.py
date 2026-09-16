"""Human-readable size and date formatting."""

from __future__ import annotations

from PyQt6.QtCore import QDateTime


# Worst-case text per detail tier. A column must be sized against these rather
# than against each row's own text, or neighbouring rows pick different formats
# and the column reads raggedly.
DATE_TIER_SAMPLES = (
    "Wednesday at 12:58 PM",
    "12/31/26 12:58 PM",
    "12/31/26",
    "12/31",
)


def date_modified_tiers(dt: QDateTime) -> list[str]:
    """Date texts from most to least detailed, aligned with DATE_TIER_SAMPLES."""
    if not dt.isValid():
        return ["", "", "", ""]

    today = QDateTime.currentDateTime().date()
    file_date = dt.date()
    time_text = dt.toString("h:mm AP")
    date_text = file_date.toString("M/d/yy")
    full = f"{date_text} {time_text}"

    if file_date == today:
        relative = f"Today at {time_text}"
    elif file_date == today.addDays(-1):
        relative = f"Yesterday at {time_text}"
    elif 2 <= file_date.daysTo(today) <= 6:
        relative = f"{file_date.toString('dddd')} at {time_text}"
    else:
        relative = full

    return [relative, full, date_text, file_date.toString("M/d")]


def format_date_modified(dt: QDateTime, column_width: int) -> str:
    """Finder-style date text that shortens as the column narrows."""
    tiers = date_modified_tiers(dt)
    if column_width >= 168:
        return tiers[0]
    if column_width >= 112:
        return tiers[1]
    if column_width >= 68:
        return tiers[2]
    return tiers[3]


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
