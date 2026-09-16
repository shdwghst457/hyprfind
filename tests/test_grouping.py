"""Tests for Group By bucket assignment."""

from datetime import datetime, timedelta

from hyprfind.core.grouping import (
    GROUP_DATE_MODIFIED,
    GROUP_KIND,
    GROUP_NAME,
    GROUP_NONE,
    GROUP_SIZE,
    group_for,
)

NOW = datetime(2026, 6, 15, 12, 0, 0)


def date_group(days_ago: float) -> str:
    moment = NOW - timedelta(days=days_ago)
    return group_for(
        key=GROUP_DATE_MODIFIED,
        name="f",
        is_dir=False,
        kind="",
        size=0,
        mtime=moment.timestamp(),
        now=NOW,
    )[1]


def kind_group(name: str, kind: str, is_dir: bool = False) -> str:
    return group_for(
        key=GROUP_KIND, name=name, is_dir=is_dir, kind=kind, size=0, mtime=0.0
    )[1]


def size_group(size: int, is_dir: bool = False) -> str:
    return group_for(
        key=GROUP_SIZE, name="f", is_dir=is_dir, kind="", size=size, mtime=0.0
    )[1]


def name_group(name: str) -> str:
    return group_for(
        key=GROUP_NAME, name=name, is_dir=False, kind="", size=0, mtime=0.0
    )[1]


def test_no_grouping_yields_blank():
    assert group_for(
        key=GROUP_NONE, name="f", is_dir=False, kind="", size=0, mtime=0.0
    ) == (0, "")


def test_kind_groups_folders_separately():
    assert kind_group("docs", "Folder", is_dir=True) == "Folders"
    assert kind_group("a.png", "PNG image") == "PNG image"
    # A file whose kind is unknown still lands somewhere sensible.
    assert kind_group("mystery", "") == "Document"


def test_date_buckets():
    assert date_group(0) == "Today"
    assert date_group(1) == "Yesterday"
    assert date_group(4) == "Previous 7 Days"
    assert date_group(20) == "Previous 30 Days"
    # Earlier in the same year gets a month name; prior years get the year.
    assert date_group(90) == "March"
    assert date_group(400) == "2025"


def test_date_buckets_are_ordered_most_recent_first():
    """Rank, not label, drives ordering, so months must not sort alphabetically."""
    ranks = [
        group_for(
            key=GROUP_DATE_MODIFIED,
            name="f",
            is_dir=False,
            kind="",
            size=0,
            mtime=(NOW - timedelta(days=days)).timestamp(),
            now=NOW,
        )[0]
        for days in (0, 1, 4, 20, 90, 400)
    ]
    assert ranks == sorted(ranks)


def test_unreadable_timestamp_is_grouped_not_crashed():
    assert group_for(
        key=GROUP_DATE_MODIFIED,
        name="f",
        is_dir=False,
        kind="",
        size=0,
        mtime=float("inf"),
        now=NOW,
    )[1] == "Unknown Date"


def test_size_buckets():
    assert size_group(0) == "Zero bytes"
    assert size_group(50_000) == "Tiny (under 100 KB)"
    assert size_group(5_000_000) == "Small (under 10 MB)"
    assert size_group(500_000_000) == "Medium (under 1 GB)"
    assert size_group(5_000_000_000) == "Large (over 1 GB)"
    # Folder sizes are not comparable to file sizes, so they get their own group.
    assert size_group(0, is_dir=True) == "Folders"


def test_name_buckets():
    assert name_group("apple") == "A"
    assert name_group("Apple") == "A"
    assert name_group("2024-report") == "0–9"
    assert name_group("_private") == "Other"
    # A leading dot is skipped so hidden files group by their real initial.
    assert name_group(".bashrc") == "B"
    assert name_group("") == "Other"
