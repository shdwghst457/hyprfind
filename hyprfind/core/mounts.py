"""Mount detection via /proc/mounts."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

NETWORK_FSTYPES = frozenset(
    {
        "cifs",
        "smb3",
        "nfs",
        "nfs4",
        "fuse.gvfsfs",
        "fuse.gvfsd-fuse",
    }
)

VOLUME_SKIP_PREFIXES = (
    "/proc",
    "/sys",
    "/dev",
    "/run/user",
    "/var/lib",
    "/snap",
)


@dataclass(frozen=True)
class Mount:
    device: str
    mount_point: str
    fstype: str

    @property
    def is_network(self) -> bool:
        return self.fstype in NETWORK_FSTYPES


def parse_mounts(mounts_text: str) -> list[Mount]:
    mounts: list[Mount] = []
    for line in mounts_text.splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        device, mount_point, fstype = parts[0], parts[1], parts[2]
        mount_point = mount_point.replace("\\040", " ")
        mounts.append(Mount(device=device, mount_point=mount_point, fstype=fstype))
    return mounts


def load_mounts(mounts_path: str = "/proc/mounts") -> list[Mount]:
    with open(mounts_path, encoding="utf-8", errors="replace") as fh:
        return parse_mounts(fh.read())


class MountService:
    CACHE_TTL_SECONDS = 2.0

    def __init__(self, mounts_path: str = "/proc/mounts") -> None:
        self._mounts_path = mounts_path
        self._mounts: list[Mount] = []
        self._last_reload: float = 0.0

    def reload(self, *, force: bool = False) -> None:
        import time

        now = time.monotonic()
        if not force and self._mounts and (now - self._last_reload) < self.CACHE_TTL_SECONDS:
            return
        self._mounts = load_mounts(self._mounts_path)
        self._last_reload = now

    def all_mounts(self) -> list[Mount]:
        if not self._mounts:
            self.reload()
        return list(self._mounts)

    def mount_for_path(self, path: str) -> Mount | None:
        if not self._mounts:
            self.reload()
        normalized = os.path.abspath(os.path.expanduser(path))
        best: Mount | None = None
        best_len = -1
        for mount in self._mounts:
            mp = mount.mount_point
            if normalized == mp or normalized.startswith(mp.rstrip("/") + "/"):
                if len(mp) > best_len:
                    best = mount
                    best_len = len(mp)
        return best

    def volume_mounts(self) -> list[Mount]:
        self.reload()
        seen: set[str] = set()
        volumes: list[Mount] = []
        for mount in sorted(self._mounts, key=lambda m: m.mount_point):
            mp = mount.mount_point
            if mp in seen:
                continue
            if any(mp.startswith(prefix) for prefix in VOLUME_SKIP_PREFIXES):
                continue
            if mount.fstype in {"tmpfs", "devtmpfs", "proc", "sysfs", "cgroup2", "bpf"}:
                continue
            if mp.startswith("/dev/") and mount.fstype not in NETWORK_FSTYPES:
                continue
            seen.add(mp)
            volumes.append(mount)
        return volumes

    def is_network_path(self, path: str) -> bool:
        mount = self.mount_for_path(path)
        if mount and mount.is_network:
            return True
        from hyprfind.utils.paths import gvfs_base

        return os.path.abspath(path).startswith(gvfs_base())
