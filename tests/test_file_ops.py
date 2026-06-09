"""Tests for file transfer helpers."""

import os

from hyprfind.core.file_ops import TransferOp, transfer_items
from hyprfind.core.folder_size import (
    SIZE_COMPLETE,
    SIZE_ERROR,
    compute_folder_size,
)


def test_compute_folder_size(tmp_path):
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.txt").write_text("world!", encoding="utf-8")
    size, status = compute_folder_size(str(tmp_path))
    assert status == SIZE_COMPLETE and size == 11


def test_compute_folder_size_missing_is_error(tmp_path):
    size, status = compute_folder_size(str(tmp_path / "does-not-exist"))
    assert status == SIZE_ERROR and size == 0


def test_transfer_items_move(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "file.txt").write_text("data", encoding="utf-8")
    dest = tmp_path / "dest"
    dest.mkdir()
    errors = transfer_items(
        [str(src / "file.txt")], str(dest), operation=TransferOp.MOVE
    )
    assert errors == []
    assert (dest / "file.txt").exists()
    assert not (src / "file.txt").exists()


def test_transfer_items_copy(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "file.txt").write_text("data", encoding="utf-8")
    dest = tmp_path / "dest"
    dest.mkdir()
    errors = transfer_items(
        [str(src / "file.txt")], str(dest), operation=TransferOp.COPY
    )
    assert errors == []
    assert (dest / "file.txt").exists()
    assert (src / "file.txt").exists()


def test_transfer_items_copy_into_same_dir_keeps_both(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "file.txt").write_text("data", encoding="utf-8")
    errors = transfer_items(
        [str(src / "file.txt")], str(src), operation=TransferOp.COPY
    )
    assert errors == []
    assert (src / "file.txt").exists()
    assert (src / "file copy.txt").exists()


def test_transfer_items_alias_creates_symlink(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "file.txt").write_text("data", encoding="utf-8")
    dest = tmp_path / "dest"
    dest.mkdir()
    errors = transfer_items(
        [str(src / "file.txt")], str(dest), operation=TransferOp.ALIAS
    )
    assert errors == []
    link = dest / "file.txt"
    assert link.is_symlink()
    assert os.path.realpath(link) == str(src / "file.txt")


def test_transfer_items_move_refuses_overwrite(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "file.txt").write_text("data", encoding="utf-8")
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "file.txt").write_text("existing", encoding="utf-8")
    errors = transfer_items(
        [str(src / "file.txt")], str(dest), operation=TransferOp.MOVE
    )
    assert errors and "Already exists" in errors[0]
    assert (src / "file.txt").exists()
    assert (dest / "file.txt").read_text(encoding="utf-8") == "existing"
