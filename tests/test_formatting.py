"""Tests for display formatting helpers."""

from PyQt6.QtCore import QDate, QDateTime, QTime

from hyprfind.utils.formatting import format_date_modified


def test_format_date_modified_full_width_today():
    today = QDate.currentDate()
    dt = QDateTime(today, QTime(15, 16))
    text = format_date_modified(dt, 200)
    assert text.startswith("Today at ")


def test_format_date_modified_compact_date():
    dt = QDateTime(QDate(2026, 5, 6), QTime(15, 16))
    assert format_date_modified(dt, 90) == "5/6/26"


def test_format_date_modified_minimal():
    dt = QDateTime(QDate(2026, 5, 6), QTime(15, 16))
    assert format_date_modified(dt, 50) == "5/6"
