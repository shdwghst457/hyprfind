"""Group keys for Finder-style "Group By" in the list view.

A group is described by a sort rank plus a heading. The rank keeps the buckets
in a sensible order (Today before Yesterday) rather than alphabetical, which is
what sorting on the heading text alone would give.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta

GROUP_NONE = "none"
GROUP_KIND = "kind"
GROUP_DATE_MODIFIED = "date"
GROUP_SIZE = "size"
GROUP_NAME = "name"

GROUP_LABELS = {
    GROUP_NONE: "None",
    GROUP_KIND: "Kind",
    GROUP_DATE_MODIFIED: "Date Modified",
    GROUP_SIZE: "Size",
    GROUP_NAME: "Name",
}

# (rank, heading) for size buckets, largest last.
_SIZE_BUCKETS = (
    (0, "Zero bytes", 1),
    (1, "Tiny (under 100 KB)", 100 * 1000),
    (2, "Small (under 10 MB)", 10 * 1000**2),
    (3, "Medium (under 1 GB)", 1000**3),
    (4, "Large (over 1 GB)", None),
)


def _date_group(timestamp: float, *, now: datetime | None = None) -> tuple[int, str]:
    now = now or datetime.now()
    try:
        moment = datetime.fromtimestamp(timestamp)
    except (OverflowError, OSError, ValueError):
        return (99, "Unknown Date")

    today = now.date()
    day = moment.date()
    if day == today:
        return (0, "Today")
    if day == today - timedelta(days=1):
        return (1, "Yesterday")
    if day > today - timedelta(days=7):
        return (2, "Previous 7 Days")
    if day > today - timedelta(days=30):
        return (3, "Previous 30 Days")
    if day.year == today.year:
        # Reverse month order so recent months come first within the year.
        return (4 + (12 - day.month), moment.strftime("%B"))
    return (100 + (today.year - day.year), str(day.year))


def _size_group(size: int) -> tuple[int, str]:
    for rank, heading, ceiling in _SIZE_BUCKETS:
        if ceiling is None or size < ceiling:
            return (rank, heading)
    return (9, "Unknown Size")


def _name_group(name: str) -> tuple[int, str]:
    first = name.lstrip(".")[:1].upper()
    if not first:
        return (2, "Other")
    if first.isdigit():
        return (0, "0–9")
    if first.isalpha():
        return (1, first)
    return (2, "Other")


def group_for(
    *,
    key: str,
    name: str,
    is_dir: bool,
    kind: str,
    size: int,
    mtime: float,
    now: datetime | None = None,
) -> tuple[int, str]:
    """Return ``(rank, heading)`` for one item under the given grouping."""
    if key == GROUP_KIND:
        # Folders are their own group, as in Finder, whatever the sort column.
        return (0, "Folders") if is_dir else (1, kind or "Document")
    if key == GROUP_DATE_MODIFIED:
        return _date_group(mtime, now=now)
    if key == GROUP_SIZE:
        return (0, "Folders") if is_dir else _size_group(size)
    if key == GROUP_NAME:
        return _name_group(name)
    return (0, "")


def group_for_path(key: str, path: str, kind: str = "") -> tuple[int, str]:
    """Convenience wrapper that stats `path` itself."""
    try:
        stat = os.stat(path)
        size, mtime = stat.st_size, stat.st_mtime
        is_dir = os.path.isdir(path)
    except OSError:
        size, mtime, is_dir = 0, 0.0, False
    return group_for(
        key=key,
        name=os.path.basename(path),
        is_dir=is_dir,
        kind=kind,
        size=size,
        mtime=mtime,
    )
