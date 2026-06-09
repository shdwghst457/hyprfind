"""Tests for folder size queue and computation."""

from hyprfind.core.folder_size import (
    FolderSizeCalculator,
    compute_folder_size,
    list_child_directories,
)


def test_compute_folder_size_recursive(tmp_path):
    (tmp_path / "a.txt").write_text("12345", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "hidden.txt").write_text("999", encoding="utf-8")
    size, ok = compute_folder_size(str(tmp_path))
    assert ok
    assert size == 8


def test_compute_folder_size_empty_dir(tmp_path):
    folder = tmp_path / "empty"
    folder.mkdir()
    size, ok = compute_folder_size(str(folder))
    assert ok
    assert size == 0


def test_compute_folder_size_missing():
    size, ok = compute_folder_size("/nonexistent/path/xyz")
    assert not ok
    assert size is None


def test_schedule_all_paths(tmp_path):
    root = tmp_path / "share"
    folders = []
    for name in ("a", "b", "c", "d", "e"):
        folder = root / name
        folder.mkdir(parents=True)
        folders.append(str(folder.resolve()))
    calc = FolderSizeCalculator(is_network_path=lambda p: str(root) in p)
    queued = calc.schedule(folders)
    assert len(queued) == 5
    assert calc.pending_count() == 5


def test_list_child_directories(tmp_path):
    root = tmp_path / "root"
    (root / "a").mkdir(parents=True)
    (root / "b").mkdir()
    (root / "file.txt").write_text("x", encoding="utf-8")
    paths = list_child_directories(str(root))
    assert sorted(paths) == sorted(
        [str((root / "a").resolve()), str((root / "b").resolve())]
    )


def test_clear_pending_cancels_generation():
    calc = FolderSizeCalculator()
    gen_before = calc._generation
    calc.clear_pending()
    assert calc._generation == gen_before + 1
    assert calc._queued == []
