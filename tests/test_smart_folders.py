"""Tests for smart folder persistence and query resolution."""

from hyprfind.core.search import SCOPE_EVERYWHERE, SCOPE_HERE
from hyprfind.core.smart_folders import SmartFolder, SmartFolderStore

HOME = "/home/user"
CWD = "/mnt/share/media"


def test_scope_home_ignores_current_directory():
    folder = SmartFolder(name="PDFs", query="*.pdf", scope=SCOPE_EVERYWHERE)
    assert folder.roots(CWD, HOME) == [HOME]


def test_scope_here_follows_the_browsed_folder():
    folder = SmartFolder(name="Here", query="report", scope=SCOPE_HERE)
    assert folder.roots(CWD, HOME) == [CWD]
    # With nothing being browsed, fall back to home rather than searching "".
    assert folder.roots("", HOME) == [HOME]


def test_pinned_root_wins_over_scope():
    folder = SmartFolder(
        name="Pinned", query="x", scope=SCOPE_HERE, root="/mnt/Anime"
    )
    assert folder.roots(CWD, HOME) == ["/mnt/Anime"]


def test_to_query_carries_the_options():
    folder = SmartFolder(
        name="Hidden dirs",
        query="cache",
        scope=SCOPE_EVERYWHERE,
        include_hidden=True,
        directories_only=True,
    )
    query = folder.to_query(CWD, HOME)
    assert query.text == "cache"
    assert query.roots == [HOME]
    assert query.include_hidden
    assert query.directories_only


def test_describe_summarises():
    assert "“*.pdf” in Home" in SmartFolder(name="a", query="*.pdf").describe()
    assert "this folder" in SmartFolder(
        name="a", query="x", scope=SCOPE_HERE
    ).describe()
    assert "folders only" in SmartFolder(
        name="a", query="x", directories_only=True
    ).describe()


def test_store_roundtrip(tmp_path):
    path = tmp_path / "smart.json"
    store = SmartFolderStore(path)
    store.add(SmartFolder(name="PDFs", query="*.pdf", include_hidden=True))
    store.add(SmartFolder(name="Here", query="todo", scope=SCOPE_HERE))

    reopened = SmartFolderStore(path)
    reopened.load()
    folders = reopened.all()
    assert [f.name for f in folders] == ["PDFs", "Here"]
    assert folders[0].include_hidden
    assert folders[1].scope == SCOPE_HERE


def test_legacy_entries_still_load(tmp_path):
    """Files written before scopes existed searched the whole home."""
    path = tmp_path / "smart.json"
    path.write_text('{"folders": [{"name": "Old", "query": "report"}]}')
    store = SmartFolderStore(path)
    store.load()
    folder = store.all()[0]
    assert folder.scope == SCOPE_EVERYWHERE
    assert folder.root == ""
    assert not folder.include_hidden


def test_malformed_entries_skipped(tmp_path):
    path = tmp_path / "smart.json"
    path.write_text(
        '{"folders": ['
        '{"name": "ok", "query": "x"},'
        '{"name": "", "query": "x"},'
        '{"name": "no query", "query": "  "},'
        '{"query": "nameless"},'
        '"not an object"'
        "]}"
    )
    store = SmartFolderStore(path)
    store.load()
    assert [f.name for f in store.all()] == ["ok"]


def test_corrupt_file_is_not_fatal(tmp_path):
    path = tmp_path / "smart.json"
    path.write_text("{{{")
    store = SmartFolderStore(path)
    store.load()
    assert store.all() == []


def test_remove_and_reorder(tmp_path):
    store = SmartFolderStore(tmp_path / "smart.json")
    for name in ("a", "b", "c"):
        store.add(SmartFolder(name=name, query=name))

    assert store.move(2, -1) == 1
    assert [f.name for f in store.all()] == ["a", "c", "b"]
    # Moving past either end is a no-op rather than an error.
    assert store.move(0, -1) == 0
    assert store.move(2, 1) == 2

    store.remove(0)
    assert [f.name for f in store.all()] == ["c", "b"]
    store.remove(99)
    assert len(store.all()) == 2


def test_replace_all_persists(tmp_path):
    path = tmp_path / "smart.json"
    store = SmartFolderStore(path)
    store.add(SmartFolder(name="gone", query="x"))
    store.replace_all([SmartFolder(name="kept", query="y")])

    reopened = SmartFolderStore(path)
    reopened.load()
    assert [f.name for f in reopened.all()] == ["kept"]
