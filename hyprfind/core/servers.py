"""Network share mounting through GVFS, plus a list of recent servers.

Shares are mounted through GIO, which puts them under the user's GVFS
directory and lets GVFS keep the password in the system keyring. See
``hyprfind.core.gio_mount`` for why the ``gio`` command line is not used.
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

from hyprfind.core.gio_mount import (
    NO_BACKEND_ERROR,
    Credentials,
    list_children,
    mount_uri,
)
from hyprfind.utils.paths import config_dir

@dataclass(frozen=True)
class Protocol:
    """A mountable scheme and the traits its credential prompts need.

    ``domain`` is a Windows/NTLM concept, so only SMB asks for it. NFS
    authenticates by host rather than by user, so it takes no credentials
    at all.

    ``package`` is the Arch package shipping the backend. Only SMB and NFS are
    split out; sftp, ftp and afp live in base ``gvfs``. ``packaged`` is False
    for schemes no official package provides, so the dialog can say so instead
    of naming a package that does not exist.
    """

    scheme: str
    label: str
    placeholder: str
    backend: str
    package: str = "gvfs"
    credentials: bool = True
    domain: bool = False
    packaged: bool = True
    # SMB exposes a list of shares under the host; sftp and ftp expose one
    # filesystem, so there is nothing to choose from.
    browsable: bool = False


PROTOCOLS: tuple[Protocol, ...] = (
    Protocol(
        "smb",
        "SMB / Windows share",
        "server, or server/share",
        "smb",
        "gvfs-smb",
        domain=True,
        browsable=True,
    ),
    Protocol("sftp", "SFTP (SSH)", "server", "sftp"),
    Protocol("ftp", "FTP", "server", "ftp"),
    Protocol("ftps", "FTP over TLS", "server", "ftp"),
    Protocol("nfs", "NFS", "server/export", "nfs", "gvfs-nfs", credentials=False),
    Protocol("afp", "AFP (Apple)", "server/volume", "afp"),
    # Arch's gvfs 1.60 ships no gvfsd-dav, and no gvfs-dav package exists.
    # Kept so a pasted dav:// URI is not silently rewritten as SMB, and so it
    # works on distributions that do ship the backend.
    Protocol("davs", "WebDAV (HTTPS)", "server/path", "dav", packaged=False),
    Protocol("dav", "WebDAV (HTTP)", "server/path", "dav", packaged=False),
)

# gvfs itself aliases ssh to the sftp backend; the rest are conveniences for
# addresses people paste.
SCHEME_ALIASES = {"ssh": "sftp", "webdav": "dav", "webdavs": "davs", "cifs": "smb"}

SUPPORTED_SCHEMES = tuple(p.scheme for p in PROTOCOLS)
DEFAULT_SCHEME = "smb"

MOUNT_TIMEOUT = 45.0
MAX_RECENT_SERVERS = 12


def protocol_for(scheme: str) -> Protocol:
    """Look up a protocol, falling back to the default for unknown schemes."""
    wanted = SCHEME_ALIASES.get(scheme.lower(), scheme.lower())
    for protocol in PROTOCOLS:
        if protocol.scheme == wanted:
            return protocol
    return PROTOCOLS[0]


def split_server_uri(text: str) -> tuple[str, str]:
    """Split user input into ``(scheme, location)``.

    Accepts a bare ``server/share``, a Windows UNC path, or a full URI, so the
    dialog can keep its protocol menu in step with whatever gets pasted in.
    """
    address = text.strip()
    if not address:
        return DEFAULT_SCHEME, ""
    if address.startswith("\\\\"):
        return "smb", address[2:].replace("\\", "/").strip("/")
    if "://" not in address:
        return DEFAULT_SCHEME, _without_password(address.strip("/"))
    scheme, rest = address.split("://", 1)
    return protocol_for(scheme).scheme, _without_password(rest.strip("/"))


def _split_userinfo(location: str) -> tuple[str, str]:
    """Split ``user:password@host/share`` into ``(userinfo, remainder)``.

    Only the authority is considered, so a password is never mistaken for part
    of a path, and an IPv6 literal's colons are left alone.
    """
    authority, slash, path = location.partition("/")
    if "@" not in authority:
        return "", location
    # rsplit: an SMB user name may itself contain an @.
    userinfo, _, host = authority.rpartition("@")
    return userinfo, f"{host}{slash}{path}"


def _without_password(location: str) -> str:
    """Drop a pasted password, keeping the user name.

    Stored addresses and the recent servers menu must never hold a secret, and
    the password belongs in the dialog's own field instead.
    """
    userinfo, remainder = _split_userinfo(location)
    if not userinfo:
        return location
    user = userinfo.split(":", 1)[0]
    return f"{user}@{remainder}" if user else remainder


def credentials_in_uri(text: str) -> tuple[str, str]:
    """The ``(user, password)`` embedded in pasted input, each possibly empty."""
    address = text.strip()
    if address.startswith("\\\\"):
        return "", ""
    location = address.split("://", 1)[1] if "://" in address else address
    userinfo, _ = _split_userinfo(location.strip("/"))
    if not userinfo:
        return "", ""
    user, _, password = userinfo.partition(":")
    return unquote(user), unquote(password)


def build_server_uri(scheme: str, location: str) -> str:
    """Join a protocol and a host/share into a URI gio understands."""
    place = location.strip().strip("/")
    if not place:
        return ""
    return f"{protocol_for(scheme).scheme}://{place}"


def normalize_server_uri(text: str) -> str:
    """Turn user input into a URI gio understands.

    A bare ``server/share`` is assumed to be SMB, which is what people paste
    from Windows; a Windows UNC path is also accepted.
    """
    scheme, location = split_server_uri(text)
    return build_server_uri(scheme, location)


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


def _mount_definition_dirs() -> list[str]:
    """Directories holding GVFS ``.mount`` files."""
    roots = [d for d in os.environ.get("XDG_DATA_DIRS", "").split(":") if d]
    for fallback in ("/usr/local/share", "/usr/share"):
        if fallback not in roots:
            roots.append(fallback)
    return [os.path.join(root, "gvfs", "mounts") for root in roots]


def supported_schemes() -> frozenset[str]:
    """Schemes gio can actually mount here.

    Reads the same ``.mount`` definitions gio reads rather than guessing where
    the helpers live: Arch installs them as ``/usr/lib/gvfsd-smb`` while other
    distributions use ``/usr/libexec/gvfs/``, and only the definition knows
    which scheme a backend claims.
    """
    found: set[str] = set()
    for directory in _mount_definition_dirs():
        try:
            names = os.listdir(directory)
        except OSError:
            continue
        for name in names:
            if not name.endswith(".mount"):
                continue
            try:
                text = Path(directory, name).read_text(encoding="utf-8")
            except OSError:
                continue

            schemes: list[str] = []
            executable = ""
            for line in text.splitlines():
                key, _, value = line.partition("=")
                if key == "Scheme":
                    schemes.append(value)
                elif key == "SchemeAliases":
                    schemes.extend(value.replace(";", ",").split(","))
                elif key == "Exec":
                    parts = value.split()
                    executable = parts[0] if parts else ""
            # A definition whose helper is gone cannot serve a mount.
            if not executable or not os.path.exists(executable):
                continue
            found.update(s.strip().lower() for s in schemes if s.strip())
    return frozenset(found)


def gvfs_installed() -> bool:
    """True when any GVFS mount definition directory is present."""
    return any(os.path.isdir(d) for d in _mount_definition_dirs())


def missing_backend(scheme: str) -> str | None:
    """Return an explanation if this scheme has no GVFS backend installed.

    gio reports a missing backend as "volume doesn't implement mount", which
    reads like a server problem, so check up front and name the package.
    """
    protocol = protocol_for(scheme)
    # An installed backend settles it, whatever the packaging looks like.
    if protocol.scheme in supported_schemes():
        return None
    if not protocol.packaged:
        return (
            f"{protocol.label} is not available: no GVFS backend for it is "
            f"packaged on Arch. Use SFTP or SMB instead."
        )
    if not gvfs_installed():
        extra = "" if protocol.package == "gvfs" else f" and {protocol.package}"
        return (
            f"GVFS is not installed, so no network shares can be mounted. "
            f"Install gvfs{extra}."
        )
    return (
        f"The {protocol.label} backend is not installed. "
        f"Install {protocol.package}."
    )


def mount_server(
    target: ServerTarget,
    *,
    user: str = "",
    domain: str = "",
    password: str = "",
    anonymous: bool = False,
    remember: bool = True,
) -> tuple[str | None, str | None]:
    """Mount a share. Returns ``(mount_point, error)``.

    With ``remember`` set, GVFS stores the password in the system keyring and
    supplies it itself next time, so the password never has to come back
    through here. Blocking; call it from a worker thread.
    """
    unsupported = missing_backend(target.scheme)
    if unsupported:
        return None, unsupported

    error = mount_uri(
        target.uri,
        Credentials(
            user=user,
            domain=domain,
            password=password,
            anonymous=anonymous,
            remember=remember,
        ),
    )
    if error is None:
        point = gvfs_mount_point(target)
        if point:
            return point, None
        return None, "Mounted, but the share directory could not be found"
    return None, _explain(error, target.scheme)


def _explain(error: str, scheme: str) -> str:
    """Add install advice to the one GIO error that calls for it."""
    if error != NO_BACKEND_ERROR:
        return error
    # Reached when the preflight check did not recognise this system's gvfs
    # layout, so the backend looked present but nothing served the URI.
    protocol = protocol_for(scheme)
    return (
        f"{protocol.label} shares cannot be mounted: no GVFS backend "
        f"answered. Install {protocol.package}, then log out and back in."
    )


_SMB_MOUNT_DIR = re.compile(r"^smb-share:server=(?P<server>[^,]+),share=(?P<share>.+)$")

LIST_TIMEOUT = 30.0


def mounted_share_names(host: str) -> set[str]:
    """Share names already mounted from ``host``, casefolded.

    GVFS names its directories ``smb-share:server=host,share=name`` and
    lowercases both parts, so compare casefolded.
    """
    try:
        entries = os.listdir(_gvfs_root())
    except OSError:
        return set()
    wanted = host.casefold()
    found: set[str] = set()
    for name in entries:
        match = _SMB_MOUNT_DIR.match(name)
        if match and match.group("server").casefold() == wanted:
            found.add(match.group("share").casefold())
    return found


def list_shares(
    target: ServerTarget,
    *,
    user: str = "",
    domain: str = "",
    password: str = "",
    anonymous: bool = False,
    remember: bool = True,
) -> tuple[list[str], str | None]:
    """List the shares a server offers. Returns ``(shares, error)``.

    Blocking; call it from a worker thread. Browsing mounts the server root,
    so a password saved in the keyring is reused and need not be retyped.
    """
    unsupported = missing_backend(target.scheme)
    if unsupported:
        return [], unsupported

    names, error = list_children(
        f"{target.scheme}://{target.host}/",
        Credentials(
            user=user,
            domain=domain,
            password=password,
            anonymous=anonymous,
            remember=remember,
        ),
        timeout=LIST_TIMEOUT,
    )
    if error:
        return [], _explain(error, target.scheme)
    shares = [n.strip().rstrip("/") for n in names]
    visible = [n for n in shares if n and not n.startswith(".")]
    return sorted(visible, key=str.casefold), None


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
            # Addresses carry user names and reveal which servers exist, so
            # keep them out of reach of other accounts on the machine.
            self._path.chmod(0o600)
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
