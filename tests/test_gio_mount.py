"""Tests for the GIO mount layer and how credentials reach it."""

from gi.repository import GLib

from hyprfind.core import gio_mount, servers
from hyprfind.core.gio_mount import (
    NO_BACKEND_ERROR,
    Credentials,
    _search_login,
    mount_uri,
    saved_login,
)
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


class _Reply:
    def __init__(self, value) -> None:
        self._value = value

    def unpack(self):
        return self._value


class _FakeBus:
    """Answers the two Secret Service calls a login lookup makes."""

    def __init__(self, unlocked=(), locked=(), attributes=None, fail=False) -> None:
        self._found = (list(unlocked), list(locked))
        self._attributes = attributes or {}
        self._fail = fail
        self.methods: list[str] = []

    def call_sync(self, _name, path, _interface, method, *_rest):
        self.methods.append(method)
        if self._fail:
            raise GLib.Error("no such service")
        if method == "SearchItems":
            return _Reply(self._found)
        return _Reply((self._attributes.get(path, {}),))


NAS_ITEM = {
    "protocol": "smb",
    "server": "nas",
    "user": "alice",
    "domain": "WORKGROUP",
    "xdg:schema": "org.gnome.keyring.NetworkPassword",
}


def test_a_saved_password_reports_who_it_belongs_to():
    bus = _FakeBus(unlocked=["/item/1"], attributes={"/item/1": NAS_ITEM})
    assert _search_login(bus, "smb", "nas").user == "alice"


def test_the_default_workgroup_is_not_offered_as_a_domain():
    """gvfsd writes WORKGROUP in regardless, so echoing it back is just noise."""
    bus = _FakeBus(unlocked=["/item/1"], attributes={"/item/1": NAS_ITEM})
    assert _search_login(bus, "smb", "nas").domain == ""


def test_a_real_domain_is_kept():
    item = NAS_ITEM | {"domain": "OFFICE"}
    bus = _FakeBus(unlocked=["/item/1"], attributes={"/item/1": item})
    assert _search_login(bus, "smb", "nas").domain == "OFFICE"


def test_a_locked_item_still_counts_as_saved():
    """The secret cannot be read yet, but it is there and worth mentioning."""
    bus = _FakeBus(locked=["/item/9"], attributes={"/item/9": NAS_ITEM})
    assert _search_login(bus, "smb", "nas").user == "alice"


def test_a_server_with_nothing_saved_reports_nothing():
    assert _search_login(_FakeBus(), "smb", "nas") is None


def test_a_broken_secret_service_is_silent():
    """Reassurance is optional; it must never get in the way of connecting."""
    assert _search_login(_FakeBus(fail=True), "smb", "nas") is None


def test_an_incomplete_address_is_not_looked_up(monkeypatch):
    def refuse():
        raise AssertionError("should not touch D-Bus without a host")

    monkeypatch.setattr(gio_mount.Gio, "bus_get_sync", lambda *_a: refuse())
    assert saved_login("smb", "") is None
    assert saved_login("", "nas") is None
