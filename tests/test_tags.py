"""Tests for xattr-backed file tags."""

import os

import pytest

from hyprfind.core.tags import (
    XATTR_TAGS,
    add_tag,
    all_tags,
    color_for,
    common_tags,
    read_tags,
    remove_tag,
    supports_tags,
    toggle_tag,
    write_tags,
)


@pytest.fixture
def tagged_file(tmp_path):
    path = tmp_path / "file.txt"
    path.write_text("x")
    if not supports_tags(str(path)):
        pytest.skip("filesystem has no extended attribute support")
    return str(path)


def test_no_tags_initially(tagged_file):
    assert read_tags(tagged_file) == []


def test_write_and_read_roundtrip(tagged_file):
    assert write_tags(tagged_file, ["Red", "Work"]).ok
    assert read_tags(tagged_file) == ["Red", "Work"]


def test_written_value_matches_freedesktop_format(tagged_file):
    """Dolphin and Nautilus read the same key, so the encoding must match."""
    write_tags(tagged_file, ["Red", "Work"])
    raw = os.getxattr(tagged_file, XATTR_TAGS)
    assert raw == b"Red,Work"


def test_duplicates_and_blanks_collapsed(tagged_file):
    write_tags(tagged_file, ["Red", " Red ", "", "  ", "Blue"])
    assert read_tags(tagged_file) == ["Red", "Blue"]


def test_add_tag_is_idempotent(tagged_file):
    add_tag(tagged_file, "Green")
    add_tag(tagged_file, "Green")
    assert read_tags(tagged_file) == ["Green"]


def test_remove_tag(tagged_file):
    write_tags(tagged_file, ["Red", "Blue", "Green"])
    assert remove_tag(tagged_file, "Blue").ok
    assert read_tags(tagged_file) == ["Red", "Green"]


def test_remove_missing_tag_succeeds(tagged_file):
    write_tags(tagged_file, ["Red"])
    assert remove_tag(tagged_file, "Purple").ok
    assert read_tags(tagged_file) == ["Red"]


def test_toggle_tag(tagged_file):
    toggle_tag(tagged_file, "Yellow")
    assert read_tags(tagged_file) == ["Yellow"]
    toggle_tag(tagged_file, "Yellow")
    assert read_tags(tagged_file) == []


def test_clearing_removes_the_attribute(tagged_file):
    write_tags(tagged_file, ["Red"])
    assert write_tags(tagged_file, []).ok
    assert XATTR_TAGS not in os.listxattr(tagged_file)
    # Clearing again is still a success, not an error.
    assert write_tags(tagged_file, []).ok


def test_missing_file_reads_empty_and_fails_to_write(tmp_path):
    missing = str(tmp_path / "gone.txt")
    assert read_tags(missing) == []
    result = write_tags(missing, ["Red"])
    assert not result.ok
    assert "gone.txt" in result.error


def test_common_tags_is_the_intersection(tmp_path):
    paths = []
    for name, tags in (("a", ["Red", "Work"]), ("b", ["Red", "Home"])):
        path = tmp_path / name
        path.write_text("x")
        if not supports_tags(str(path)):
            pytest.skip("filesystem has no extended attribute support")
        write_tags(str(path), tags)
        paths.append(str(path))

    assert common_tags(paths) == ["Red"]
    # Every tag on any item, standard colours first then custom alphabetically.
    assert all_tags(paths) == ["Red", "Home", "Work"]


def test_common_tags_of_nothing():
    assert common_tags([]) == []


def test_colors_only_for_standard_tags():
    assert color_for("Red") == "#ff5f57"
    assert color_for("red") == "#ff5f57"  # capitalisation tolerated
    assert color_for("Taxes") is None
