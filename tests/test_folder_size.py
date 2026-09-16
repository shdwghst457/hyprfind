"""Tests for folder size queue and computation."""

from hyprfind.core.folder_size import (
    SIZE_COMPLETE,
    SIZE_ERROR,
    FolderSizeCalculator,
    compute_folder_size,
    list_child_directories,
)


def test_compute_folder_size_recursive(tmp_path):
    (tmp_path / "a.txt").write_text("12345", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "hidden.txt").write_text("999", encoding="utf-8")
    size, status = compute_folder_size(str(tmp_path))
    assert status == SIZE_COMPLETE
    assert size == 8


def test_compute_folder_size_empty_dir(tmp_path):
    folder = tmp_path / "empty"
    folder.mkdir()
    size, status = compute_folder_size(str(folder))
    assert status == SIZE_COMPLETE
    assert size == 0


def test_compute_folder_size_missing():
    """An unreadable folder reports ERROR so the cell shows "—", not "0 bytes"."""
    size, status = compute_folder_size("/nonexistent/path/xyz")
    assert status == SIZE_ERROR
    assert size == 0


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


# Anything past 2**31 is where a 32-bit signal parameter wraps around: 3 GiB
# arrived as a negative number (shown as a blank cell) and 74 GB as 1.15 GB.
HUGE = 3 * 1024**3 + 12345


def test_a_folder_larger_than_two_gibibytes_is_measured_exactly(tmp_path):
    # Sparse file: a real 3 GiB st_size without occupying 3 GiB of disk.
    with open(tmp_path / "movie.mkv", "wb") as handle:
        handle.truncate(HUGE)
    size, status = compute_folder_size(str(tmp_path))
    assert status == SIZE_COMPLETE
    assert size == HUGE


def test_a_huge_size_survives_the_trip_from_the_worker_thread(tmp_path):
    """The walk is only half the job; the size has to reach the view unharmed."""
    calc = FolderSizeCalculator(persistent_path=tmp_path / "sizes.json")
    seen: dict[str, int] = {}
    calc.sizeReady.connect(lambda path, size: seen.__setitem__(path, size))

    folder = str(tmp_path)
    calc._signals.finished.emit(folder, HUGE, SIZE_COMPLETE, calc._generation, False)

    assert seen[folder] == HUGE
    assert calc.cached_size(folder) == HUGE


def test_an_impossible_negative_size_is_reported_as_unreadable(tmp_path):
    """A byte count below zero means something mangled it — never show "0 bytes"."""
    calc = FolderSizeCalculator(persistent_path=tmp_path / "sizes.json")
    failed: list[str] = []
    ready: list[str] = []
    calc.sizeFailed.connect(failed.append)
    calc.sizeReady.connect(lambda path, _size: ready.append(path))

    folder = str(tmp_path)
    calc._signals.finished.emit(folder, -874749358, SIZE_COMPLETE, calc._generation, False)

    assert failed == [folder]
    assert ready == []
    assert calc.is_failed(folder)
