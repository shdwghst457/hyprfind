"""Network share mounting through GVFS, plus a list of recent servers.

Shares are mounted with ``gio``, which puts them under the user's GVFS
directory. gio has no flags for credentials — it prompts on stdin — so the
prompts are answered by piping the answers in order.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

from hyprfind.utils.paths import config_dir

SUPPORTED_SCHEMES = ("smb", "sftp", "ftp", "nfs", "dav", "davs", "ssh", "afp")
DEFAULT_SCHEME = "smb"

MOUNT_TIMEOUT = 45.0
MAX_RECENT_SERVERS = 12


def normalize_server_uri(text: str) -> str:
    """Turn user input into a URI gio understands.

    A bare ``server/share`` is assumed to be SMB, which is what people paste
    from Windows; a Windows UNC path is also accepted.
    """
    address = text.strip()
    if not address:
        return ""
    if address.startswith("\\\\"):
        address = "smb://" + address[2:].replace("\\", "/")
    if "://" not in address:
        address = f"{DEFAULT_SCHEME}://{address}"

    scheme, rest = address.split("://", 1)
    scheme = scheme.lower()
    if scheme not in SUPPORTED_SCHEMES:
        scheme = DEFAULT_SCHEME
    return f"{scheme}://{rest.strip('/')}" if rest.strip("/") else ""


@dataclass(frozen=True)
class ServerTarget:
    """A parsed share address."""

    uri: str
    scheme: str
    host: str
    share: str
    user: str = ""

    @property
    def display_name(self) -> str:
        if self.share:
            return f"{self.share} on {self.host}"
        return self.host


def parse_server_uri(uri: str) -> ServerTarget | None:
    normalized = normalize_server_uri(uri)
    if not normalized:
        return None
    parsed = urlparse(normalized)
    if not parsed.hostname:
        return None
    share = unquote(parsed.path).strip("/").split("/", 1)[0]
    return ServerTarget(
        uri=normalized,
        scheme=parsed.scheme,
        host=parsed.hostname,
        share=share,
        user=unquote(parsed.username or ""),
    )


def _gvfs_root() -> str:
    return f"/run/user/{os.getuid()}/gvfs"


def gvfs_mount_point(target: ServerTarget) -> str | None:
    """Locate the GVFS directory for a mounted share.

    GVFS names its directories predictably, but the exact key set varies with
    the backend and whether a user was supplied, so fall back to scanning.
    """
    root = _gvfs_root()
    if target.scheme == "smb" and target.share:
        expected = os.path.join(
            root, f"smb-share:server={target.host.lower()},share={target.share.lower()}"
        )
        if os.path.isdir(expected):
            return expected

    if not os.path.isdir(root):
        return None
    try:
        entries = sorted(os.listdir(root))
    except OSError:
        return None

    host = target.host.casefold()
    share = target.share.casefold()
    for name in entries:
        lowered = name.casefold()
        if host not in lowered:
            continue
        if share and share not in lowered:
            continue
        candidate = os.path.join(root, name)
        if os.path.isdir(candidate):
            return candidate
    return None


def _credential_input(user: str, domain: str, password: str, anonymous: bool) -> str:
    """Build the stdin gio's interactive prompts expect, in prompt order."""
    if anonymous:
        # Blank answers accept gio's defaults and try an anonymous bind.
        return "\n\n\n\n"
    return f"{user}\n{domain}\n{password}\n\n"


_ALREADY_MOUNTED = re.compile(r"already mounted", re.IGNORECASE)


def mount_server(
    target: ServerTarget,
    *,
    user: str = "",
    domain: str = "",
    password: str = "",
    anonymous: bool = False,
) -> tuple[str | None, str | None]:
    """Mount a share. Returns ``(mount_point, error)``.

    Blocking; call it from a worker thread.
    """
    if shutil.which("gio") is None:
        return None, "gio not installed (install glib2 and gvfs)"

    try:
        proc = subprocess.run(
            ["gio", "mount", target.uri],
            input=_credential_input(user, domain, password, anonymous),
            capture_output=True,
            text=True,
            timeout=MOUNT_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return None, "Timed out waiting for the server"
    except OSError as exc:
        return None, str(exc)

    output = f"{proc.stdout}\n{proc.stderr}".strip()
    if proc.returncode == 0 or _ALREADY_MOUNTED.search(output):
        point = gvfs_mount_point(target)
        if point:
            return point, None
        return None, "Mounted, but the share directory could not be found"

    detail = _last_meaningful_line(output) or "connection failed"
    return None, detail


def unmount_server(mount_point: str) -> str | None:
    """Unmount a GVFS share. Returns an error message or None."""
    if shutil.which("gio") is None:
        return "gio not installed (install glib2 and gvfs)"
    try:
        proc = subprocess.run(
            ["gio", "mount", "-u", mount_point],
            capture_output=True,
            text=True,
            timeout=MOUNT_TIMEOUT,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return str(exc)
    if proc.returncode == 0:
        return None
    return _last_meaningful_line(f"{proc.stdout}\n{proc.stderr}") or "unmount failed"


def _last_meaningful_line(text: str) -> str:
    """gio echoes its prompts before the real error; keep the last real line."""
    noise = ("user [", "domain [", "password:", "password [")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in reversed(lines):
        if not line.casefold().startswith(noise):
            return line
    return ""


class ServerStore:
    """Remembers recently used server addresses."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or config_dir() / "servers.json"
        self._uris: list[str] = []

    def load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        if isinstance(data, list):
            self._uris = [item for item in data if isinstance(item, str) and item]

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._path.write_text(
                json.dumps(self._uris, indent=2) + "\n", encoding="utf-8"
            )
        except OSError:
            pass

    def all(self) -> list[str]:
        return list(self._uris)

    def push(self, uri: str) -> None:
        normalized = normalize_server_uri(uri)
        if not normalized:
            return
        # Most recent first, without duplicates.
        self._uris = [normalized] + [u for u in self._uris if u != normalized]
        del self._uris[MAX_RECENT_SERVERS:]
        self.save()

    def remove(self, uri: str) -> None:
        normalized = normalize_server_uri(uri)
        before = len(self._uris)
        self._uris = [u for u in self._uris if u != normalized]
        if len(self._uris) != before:
            self.save()
