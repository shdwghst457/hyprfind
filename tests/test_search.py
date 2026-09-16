"""Tests for the recursive search engine."""

import os

from hyprfind.core.search import (
    SCOPE_EVERYWHERE,
    SCOPE_HERE,
    SearchQuery,
    SearchWorker,
    _is_pruned,
    search_roots,
)


def build_tree(root):
    (root / "a" / "b").mkdir(parents=True)
    (root / "Reports").mkdir()
    (root / ".hidden").mkdir()
    (root / "a" / "report-2024.txt").write_text("x")
    (root / "a" / "b" / "REPORT-2025.TXT").write_text("x")
    (root / "a" / "b" / "notes.md").write_text("x")
    (root / ".hidden" / "secret-report.txt").write_text("x")
    (root / "other.bin").write_text("x")


def collect(query: SearchQuery) -> tuple[list[str], bool, bool]:
    """Run a search synchronously and return (names, cancelled, truncated)."""
    worker = SearchWorker(query)
    names: list[str] = []
    outcome: dict = {}
    worker.hitsFound.connect(lambda hits: names.extend(h.name for h in hits))
    worker.finished.connect(
        lambda total, cancelled, truncated: outcome.update(
            total=total, cancelled=cancelled, truncated=truncated
        )
    )
    worker.run()
    return sorted(names), outcome["cancelled"], outcome["truncated"]


def test_finds_matches_at_every_depth(tmp_path):
    build_tree(tmp_path)
    names, _, _ = collect(SearchQuery(text="report", roots=[str(tmp_path)]))
    # Case-insensitive, and folders count as results too.
    assert names == ["REPORT-2025.TXT", "Reports", "report-2024.txt"]


def test_hidden_entries_excluded_by_default(tmp_path):
    build_tree(tmp_path)
    names, _, _ = collect(SearchQuery(text="secret", roots=[str(tmp_path)]))
    assert names == []

    names, _, _ = collect(
        SearchQuery(text="secret", roots=[str(tmp_path)], include_hidden=True)
    )
    assert names == ["secret-report.txt"]


def test_wildcards_use_glob_semantics(tmp_path):
    build_tree(tmp_path)
    names, _, _ = collect(SearchQuery(text="*.md", roots=[str(tmp_path)]))
    assert names == ["notes.md"]

    # Anchored at the start, so a trailing wildcard is a prefix match.
    names, _, _ = collect(SearchQuery(text="report*", roots=[str(tmp_path)]))
    assert names == ["REPORT-2025.TXT", "Reports", "report-2024.txt"]

    # Anchored at the end too: "*.md" above matched nothing else, and a glob
    # with no wildcard at the front will not match mid-name.
    names, _, _ = collect(SearchQuery(text="2024*", roots=[str(tmp_path)]))
    assert names == []


def test_directories_only(tmp_path):
    build_tree(tmp_path)
    names, _, _ = collect(
        SearchQuery(text="report", roots=[str(tmp_path)], directories_only=True)
    )
    assert names == ["Reports"]


def test_empty_query_finds_nothing(tmp_path):
    build_tree(tmp_path)
    names, _, _ = collect(SearchQuery(text="   ", roots=[str(tmp_path)]))
    assert names == []


def test_unreadable_directory_is_skipped(tmp_path):
    build_tree(tmp_path)
    locked = tmp_path / "locked"
    locked.mkdir()
    (locked / "report-x.txt").write_text("x")
    os.chmod(locked, 0o000)
    try:
        names, _, _ = collect(SearchQuery(text="report", roots=[str(tmp_path)]))
        # The walk continues past the unreadable folder rather than aborting.
        assert "report-2024.txt" in names
    finally:
        os.chmod(locked, 0o755)


def test_symlink_loop_does_not_hang(tmp_path):
    """A directory symlink pointing at an ancestor must not recurse forever."""
    build_tree(tmp_path)
    (tmp_path / "a" / "loop").symlink_to(tmp_path, target_is_directory=True)
    names, _, _ = collect(SearchQuery(text="report", roots=[str(tmp_path)]))
    assert "report-2024.txt" in names


def test_cancel_reports_cancelled(tmp_path):
    build_tree(tmp_path)
    worker = SearchWorker(SearchQuery(text="report", roots=[str(tmp_path)]))
    worker.cancel()
    outcome: dict = {}
    worker.finished.connect(
        lambda total, cancelled, truncated: outcome.update(cancelled=cancelled)
    )
    worker.run()
    assert outcome["cancelled"]


def test_kernel_trees_pruned():
    assert _is_pruned("/proc")
    assert _is_pruned("/sys/devices")
    assert _is_pruned("/dev/shm")
    assert not _is_pruned("/home/user/proc-notes")


def test_search_roots_scope():
    home = "/home/user"
    assert search_roots(SCOPE_HERE, "/mnt/share", home) == ["/mnt/share"]
    assert search_roots(SCOPE_EVERYWHERE, "/mnt/share", home) == [home]
    # No current directory: fall back to home rather than searching nothing.
    assert search_roots(SCOPE_HERE, "", home) == [home]
