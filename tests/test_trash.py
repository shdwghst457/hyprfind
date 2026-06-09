"""Tests for trash operations."""

import os

from hyprfind.core.trash import empty_trash, move_to_trash, restore_from_trash, trash_files_dir


def test_move_and_restore(tmp_path, monkeypatch):
    trash_base = tmp_path / "Trash"
    files = trash_base / "files"
    info = trash_base / "info"
    files.mkdir(parents=True)
    info.mkdir(parents=True)
    monkeypatch.setattr("hyprfind.core.trash.trash_files_dir", lambda: files)
    monkeypatch.setattr("hyprfind.core.trash.trash_info_dir", lambda: info)
    monkeypatch.setattr("hyprfind.core.trash.trash_dir", lambda: trash_base)

    src = tmp_path / "document.txt"
    src.write_text("hello", encoding="utf-8")
    result = move_to_trash(str(src))
    assert result is not None
    trash_path, original = result
    assert not src.exists()
    assert os.path.exists(trash_path)

    restored = restore_from_trash(trash_path)
    assert restored == original
    assert src.exists()
    assert src.read_text(encoding="utf-8") == "hello"


def test_empty_trash(tmp_path, monkeypatch):
    trash_base = tmp_path / "Trash"
    files = trash_base / "files"
    info = trash_base / "info"
    files.mkdir(parents=True)
    info.mkdir(parents=True)
    monkeypatch.setattr("hyprfind.core.trash.trash_files_dir", lambda: files)
    monkeypatch.setattr("hyprfind.core.trash.trash_info_dir", lambda: info)
    monkeypatch.setattr("hyprfind.core.trash.trash_dir", lambda: trash_base)

    f = files / "gone.txt"
    f.write_text("x", encoding="utf-8")
    (info / "gone.txt.trashinfo").write_text(
        "[Trash Info]\nPath=/tmp/gone.txt\nDeletionDate=2024-01-01T00:00:00\n",
        encoding="utf-8",
    )
    errors = empty_trash()
    assert errors == []
    assert not f.exists()
