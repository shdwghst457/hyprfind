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


PROTOCOLS: tuple[Protocol, ...] = (
    Protocol(
        "smb", "SMB / Windows share", "server/share", "smb", "gvfs-smb", domain=True
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
        return DEFAULT_SCHEME, address.strip("/")
    scheme, rest = address.split("://", 1)
    return protocol_for(scheme).scheme, rest.strip("/")


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


def _credential_input(
    user: str, domain: str, password: str, anonymous: bool, scheme: str = DEFAULT_SCHEME
) -> str:
    """Build the stdin gio's interactive prompts expect, in prompt order.

    The prompt sequence follows the backend: only SMB asks for a domain, so
    sending one to the others would shift every later answer by a line.
    """
    protocol = protocol_for(scheme)
    if not protocol.credentials:
        return "\n"
    if anonymous:
        # Blank answers accept gio's defaults and try an anonymous bind.
        return "\n\n\n\n"
    answers = [user, domain, password] if protocol.domain else [user, password]
    return "\n".join(answers) + "\n\n"


_ALREADY_MOUNTED = re.compile(r"already mounted", re.IGNORECASE)

# gio's two wordings for "no GVFS backend handles this scheme". The apostrophe
# is a Unicode right single quote in gio's output, so match it loosely.
_NO_BACKEND = re.compile(
    r"doesn.t implement mount|is not mountable|not supported", re.IGNORECASE
)

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
) -> tuple[str | None, str | None]:
    """Mount a share. Returns ``(mount_point, error)``.

    Blocking; call it from a worker thread.
    """
    if shutil.which("gio") is None:
        return None, "gio not installed (install glib2 and gvfs)"

    unsupported = missing_backend(target.scheme)
    if unsupported:
        return None, unsupported

    try:
        proc = subprocess.run(
            ["gio", "mount", target.uri],
            input=_credential_input(
                user, domain, password, anonymous, target.scheme
            ),
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
    if _NO_BACKEND.search(detail):
        # Reached when the backend exists but cannot serve this URI, and on
        # distros whose gvfs layout the preflight check does not recognise.
        protocol = protocol_for(target.scheme)
        return None, (
            f"{protocol.label} shares cannot be mounted: no GVFS backend "
            f"answered. Install {protocol.package}, then log out and back in."
        )
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
