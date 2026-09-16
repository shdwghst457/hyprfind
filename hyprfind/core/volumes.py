"""Block device and volume discovery for the sidebar.

/proc/mounts alone cannot answer "what drives are attached?" — a USB disk that
no daemon auto-mounted has no mount point at all, which is the common case on a
bare Hyprland session. So we enumerate block devices with ``lsblk`` and merge
that with the mount table, then mount on demand through ``udisksctl`` (no root
needed thanks to polkit).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass

from hyprfind.core.mounts import Mount, MountService
from hyprfind.utils.formatting import format_bytes

LSBLK_COLUMNS = (
    "NAME,PATH,LABEL,PARTLABEL,SIZE,FSTYPE,MOUNTPOINT,MOUNTPOINTS,"
    "RM,HOTPLUG,TYPE,TRAN,VENDOR,MODEL,RO,PARTTYPE,PARTTYPENAME"
)

# Device types that are never user-facing storage.
_SKIP_DEVICE_TYPES = frozenset({"loop", "zram", "ram", "md", "dm"})
# Filesystems that exist on disk but should not appear as a browsable volume.
_SKIP_FSTYPES = frozenset({"swap", "crypto_LUKS", "LVM2_member", "linux_raid_member"})

# GPT partition type GUIDs for firmware and vendor housekeeping. These carry
# real filesystems, so only the partition type distinguishes them from data.
_SKIP_PARTITION_TYPES = frozenset(
    {
        "c12a7328-f81f-11d2-ba4b-00a0c93ec93b",  # EFI System
        "de94bba4-06d1-4d40-a16a-bfd50179d6ac",  # Windows Recovery
        "e3c9e316-0b5c-4db8-817d-f92df00215ae",  # Microsoft Reserved
        "21686148-6449-6e6f-744e-656564454649",  # BIOS boot
        "0657fd6d-a4ab-43c4-84e5-0933c84b4f4f",  # Linux swap
        "bc13c2ff-59e6-4262-a352-b275fd6f7172",  # Extended boot (XBOOTLDR)
        "d3bfe2de-3daf-11df-ba40-e3a556d89593",  # Intel Fast Flash
    }
)

# MBR type codes for the same categories.
_SKIP_MBR_TYPES = frozenset({"0xef", "0x82", "0x27"})

SYSTEM = "system"
INTERNAL = "internal"
REMOVABLE = "removable"
OPTICAL = "optical"
NETWORK = "network"

_COMMAND_TIMEOUT = 15.0


@dataclass(frozen=True)
class Volume:
    """A drive or share the user can open, mount, or eject."""

    name: str
    device: str
    mount_point: str | None
    fstype: str
    kind: str
    size_bytes: int = 0
    read_only: bool = False

    @property
    def is_mounted(self) -> bool:
        return bool(self.mount_point)

    @property
    def is_network(self) -> bool:
        return self.kind == NETWORK

    @property
    def is_ejectable(self) -> bool:
        """True when the user should be offered an eject control."""
        if self.kind == SYSTEM:
            return False
        if not self.is_mounted:
            return False
        return self.kind in (REMOVABLE, OPTICAL, NETWORK)

    @property
    def is_block_device(self) -> bool:
        return self.device.startswith("/dev/")


def _run(argv: list[str]) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=_COMMAND_TIMEOUT,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return 1, "", str(exc)
    return proc.returncode, proc.stdout, proc.stderr


def _lsblk_json() -> list[dict]:
    if shutil.which("lsblk") is None:
        return []
    code, out, _err = _run(["lsblk", "-J", "-b", "-o", LSBLK_COLUMNS])
    if code != 0 or not out.strip():
        return []
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return []
    devices = data.get("blockdevices")
    return devices if isinstance(devices, list) else []


def _flatten(devices: list[dict], parent: dict | None = None) -> list[tuple[dict, dict | None]]:
    flat: list[tuple[dict, dict | None]] = []
    for device in devices:
        if not isinstance(device, dict):
            continue
        flat.append((device, parent))
        children = device.get("children")
        if isinstance(children, list):
            flat.extend(_flatten(children, device))
    return flat


def _first_mountpoint(device: dict) -> str | None:
    """Pick the volume's primary mount point.

    btrfs subvolumes and bind mounts make one device report many paths, and
    lsblk's scalar ``mountpoint`` is an arbitrary one of them, so prefer the
    shortest entry from the full list (``/`` beats ``/home/u/proj/.git``).
    """
    candidates: list[str] = []
    points = device.get("mountpoints")
    if isinstance(points, list):
        candidates = [p for p in points if isinstance(p, str) and p]
    single = device.get("mountpoint")
    if isinstance(single, str) and single:
        candidates.append(single)

    usable = [p for p in candidates if not p.startswith("[")]
    if not usable:
        return None
    return min(usable, key=len)


def _as_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _is_housekeeping_partition(device: dict) -> bool:
    """True for firmware/vendor partitions the user should never browse."""
    part_type = str(device.get("parttype") or "").lower()
    if part_type in _SKIP_PARTITION_TYPES or part_type in _SKIP_MBR_TYPES:
        return True
    type_name = str(device.get("parttypename") or "").casefold()
    return type_name in ("efi system", "microsoft reserved", "bios boot")


def _device_label(device: dict, parent: dict | None) -> str:
    for key in ("label", "partlabel"):
        value = device.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    # An unlabelled partition must not borrow the whole disk's model name, or
    # sibling partitions all end up with the same title.
    if (device.get("type") or "") == "part":
        size = _as_int(device.get("size"))
        if size > 0:
            return f"{format_bytes(size)} Volume"
    else:
        for source in (device, parent):
            if not source:
                continue
            vendor = (source.get("vendor") or "").strip()
            model = (source.get("model") or "").strip()
            combined = " ".join(part for part in (vendor, model) if part)
            if combined:
                return combined

    path = device.get("path") or device.get("name") or "Disk"
    return os.path.basename(str(path))


def _system_volume_name() -> str:
    """Finder calls the boot disk "Macintosh HD"; use the machine name here."""
    try:
        host = os.uname().nodename.strip()
    except OSError:
        host = ""
    return host or "System"


def _volume_name(device: dict, parent: dict | None, kind: str) -> str:
    label = device.get("label")
    if isinstance(label, str) and label.strip():
        return label.strip()
    if kind == SYSTEM:
        return _system_volume_name()
    return _device_label(device, parent)


def _is_removable(device: dict, parent: dict | None) -> bool:
    for source in (device, parent):
        if not source:
            continue
        if source.get("rm") or source.get("hotplug"):
            return True
        if (source.get("tran") or "").lower() in ("usb", "ieee1394", "mmc"):
            return True
    return False


def _classify_block(device: dict, parent: dict | None, mount_point: str | None) -> str:
    if (device.get("type") or "") == "rom":
        return OPTICAL
    if mount_point == "/":
        return SYSTEM
    if _is_removable(device, parent):
        return REMOVABLE
    return INTERNAL


class VolumeService:
    """Discovers drives and shares; mounts and ejects them on request."""

    def __init__(self, mount_service: MountService | None = None) -> None:
        self._mount_service = mount_service or MountService()

    # ---------------------------------------------------------------- discovery

    def volumes(self) -> list[Volume]:
        """Attached drives plus network shares, ordered for the sidebar."""
        block = self._block_volumes()
        claimed = {
            os.path.normpath(vol.mount_point)
            for vol in block
            if vol.mount_point
        }
        network = [
            vol
            for vol in self._network_volumes()
            if os.path.normpath(vol.mount_point or "") not in claimed
        ]

        order = {SYSTEM: 0, INTERNAL: 1, REMOVABLE: 2, OPTICAL: 3, NETWORK: 4}
        combined = block + network
        combined.sort(key=lambda v: (order.get(v.kind, 9), v.name.casefold()))
        return combined

    def _block_volumes(self) -> list[Volume]:
        volumes: list[Volume] = []
        seen_devices: set[str] = set()

        for device, parent in _flatten(_lsblk_json()):
            dev_type = (device.get("type") or "").lower()
            if dev_type in _SKIP_DEVICE_TYPES:
                continue

            path = device.get("path")
            if not isinstance(path, str) or not path:
                continue
            if path in seen_devices:
                continue
            name = str(device.get("name") or "")
            if name.startswith(("zram", "loop", "ram")):
                continue

            fstype = device.get("fstype") or ""
            mount_point = _first_mountpoint(device)

            if dev_type == "disk" and isinstance(device.get("children"), list):
                # Partitioned disk: the partitions carry the filesystems.
                if device["children"]:
                    continue
            if fstype in _SKIP_FSTYPES:
                continue
            if _is_housekeeping_partition(device):
                continue
            if dev_type != "rom" and not fstype and not mount_point:
                # Unformatted or unreadable; nothing to browse or mount.
                continue
            if mount_point and self._is_hidden_mount(mount_point):
                continue

            seen_devices.add(path)
            kind = _classify_block(device, parent, mount_point)
            volumes.append(
                Volume(
                    name=_volume_name(device, parent, kind),
                    device=path,
                    mount_point=mount_point,
                    fstype=fstype,
                    kind=kind,
                    size_bytes=_as_int(device.get("size")),
                    read_only=bool(device.get("ro")),
                )
            )

        if not volumes:
            volumes = self._fallback_block_volumes()
        return volumes

    def _fallback_block_volumes(self) -> list[Volume]:
        """Used when lsblk is unavailable: derive drives from /proc/mounts."""
        volumes: list[Volume] = []
        seen: set[str] = set()
        for mount in self._mount_service.volume_mounts():
            if mount.is_network or mount.device in seen:
                continue
            if not mount.device.startswith("/dev/"):
                continue
            seen.add(mount.device)
            volumes.append(
                Volume(
                    name=os.path.basename(mount.mount_point.rstrip("/")) or mount.mount_point,
                    device=mount.device,
                    mount_point=mount.mount_point,
                    fstype=mount.fstype,
                    kind=SYSTEM if mount.mount_point == "/" else INTERNAL,
                )
            )
        return volumes

    def _network_volumes(self) -> list[Volume]:
        # A triggered autofs share appears twice: the automount placeholder and
        # the real cifs/nfs mount on the same path. Keep the concrete one.
        by_path: dict[str, Mount] = {}
        for mount in self._mount_service.volume_mounts():
            if not mount.is_network:
                continue
            key = os.path.normpath(mount.mount_point)
            existing = by_path.get(key)
            if existing is None or (
                existing.fstype == "autofs" and mount.fstype != "autofs"
            ):
                by_path[key] = mount

        return [
            Volume(
                name=self._network_label(mount),
                device=mount.device,
                mount_point=mount.mount_point,
                fstype=mount.fstype,
                kind=NETWORK,
            )
            for mount in by_path.values()
        ]

    @staticmethod
    def _network_label(mount: Mount) -> str:
        base = os.path.basename(mount.mount_point.rstrip("/"))
        return base or mount.mount_point

    @staticmethod
    def _is_hidden_mount(mount_point: str) -> bool:
        normalized = os.path.normpath(mount_point)
        if normalized in ("/boot", "/boot/efi", "/efi"):
            return True
        return normalized.startswith("/tmp/.mount_")

    # ------------------------------------------------------------------ actions

    def mount(self, volume: Volume) -> tuple[str | None, str | None]:
        """Mount a block volume. Returns (mount_point, error)."""
        if volume.is_mounted:
            return volume.mount_point, None
        if not volume.is_block_device:
            return None, f"Cannot mount {volume.name}"

        if shutil.which("udisksctl") is None:
            return None, "udisksctl not installed (install udisks2)"

        code, out, err = _run(["udisksctl", "mount", "-b", volume.device])
        if code == 0:
            path = self._parse_mount_output(out)
            if path:
                self._mount_service.reload(force=True)
                return path, None

        message = (err or out).strip().splitlines()
        detail = message[-1] if message else "unknown error"
        if "AlreadyMounted" in detail or "already mounted" in detail.lower():
            self._mount_service.reload(force=True)
            existing = self._mount_service.mount_for_path(volume.device)
            return (existing.mount_point if existing else None), None
        return None, f"Mount failed: {detail}"

    @staticmethod
    def _parse_mount_output(output: str) -> str | None:
        # udisksctl prints: "Mounted /dev/sdb1 at /run/media/user/LABEL"
        for line in output.splitlines():
            if " at " in line:
                candidate = line.rsplit(" at ", 1)[1].strip().rstrip(".")
                if candidate:
                    return candidate
        return None

    def eject(self, volume: Volume) -> str | None:
        """Unmount (and power off removable hardware). Returns error or None."""
        if volume.is_network:
            return self._eject_network(volume)
        return self._eject_block(volume)

    def _eject_network(self, volume: Volume) -> str | None:
        if not volume.mount_point:
            return None
        if shutil.which("gio") is not None:
            code, _out, err = _run(["gio", "mount", "-u", volume.mount_point])
            if code == 0:
                self._mount_service.reload(force=True)
                return None
            failure = err.strip() or "unmount failed"
        else:
            failure = "gio not installed"
        self._mount_service.reload(force=True)
        return f"Eject failed: {failure}"

    def _eject_block(self, volume: Volume) -> str | None:
        if not volume.is_block_device:
            return f"Cannot eject {volume.name}"
        if shutil.which("udisksctl") is None:
            return "udisksctl not installed (install udisks2)"

        code, out, err = _run(["udisksctl", "unmount", "-b", volume.device])
        if code != 0:
            detail = (err or out).strip().splitlines()
            message = detail[-1] if detail else "unmount failed"
            if "NotMounted" not in message:
                self._mount_service.reload(force=True)
                return f"Eject failed: {message}"

        if volume.kind == REMOVABLE:
            # Best effort: spin down / cut power so the disk is safe to unplug.
            _run(["udisksctl", "power-off", "-b", volume.device])

        self._mount_service.reload(force=True)
        return None
