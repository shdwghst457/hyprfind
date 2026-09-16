"""Mount detection via /proc/mounts."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

NETWORK_FSTYPES = frozenset(
    {
        "cifs",
        "smb3",
        "smbfs",
        "nfs",
        "nfs4",
        "davfs",
        "fuse.gvfsfs",
        "fuse.gvfsd-fuse",
        "fuse.sshfs",
        # systemd automounts under /mnt are nearly always remote shares, and
        # polling a local path costs little compared to missing SMB changes.
        "autofs",
    }
)

VOLUME_SKIP_PREFIXES = (
    "/proc",
    "/sys",
    "/dev",
    "/run/user",
    "/run/credentials",
    "/var/lib",
    "/snap",
    "/boot",
    "/efi",
)

# Pseudo-filesystems that are never a browsable volume.
PSEUDO_FSTYPES = frozenset(
    {
        "tmpfs",
        "devtmpfs",
        "proc",
        "sysfs",
        "cgroup2",
        "bpf",
        "devpts",
        "mqueue",
        "hugetlbfs",
        "securityfs",
        "pstore",
        "efivarfs",
        "debugfs",
        "configfs",
        "tracefs",
        "fusectl",
        "binfmt_misc",
        "ramfs",
        "squashfs",
        "overlay",
    }
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

    def __init__(
        self,
        mounts_path: str = "/proc/mounts",
        *,
        is_dir: Callable[[str], bool] = os.path.isdir,
    ) -> None:
        self._mounts_path = mounts_path
        self._mounts: list[Mount] = []
        self._last_reload: float = 0.0
        self._is_dir = is_dir

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
        """User-facing volumes: one entry per backing device or share.

        Btrfs subvolumes, bind mounts, and AppImage FUSE mounts all appear in
        /proc/mounts as separate lines sharing a device, so we keep only the
        shortest mount point per device to avoid a sidebar full of duplicates.
        """
        self.reload()
        best_by_device: dict[tuple[str, str], Mount] = {}
        standalone: list[Mount] = []

        for mount in self._mounts:
            if not self._is_candidate_volume(mount):
                continue
            if not mount.device.startswith("/dev/"):
                # Pseudo devices (autofs "systemd-1", //server/share) reuse the
                # same name for unrelated mounts, so they must not be merged.
                standalone.append(mount)
                continue
            key = (mount.device, mount.fstype)
            existing = best_by_device.get(key)
            if existing is None or len(mount.mount_point) < len(existing.mount_point):
                best_by_device[key] = mount

        merged = list(best_by_device.values()) + standalone
        return sorted(merged, key=lambda m: m.mount_point)

    def _is_candidate_volume(self, mount: Mount) -> bool:
        mp = mount.mount_point
        fstype = mount.fstype

        if any(mp == prefix or mp.startswith(prefix.rstrip("/") + "/") for prefix in VOLUME_SKIP_PREFIXES):
            return False
        if mp in ("/boot", "/efi"):
            return False
        if fstype in PSEUDO_FSTYPES:
            return False
        # FUSE mounts are usually app plumbing (AppImages, portals); only the
        # network-capable ones are real volumes.
        if fstype.startswith("fuse") and fstype not in NETWORK_FSTYPES:
            return False
        if mp.startswith("/tmp/.mount_"):
            return False
        # Bind mounts of individual files (common with sandboxes and secrets).
        if not self._is_dir(mp):
            return False
        return True

    def is_network_path(self, path: str) -> bool:
        mount = self.mount_for_path(path)
        if mount and mount.is_network:
            return True
        from hyprfind.utils.paths import gvfs_base

        return os.path.abspath(path).startswith(gvfs_base())
