"""Tests for progress reporting and cancellation during transfers."""

import os

from hyprfind.core.file_ops import (
    TransferMonitor,
    TransferOp,
    estimate_transfer_size,
    transfer_items,
)
from hyprfind.ui.transfer_dialog import _TransferWorker, should_show_progress


def make_tree(root, files: dict[str, int]) -> list[str]:
    """Create files under `root`; values are byte counts."""
    for name, size in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * size)
    return [str(root / name) for name in files]


def test_estimate_counts_nested_files(tmp_path):
    make_tree(tmp_path / "src", {"a.bin": 1000, "sub/b.bin": 2500, "sub/c.bin": 500})
    total, count = estimate_transfer_size([str(tmp_path / "src")])
    assert total == 4000
    assert count == 3


def test_estimate_handles_missing_paths(tmp_path):
    total, count = estimate_transfer_size([str(tmp_path / "nope")])
    assert total == 0
    assert count == 1


def test_estimate_does_not_follow_symlinks(tmp_path):
    target = tmp_path / "real.bin"
    target.write_bytes(b"y" * 5000)
    link = tmp_path / "link.bin"
    link.symlink_to(target)
    total, count = estimate_transfer_size([str(link)])
    assert total == 0  # the link itself, not its target
    assert count == 1


def test_copy_reports_progress(tmp_path):
    sources = make_tree(tmp_path / "src", {"big.bin": 3 * 1024 * 1024})
    dest = tmp_path / "dst"
    dest.mkdir()

    seen: list[int] = []
    monitor = TransferMonitor(
        total_bytes=3 * 1024 * 1024,
        on_progress=lambda copied, _total, _name: seen.append(copied),
    )
    errors = transfer_items(
        sources, str(dest), operation=TransferOp.COPY, monitor=monitor
    )

    assert errors == []
    assert (dest / "big.bin").read_bytes() == b"x" * (3 * 1024 * 1024)
    # Chunked, so progress arrives incrementally and ends at the total.
    assert len(seen) > 1
    assert monitor.copied_bytes == 3 * 1024 * 1024


def test_cancel_stops_copy_midway(tmp_path):
    """Cancelling must abort promptly and leave later sources untouched."""
    sources = make_tree(
        tmp_path / "src", {"a.bin": 1024 * 1024, "b.bin": 1024 * 1024, "c.bin": 1024 * 1024}
    )
    dest = tmp_path / "dst"
    dest.mkdir()

    state = {"cancel": False}

    def on_progress(copied, _total, _name):
        if copied > 0:
            state["cancel"] = True

    monitor = TransferMonitor(
        total_bytes=3 * 1024 * 1024,
        on_progress=on_progress,
        should_cancel=lambda: state["cancel"],
    )
    transfer_items(sources, str(dest), operation=TransferOp.COPY, monitor=monitor)

    assert monitor.cancelled
    assert monitor.copied_bytes < 3 * 1024 * 1024
    # The sources are never touched by a copy, cancelled or not.
    for source in sources:
        assert os.path.exists(source)


def test_cancelled_move_keeps_source(tmp_path):
    sources = make_tree(tmp_path / "src", {"big.bin": 4 * 1024 * 1024})
    dest = tmp_path / "dst"
    dest.mkdir()

    monitor = TransferMonitor(total_bytes=4 * 1024 * 1024, should_cancel=lambda: True)
    transfer_items(sources, str(dest), operation=TransferOp.MOVE, monitor=monitor)

    assert monitor.cancelled
    assert os.path.exists(sources[0])


def test_directory_copy_preserves_structure(tmp_path):
    make_tree(tmp_path / "src", {"top.bin": 10, "deep/nested/leaf.bin": 20})
    dest = tmp_path / "dst"
    dest.mkdir()

    monitor = TransferMonitor(total_bytes=30)
    errors = transfer_items(
        [str(tmp_path / "src")], str(dest), operation=TransferOp.COPY, monitor=monitor
    )

    assert errors == []
    assert (dest / "src" / "top.bin").exists()
    assert (dest / "src" / "deep" / "nested" / "leaf.bin").read_bytes() == b"x" * 20


def test_monitor_free_path_still_works(tmp_path):
    """Without a monitor the fast shutil path is used and must behave the same."""
    make_tree(tmp_path / "src", {"a.bin": 64, "sub/b.bin": 64})
    dest = tmp_path / "dst"
    dest.mkdir()
    errors = transfer_items(
        [str(tmp_path / "src")], str(dest), operation=TransferOp.COPY
    )
    assert errors == []
    assert (dest / "src" / "sub" / "b.bin").exists()


def test_progress_survives_transfers_over_two_gibibytes():
    """Byte counts past 2**31 must not wrap on their way out of the worker."""
    huge = 6 * 1024**3
    worker = _TransferWorker(
        [], "/tmp", TransferOp.COPY, total_bytes=huge, total_items=1, on_conflict=None
    )
    seen: list[tuple[int, int]] = []
    worker.progress.connect(lambda copied, total, _name: seen.append((copied, total)))

    worker.progress.emit(huge // 2, huge, "movie.mkv")

    assert seen == [(huge // 2, huge)]


def test_progress_threshold():
    """Tiny jobs must not flash a dialog; big or numerous ones should."""
    assert not should_show_progress(1024, 1)
    assert should_show_progress(64 * 1024 * 1024, 1)
    assert should_show_progress(1024, 500)
