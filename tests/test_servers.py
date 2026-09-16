"""Tests for server URI handling and the recent-servers store."""

from hyprfind.core.servers import (
    PROTOCOLS,
    ServerStore,
    _credential_input,
    _last_meaningful_line,
    build_server_uri,
    missing_backend,
    normalize_server_uri,
    parse_server_uri,
    protocol_for,
    split_server_uri,
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


# ------------------------------------------------- protocol menu / credentials


def test_only_smb_asks_for_a_domain():
    """Domain is a Windows concept, so no other backend should show it."""
    with_domain = [p.scheme for p in PROTOCOLS if p.domain]
    assert with_domain == ["smb"]


def test_nfs_takes_no_credentials():
    assert protocol_for("nfs").credentials is False
    assert protocol_for("smb").credentials is True


def test_scheme_aliases_resolve():
    # People paste ssh:// and cifs://; gio wants sftp:// and smb://.
    assert protocol_for("ssh").scheme == "sftp"
    assert protocol_for("cifs").scheme == "smb"
    assert protocol_for("nonsense").scheme == "smb"


def test_split_separates_scheme_from_location():
    assert split_server_uri("smb://nas/media") == ("smb", "nas/media")
    assert split_server_uri("sftp://host") == ("sftp", "host")
    assert split_server_uri("nas/media") == ("smb", "nas/media")
    assert split_server_uri(r"\\nas\media") == ("smb", "nas/media")
    assert split_server_uri("") == ("smb", "")


def test_split_round_trips_through_build():
    for text in ("smb://nas/media", "sftp://host/dir", "nfs://box/export"):
        scheme, location = split_server_uri(text)
        assert build_server_uri(scheme, location) == text


def test_build_rejects_an_empty_location():
    assert build_server_uri("smb", "") == ""
    assert build_server_uri("smb", "  /  ") == ""


def test_domain_answer_only_sent_to_smb():
    """A stray domain line would shift gio's later answers out of step."""
    smb = _credential_input("kweber", "WORKGROUP", "secret", False, "smb")
    assert smb.split("\n")[:3] == ["kweber", "WORKGROUP", "secret"]

    sftp = _credential_input("kweber", "WORKGROUP", "secret", False, "sftp")
    assert sftp.split("\n")[:2] == ["kweber", "secret"]
    assert "WORKGROUP" not in sftp


def test_guest_and_credential_free_protocols():
    assert _credential_input("u", "d", "p", True, "smb") == "\n\n\n\n"
    # NFS never prompts, so nothing should be piped at it.
    assert _credential_input("u", "d", "p", False, "nfs") == "\n"


def test_missing_backend_names_the_package(monkeypatch):
    monkeypatch.setattr("hyprfind.core.servers.gvfs_installed", lambda: False)
    message = missing_backend("smb")
    assert message is not None
    assert "gvfs-smb" in message
    # The point of the check is to replace gio's unhelpful phrasing.
    assert "implement mount" not in message


def test_missing_backend_for_bundled_scheme_says_gvfs(monkeypatch):
    monkeypatch.setattr("hyprfind.core.servers.gvfs_installed", lambda: False)
    message = missing_backend("sftp")
    assert message is not None and "gvfs" in message


def test_backend_present_reports_no_problem(monkeypatch, tmp_path):
    (tmp_path / "gvfsd-smb").write_text("")
    monkeypatch.setattr("hyprfind.core.servers.gvfs_installed", lambda: True)
    monkeypatch.setattr(
        "hyprfind.core.servers._GVFS_LIBEXEC_DIRS", (str(tmp_path),)
    )
    assert missing_backend("smb") is None
    # sftp backend file is absent, so it should still be reported.
    assert missing_backend("sftp") is not None
