"""Tests for server URI handling and the recent-servers store."""

from hyprfind.core.servers import (
    PROTOCOLS,
    ServerStore,
    _credential_input,
    _last_meaningful_line,
    build_server_uri,
    missing_backend,
    supported_schemes,
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


def test_missing_backend_names_the_package(tmp_path, monkeypatch):
    # A gvfs install that lacks the SMB backend.
    fake_gvfs(tmp_path, monkeypatch, {"sftp": ("sftp", "", True)})
    message = missing_backend("smb")
    assert message is not None
    assert "gvfs-smb" in message
    # The point of the check is to replace gio's unhelpful phrasing.
    assert "implement mount" not in message


def test_missing_backend_for_bundled_scheme_says_gvfs(tmp_path, monkeypatch):
    fake_gvfs(tmp_path, monkeypatch, {"smb": ("smb", "", True)})
    message = missing_backend("sftp")
    assert message is not None and "gvfs" in message


def test_only_smb_and_nfs_are_split_into_own_packages():
    """sftp/ftp/afp live in base gvfs; there is no gvfs-sftp or gvfs-afp."""
    split = {p.package for p in PROTOCOLS if p.packaged and p.package != "gvfs"}
    assert split == {"gvfs-smb", "gvfs-nfs"}


def test_webdav_is_marked_unpackaged():
    # Arch ships no gvfsd-dav and no gvfs-dav package.
    assert protocol_for("dav").packaged is False
    assert protocol_for("davs").packaged is False
    assert protocol_for("afp").packaged is True


def fake_gvfs(tmp_path, monkeypatch, definitions):
    """Build a GVFS mount-definition tree and point the module at it.

    ``definitions`` maps a .mount basename to (scheme, aliases, helper_exists).
    """
    mounts = tmp_path / "share" / "gvfs" / "mounts"
    mounts.mkdir(parents=True)
    for name, (scheme, aliases, helper_exists) in definitions.items():
        helper = tmp_path / f"gvfsd-{name}"
        if helper_exists:
            helper.write_text("")
        body = ["[Mount]", f"Type={name}", f"Exec={helper}"]
        if scheme:
            body.append(f"Scheme={scheme}")
        if aliases:
            body.append(f"SchemeAliases={aliases}")
        (mounts / f"{name}.mount").write_text("\n".join(body) + "\n")
    monkeypatch.setattr(
        "hyprfind.core.servers._mount_definition_dirs", lambda: [str(mounts)]
    )
    return mounts


def test_backend_found_where_arch_actually_puts_it(tmp_path, monkeypatch):
    """Arch installs helpers as /usr/lib/gvfsd-smb, not /usr/lib/gvfs/gvfsd-smb.

    Looking in the wrong place reported an installed backend as missing and
    refused to mount, so the scheme comes from the .mount definition instead.
    """
    fake_gvfs(tmp_path, monkeypatch, {"smb": ("smb", "", True)})
    assert supported_schemes() == {"smb"}
    assert missing_backend("smb") is None


def test_definition_without_its_helper_is_not_supported(tmp_path, monkeypatch):
    fake_gvfs(tmp_path, monkeypatch, {"smb": ("smb", "", False)})
    assert supported_schemes() == frozenset()
    assert missing_backend("smb") is not None


def test_scheme_aliases_from_definitions_count(tmp_path, monkeypatch):
    # gvfs declares SchemeAliases=ssh on sftp.mount.
    fake_gvfs(tmp_path, monkeypatch, {"sftp": ("sftp", "ssh", True)})
    assert supported_schemes() == {"sftp", "ssh"}


def test_unpackaged_scheme_does_not_invent_a_package(tmp_path, monkeypatch):
    fake_gvfs(tmp_path, monkeypatch, {"smb": ("smb", "", True)})
    message = missing_backend("dav")
    assert message is not None
    assert "install gvfs-dav" not in message.casefold()
    assert "not available" in message


def test_unpackaged_scheme_works_when_the_distro_ships_it(tmp_path, monkeypatch):
    """Debian and Fedora do ship a dav backend, so a present one must win."""
    fake_gvfs(tmp_path, monkeypatch, {"dav": ("dav", "davs", True)})
    assert missing_backend("dav") is None
    assert missing_backend("davs") is None


def test_dav_uri_is_not_silently_turned_into_smb():
    # Coercing an unmountable scheme to SMB would connect somewhere unexpected.
    assert protocol_for("dav").scheme == "dav"
    assert split_server_uri("dav://host/path") == ("dav", "host/path")


def test_ftps_is_offered_and_uses_the_ftp_backend():
    assert protocol_for("ftps").scheme == "ftps"
    assert protocol_for("ftps").backend == "ftp"


def test_backend_present_reports_no_problem(tmp_path, monkeypatch):
    fake_gvfs(tmp_path, monkeypatch, {"smb": ("smb", "", True)})
    assert missing_backend("smb") is None
    # No sftp definition, so it should still be reported.
    assert missing_backend("sftp") is not None


def test_no_definitions_at_all_reads_as_gvfs_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "hyprfind.core.servers._mount_definition_dirs",
        lambda: [str(tmp_path / "nope")],
    )
    message = missing_backend("smb")
    assert message is not None and "GVFS is not installed" in message


def test_both_gio_no_backend_wordings_are_recognised():
    """gio says "doesn't implement mount" or "Location is not mountable"."""
    from hyprfind.core.servers import _NO_BACKEND

    assert _NO_BACKEND.search("gio: smb://h: volume doesn\u2019t implement mount")
    assert _NO_BACKEND.search("gio: dav://h/: Location is not mountable")
    # A real connection failure must not be mistaken for a missing backend.
    assert not _NO_BACKEND.search("Failed to mount Windows share: Permission denied")
    assert not _NO_BACKEND.search("Could not resolve hostname")
