"""Mounting network shares through GIO.

Driving GIO directly rather than shelling out to ``gio mount`` is what lets
GVFS keep share passwords: a mount operation can ask gvfsd to save the
credential permanently, which puts it in the Secret Service (KWallet or
gnome-keyring) and hands it back on later mounts without a prompt. The ``gio``
command line tool has no equivalent, so anything mounted through it has to be
re-authenticated every time.
"""

from __future__ import annotations

from dataclasses import dataclass

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402  (must follow require_version)

MOUNT_TIMEOUT = 45.0

# Returned when no backend claims the scheme. Callers turn it into advice about
# which package to install, which is knowledge GIO does not have.
NO_BACKEND_ERROR = "no GVFS backend answered"


@dataclass(frozen=True)
class Credentials:
    """What to answer when a backend asks who we are."""

    user: str = ""
    domain: str = ""
    password: str = ""
    anonymous: bool = False
    remember: bool = True


SECRET_SERVICE = "org.freedesktop.secrets"


def keyring_available() -> bool:
    """Whether a Secret Service is running or can be started on demand.

    Without one, GVFS accepts a request to save a password but has nowhere to
    put it, so the promise to remember would quietly go nowhere. A bare
    Hyprland session often has no keyring: KDE's ksecretd implements the API
    but only registers its own KDE name, so nothing auto-starts it.
    """
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        for method in ("ListNames", "ListActivatableNames"):
            reply = bus.call_sync(
                "org.freedesktop.DBus",
                "/org/freedesktop/DBus",
                "org.freedesktop.DBus",
                method,
                None,
                GLib.VariantType("(as)"),
                Gio.DBusCallFlags.NONE,
                2000,
                None,
            )
            if SECRET_SERVICE in reply.unpack()[0]:
                return True
    except GLib.Error:
        return False
    return False


def mount_uri(
    uri: str, credentials: Credentials, timeout: float = MOUNT_TIMEOUT
) -> str | None:
    """Mount ``uri``, returning an error message or None on success.

    Blocking, so call it from a worker thread. Already-mounted counts as
    success, matching what the caller wants to happen next.
    """
    context = GLib.MainContext.new()
    context.push_thread_default()
    try:
        return _mount(uri, credentials, timeout)
    finally:
        context.pop_thread_default()


def _mount(uri: str, credentials: Credentials, timeout: float) -> str | None:
    loop = GLib.MainLoop.new(GLib.MainContext.get_thread_default(), False)
    # Lists because the callbacks assign to them from inside the loop.
    outcome: list[str | None] = ["The server never answered"]
    # Why we gave up, when we are the ones who did.
    reason: list[str | None] = [None]
    prompts = 0

    def on_ask_password(operation, _message, default_user, default_domain, flags):
        nonlocal prompts
        prompts += 1
        if prompts > 1:
            # gvfsd re-asks when an answer is rejected. Without this the loop
            # would keep replaying the same wrong password forever.
            reason[0] = "Wrong user name or password"
            operation.reply(Gio.MountOperationResult.ABORTED)
            return
        anonymous_ok = bool(flags & Gio.AskPasswordFlags.ANONYMOUS_SUPPORTED)
        if credentials.anonymous and anonymous_ok:
            operation.set_anonymous(True)
        else:
            if flags & Gio.AskPasswordFlags.NEED_USERNAME:
                operation.set_username(credentials.user or default_user)
            if flags & Gio.AskPasswordFlags.NEED_DOMAIN:
                operation.set_domain(credentials.domain or default_domain)
            if flags & Gio.AskPasswordFlags.NEED_PASSWORD:
                operation.set_password(credentials.password)
        if credentials.remember and flags & Gio.AskPasswordFlags.SAVING_SUPPORTED:
            operation.set_password_save(Gio.PasswordSave.PERMANENTLY)
        operation.reply(Gio.MountOperationResult.HANDLED)

    def on_ask_question(operation, _message, _choices):
        # Backends ask things like whether to accept an unknown certificate.
        # The first choice is the conservative one.
        operation.set_choice(0)
        operation.reply(Gio.MountOperationResult.HANDLED)

    operation = Gio.MountOperation()
    operation.connect("ask-password", on_ask_password)
    operation.connect("ask-question", on_ask_question)

    def on_done(location, result):
        try:
            location.mount_enclosing_volume_finish(result)
            outcome[0] = None
        except GLib.Error as error:
            outcome[0] = _describe(error, reason[0])
        loop.quit()

    def on_timeout():
        outcome[0] = "Timed out waiting for the server"
        loop.quit()
        return GLib.SOURCE_REMOVE

    location = Gio.File.new_for_uri(uri)
    location.mount_enclosing_volume(
        Gio.MountMountFlags(0), operation, None, on_done
    )
    timer = GLib.timeout_source_new_seconds(max(1, int(timeout)))
    timer.set_callback(lambda _data=None: on_timeout())
    timer.attach(GLib.MainContext.get_thread_default())
    try:
        loop.run()
    finally:
        timer.destroy()
    return outcome[0]


def list_children(
    uri: str, credentials: Credentials, timeout: float = MOUNT_TIMEOUT
) -> tuple[list[str], str | None]:
    """List the names under ``uri``, mounting it first if needed.

    For ``smb://host/`` those names are the server's shares. Going through GIO
    rather than ``gio list`` means a password already in the keyring is reused,
    so browsing a known server needs no retyping.

    Blocking; call it from a worker thread.
    """
    context = GLib.MainContext.new()
    context.push_thread_default()
    try:
        location = Gio.File.new_for_uri(uri)
        names, error, not_mounted = _enumerate(location)
        if not_mounted:
            failure = _mount(uri, credentials, timeout)
            if failure:
                return [], failure
            names, error, _ = _enumerate(location)
        return names, error
    finally:
        context.pop_thread_default()


def _enumerate(location) -> tuple[list[str], str | None, bool]:
    """Names under ``location`` as ``(names, error, needs_mounting)``."""
    try:
        children = location.enumerate_children(
            "standard::name", Gio.FileQueryInfoFlags.NONE, None
        )
    except GLib.Error as error:
        if error.matches(Gio.io_error_quark(), Gio.IOErrorEnum.NOT_MOUNTED):
            return [], None, True
        return [], _describe(error, None), False
    names: list[str] = []
    try:
        while True:
            info = children.next_file(None)
            if info is None:
                break
            names.append(info.get_name())
    except GLib.Error as error:
        return names, _describe(error, None), False
    finally:
        children.close(None)
    return names, None, False


def _describe(error: GLib.Error, pending: str | None) -> str | None:
    """Turn a GLib error into something worth showing, or None if it is success."""
    if error.matches(Gio.io_error_quark(), Gio.IOErrorEnum.ALREADY_MOUNTED):
        return None
    if error.matches(Gio.io_error_quark(), Gio.IOErrorEnum.FAILED_HANDLED):
        # Someone answered the prompt and gave up. If that was us, say which
        # answer was refused; otherwise GIO has nothing quotable to add.
        return pending or "Authentication was cancelled"
    if error.matches(Gio.io_error_quark(), Gio.IOErrorEnum.NOT_SUPPORTED):
        return NO_BACKEND_ERROR
    if error.matches(Gio.io_error_quark(), Gio.IOErrorEnum.PERMISSION_DENIED):
        return "Permission denied: check the user name and password"
    return error.message or "connection failed"
