"""Tests for the persistent folder-size cache."""

import os
import time

from hyprfind.core.size_cache import PersistentSizeCache


def test_put_and_get_valid(tmp_path):
    folder = tmp_path / "folder"
    folder.mkdir()
    cache = PersistentSizeCache(tmp_path / "sizes.json")
    cache.put(str(folder), 1234)
    assert cache.get_valid(str(folder)) == 1234


def test_invalidated_when_directory_changes(tmp_path):
    folder = tmp_path / "folder"
    folder.mkdir()
    cache = PersistentSizeCache(tmp_path / "sizes.json")
    cache.put(str(folder), 1234)
    # Adding an entry bumps the directory mtime.
    time.sleep(0.01)
    (folder / "new.txt").write_text("x", encoding="utf-8")
    assert cache.get_valid(str(folder)) is None


def test_save_and_load_round_trip(tmp_path):
    folder = tmp_path / "folder"
    folder.mkdir()
    path = tmp_path / "sizes.json"
    cache = PersistentSizeCache(path)
    cache.put(str(folder), 999)
    cache.save_if_dirty()
    assert path.exists()

    reloaded = PersistentSizeCache(path)
    reloaded.load()
    assert reloaded.get_valid(str(folder)) == 999


def test_discard(tmp_path):
    folder = tmp_path / "folder"
    folder.mkdir()
    cache = PersistentSizeCache(tmp_path / "sizes.json")
    cache.put(str(folder), 5)
    cache.discard(str(folder))
    assert cache.get_valid(str(folder)) is None


def test_get_valid_prunes_missing_directory(tmp_path):
    folder = tmp_path / "folder"
    folder.mkdir()
    cache = PersistentSizeCache(tmp_path / "sizes.json")
    cache.put(str(folder), 7)
    os.rmdir(folder)
    assert cache.get_valid(str(folder)) is None
    # Entry should have been pruned and marked dirty for the next save.
    assert cache.dirty
