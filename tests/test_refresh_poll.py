"""Tests for directory polling refresh logic."""

from hyprfind.core.refresh import (
    directory_snapshot,
    snapshots_differ,
    strategy_for,
)
from hyprfind.core.mounts import MountService, parse_mounts


SAMPLE_MOUNTS = """\
/dev/sda1 / ext4 rw 0 0
//server/share /mnt/smb/share cifs rw 0 0
"""


def test_snapshots_differ_detects_add():
    before = {"a.txt": (100, 10)}
    after = {"a.txt": (100, 10), "b.txt": (200, 20)}
    assert snapshots_differ(before, after)


def test_snapshots_differ_detects_remove():
    before = {"a.txt": (100, 10), "b.txt": (200, 20)}
    after = {"a.txt": (100, 10)}
    assert snapshots_differ(before, after)


def test_snapshots_differ_detects_mtime_change():
    before = {"a.txt": (100, 10)}
    after = {"a.txt": (101, 10)}
    assert snapshots_differ(before, after)


def test_snapshots_differ_unchanged():
    snap = {"a.txt": (100, 10)}
    assert not snapshots_differ(snap, dict(snap))


def test_strategy_for_cifs():
    service = MountService()
    service._mounts = parse_mounts(SAMPLE_MOUNTS)
    assert strategy_for("/mnt/smb/share", service) == "poll"


def test_strategy_for_local():
    service = MountService()
    service._mounts = parse_mounts(SAMPLE_MOUNTS)
    assert strategy_for("/home/user", service) == "inotify"


def test_directory_snapshot(tmp_path):
    (tmp_path / "one.txt").write_text("hello", encoding="utf-8")
    (tmp_path / "two.txt").write_text("world", encoding="utf-8")
    snap = directory_snapshot(str(tmp_path))
    assert "one.txt" in snap
    assert "two.txt" in snap
    assert "." not in snap
