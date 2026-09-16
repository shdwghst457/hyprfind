"""Tests for the GIO mount layer and how credentials reach it."""

from hyprfind.core import gio_mount, servers
from hyprfind.core.gio_mount import NO_BACKEND_ERROR, Credentials, mount_uri
from hyprfind.core.servers import mount_server, parse_server_uri


def fake_gio(monkeypatch, keyring: bool):
    """Capture the credentials that reach the GIO call, with no D-Bus or network."""
    seen: dict = {}

    def fake_inner(uri, credentials, timeout):
        seen["credentials"] = credentials
        return None

    monkeypatch.setattr(gio_mount, "keyring_available", lambda: keyring)
    monkeypatch.setattr(gio_mount, "_mount", fake_inner)
    return seen


def test_saving_is_skipped_when_the_keyring_cannot_take_it(monkeypatch):
    """Asking GVFS to save into a locked keyring hangs the mount, so never ask."""
    seen = fake_gio(monkeypatch, keyring=False)
    mount_uri("smb://nas/media", Credentials(password="PLACEHOLDER", remember=True))
    assert seen["credentials"].remember is False
    # The rest of the credentials must survive the override.
    assert seen["credentials"].password == "PLACEHOLDER"


def test_saving_is_requested_when_the_keyring_is_usable(monkeypatch):
    seen = fake_gio(monkeypatch, keyring=True)
    mount_uri("smb://nas/media", Credentials(remember=True))
    assert seen["credentials"].remember is True


def test_a_caller_that_declined_is_not_overridden(monkeypatch):
    seen = fake_gio(monkeypatch, keyring=True)
    mount_uri("smb://nas/media", Credentials(remember=False))
    assert seen["credentials"].remember is False


def fake_mount(monkeypatch, error=None, mount_point="/run/user/1000/gvfs/share"):
    """Capture what mount_server hands to the GIO layer."""
    calls: dict = {}

    def fake_mount_uri(uri, credentials, timeout=None):
        calls["uri"] = uri
        calls["credentials"] = credentials
        return error

    monkeypatch.setattr(servers, "mount_uri", fake_mount_uri)
    monkeypatch.setattr(servers, "missing_backend", lambda _: None)
    monkeypatch.setattr(servers, "gvfs_mount_point", lambda _: mount_point)
    return calls


def test_remembering_is_the_default():
    """The dialog offers it checked, and the core must agree."""
    assert Credentials().remember is True


def test_credentials_reach_the_mount_unchanged(monkeypatch):
    calls = fake_mount(monkeypatch)
    point, error = mount_server(
        parse_server_uri("smb://nas/media"),
        user="alice",
        domain="WORKGROUP",
        password="PLACEHOLDER",
    )
    assert (point, error) == ("/run/user/1000/gvfs/share", None)
    sent = calls["credentials"]
    assert (sent.user, sent.domain, sent.password) == (
        "alice",
        "WORKGROUP",
        "PLACEHOLDER",
    )
    assert sent.remember is True
    assert calls["uri"] == "smb://nas/media"


def test_declining_to_remember_is_passed_on(monkeypatch):
    calls = fake_mount(monkeypatch)
    mount_server(parse_server_uri("smb://nas/media"), remember=False)
    assert calls["credentials"].remember is False


def test_a_guest_connection_is_marked_anonymous(monkeypatch):
    calls = fake_mount(monkeypatch)
    mount_server(parse_server_uri("smb://nas/media"), anonymous=True)
    assert calls["credentials"].anonymous is True


def test_a_missing_backend_is_reported_before_dialling_out(monkeypatch):
    calls = fake_mount(monkeypatch)
    monkeypatch.setattr(servers, "missing_backend", lambda _: "Install gvfs-smb.")
    point, error = mount_server(parse_server_uri("smb://nas/media"))
    assert (point, error) == (None, "Install gvfs-smb.")
    assert "uri" not in calls, "should not attempt a mount it knows will fail"


def test_no_backend_at_mount_time_gains_install_advice(monkeypatch):
    """The preflight check can miss an unusual gvfs layout."""
    fake_mount(monkeypatch, error=NO_BACKEND_ERROR)
    _, error = mount_server(parse_server_uri("smb://nas/media"))
    assert "gvfs-smb" in error


def test_a_mount_that_leaves_no_directory_is_an_error(monkeypatch):
    fake_mount(monkeypatch, mount_point=None)
    point, error = mount_server(parse_server_uri("smb://nas/media"))
    assert point is None
    assert "could not be found" in error


def test_connection_errors_are_surfaced_verbatim(monkeypatch):
    fake_mount(monkeypatch, error="Connection timed out")
    point, error = mount_server(parse_server_uri("smb://nas/media"))
    assert (point, error) == (None, "Connection timed out")
