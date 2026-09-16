"""Tests for server URI handling and the recent-servers store."""

from hyprfind.core.servers import (
    ServerStore,
    _last_meaningful_line,
    normalize_server_uri,
    parse_server_uri,
)


def test_bare_host_share_assumed_smb():
    assert normalize_server_uri("nas/media") == "smb://nas/media"
    assert normalize_server_uri("172.16.0.47/Anime") == "smb://172.16.0.47/Anime"


def test_windows_unc_path_converted():
    assert normalize_server_uri(r"\\nas\media") == "smb://nas/media"


def test_known_schemes_preserved():
    assert normalize_server_uri("sftp://host/path") == "sftp://host/path"
    assert normalize_server_uri("SFTP://host/path") == "sftp://host/path"
    # An unknown scheme is not silently trusted.
    assert normalize_server_uri("gopher://host/x") == "smb://host/x"


def test_trailing_slashes_trimmed():
    assert normalize_server_uri("smb://nas/media/") == "smb://nas/media"


def test_blank_input_rejected():
    assert normalize_server_uri("   ") == ""
    assert parse_server_uri("") is None
    assert parse_server_uri("smb://") is None


def test_parse_extracts_parts():
    target = parse_server_uri("smb://kweber@nas/Anime/subdir")
    assert target is not None
    assert target.host == "nas"
    assert target.share == "Anime"  # first path segment only
    assert target.user == "kweber"
    assert target.display_name == "Anime on nas"


def test_display_name_without_share():
    target = parse_server_uri("smb://nas")
    assert target is not None
    assert target.display_name == "nas"


def test_error_extraction_skips_gio_prompts():
    output = "User [kweber]: \nDomain [WORKGROUP]: \nPassword: \ngio: Permission denied"
    assert _last_meaningful_line(output) == "gio: Permission denied"


def test_store_roundtrip_and_ordering(tmp_path):
    store = ServerStore(tmp_path / "servers.json")
    store.push("nas/media")
    store.push("smb://other/share")
    # Re-pushing moves an entry to the front instead of duplicating it.
    store.push("nas/media")
    assert store.all() == ["smb://nas/media", "smb://other/share"]

    reopened = ServerStore(tmp_path / "servers.json")
    reopened.load()
    assert reopened.all() == ["smb://nas/media", "smb://other/share"]


def test_store_remove(tmp_path):
    store = ServerStore(tmp_path / "servers.json")
    store.push("smb://nas/media")
    store.remove("nas/media")  # normalised before comparing
    assert store.all() == []


def test_store_caps_history(tmp_path):
    store = ServerStore(tmp_path / "servers.json")
    for index in range(20):
        store.push(f"smb://host{index}/share")
    assert len(store.all()) == 12
    assert store.all()[0] == "smb://host19/share"


def test_store_ignores_corrupt_file(tmp_path):
    path = tmp_path / "servers.json"
    path.write_text("{not json", encoding="utf-8")
    store = ServerStore(path)
    store.load()
    assert store.all() == []
