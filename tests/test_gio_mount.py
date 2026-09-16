"""Tests for the GIO mount layer and how credentials reach it."""

from hyprfind.core.gio_mount import NO_BACKEND_ERROR, Credentials
from hyprfind.core import servers
from hyprfind.core.servers import mount_server, parse_server_uri


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
