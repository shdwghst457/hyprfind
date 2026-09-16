"""Tests for how much of a name is preselected when a rename starts."""

import os

from hyprfind.ui.list_delegate import _rename_selection_length


class FakeIndex:
    """Stands in for a model index that reports a file path."""

    def __init__(self, path: str) -> None:
        self._path = path

    def data(self, _role):
        return self._path


def preselected(path: str) -> str:
    name = os.path.basename(path)
    return name[: _rename_selection_length(FakeIndex(path), name)]


def test_file_extension_is_left_out(tmp_path):
    target = tmp_path / "report.txt"
    target.touch()
    assert preselected(str(target)) == "report"


def test_only_the_last_extension_is_left_out(tmp_path):
    target = tmp_path / "report.tar.gz"
    target.touch()
    assert preselected(str(target)) == "report.tar"


def test_file_without_an_extension_selects_everything(tmp_path):
    target = tmp_path / "README"
    target.touch()
    assert preselected(str(target)) == "README"


def test_dotfile_selects_everything(tmp_path):
    """".bashrc" is a name, not an extension, so keeping the stem would select nothing."""
    target = tmp_path / ".bashrc"
    target.touch()
    assert preselected(str(target)) == ".bashrc"


def test_folder_name_selects_everything(tmp_path):
    target = tmp_path / "New Folder With Items"
    target.mkdir()
    assert preselected(str(target)) == "New Folder With Items"


def test_folder_with_a_dot_still_selects_everything(tmp_path):
    target = tmp_path / "backup.old"
    target.mkdir()
    assert preselected(str(target)) == "backup.old"


def test_empty_name_selects_nothing(tmp_path):
    assert _rename_selection_length(FakeIndex(str(tmp_path)), "") == 0


def test_a_missing_path_is_treated_as_a_file(tmp_path):
    """The row can vanish between the refresh and the deferred selection."""
    gone = tmp_path / "vanished.txt"
    assert preselected(str(gone)) == "vanished"


def test_a_non_string_path_is_tolerated():
    assert _rename_selection_length(FakeIndex(None), "notes.txt") == len("notes")
