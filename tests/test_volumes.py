"""Tests for VolumeService block-device discovery."""

import hyprfind.core.volumes as volumes_module
from hyprfind.core.mounts import MountService
from hyprfind.core.volumes import (
    INTERNAL,
    NETWORK,
    REMOVABLE,
    SYSTEM,
    VolumeService,
    _first_mountpoint,
    _parse_gvfs_dir,
)

MOUNTS = """\
/dev/sda2 / btrfs rw,subvol=/@ 0 0
/dev/sda2 /home btrfs rw,subvol=/@home 0 0
systemd-1 /mnt/transport autofs rw,relatime 0 0
//172.16.0.47/transport /mnt/transport cifs rw,relatime 0 0
systemd-1 /mnt/Anime autofs rw,relatime 0 0
"""

# Shape mirrors `lsblk -J -b`: a partitioned system disk, an unmounted USB
# disk, a mounted USB stick, and a zram swap device that must be ignored.
LSBLK = [
    {
        "name": "sda", "path": "/dev/sda", "type": "disk", "rm": False,
        "hotplug": False, "tran": "sata", "vendor": "ATA ", "model": "INTEL SSD",
        "children": [
            {
                "name": "sda2", "path": "/dev/sda2", "type": "part",
                "fstype": "btrfs", "size": 240000000000,
                "mountpoint": "/home/u/proj/.git/hooks",
                "mountpoints": ["/", "/home", "/home/u/proj/.git/hooks"],
            },
            {
                "name": "sda1", "path": "/dev/sda1", "type": "part",
                "fstype": "vfat", "size": 4000000000,
                "mountpoint": "/boot", "mountpoints": ["/boot"],
            },
        ],
    },
    # A USB installer stick: an EFI partition beside the data partition. Only
    # the data half should be offered.
    {
        "name": "sdb", "path": "/dev/sdb", "type": "disk", "rm": True,
        "hotplug": True, "tran": "usb", "vendor": "SanDisk", "model": "Cruzer",
        "children": [
            {
                "name": "sdb1", "path": "/dev/sdb1", "type": "part",
                "label": "EFI", "fstype": "vfat", "size": 209715200,
                "parttype": "c12a7328-f81f-11d2-ba4b-00a0c93ec93b",
                "parttypename": "EFI System",
                "mountpoint": None, "mountpoints": [None],
                "rm": True, "hotplug": True,
            },
            {
                "name": "sdb2", "path": "/dev/sdb2", "type": "part",
                "label": "Backup Drive", "fstype": "vfat",
                "size": 7658799104, "mountpoint": None, "mountpoints": [None],
                "parttype": "ebd0a0a2-b9e5-4433-87c0-68b6b72699c7",
                "rm": True, "hotplug": True,
            },
        ],
    },
    {
        "name": "sdc", "path": "/dev/sdc", "type": "disk", "rm": True,
        "hotplug": True, "tran": "usb", "children": [
            {
                "name": "sdc1", "path": "/dev/sdc1", "type": "part",
                "label": "USB STICK", "fstype": "vfat", "size": 64000000000,
                "mountpoint": "/run/media/u/USB STICK",
                "mountpoints": ["/run/media/u/USB STICK"],
                "rm": True, "hotplug": True,
            },
        ],
    },
    {
        "name": "zram0", "path": "/dev/zram0", "type": "disk", "fstype": "swap",
        "mountpoint": "[SWAP]", "mountpoints": ["[SWAP]"], "size": 8000000000,
    },
    # A Windows disk: firmware/vendor partitions carry real filesystems and are
    # only distinguishable from data by their GPT partition type.
    {
        "name": "nvme0n1", "path": "/dev/nvme0n1", "type": "disk", "tran": "nvme",
        "vendor": "", "model": "Samsung SSD 980 PRO 2TB", "children": [
            {
                "name": "nvme0n1p1", "path": "/dev/nvme0n1p1", "type": "part",
                "fstype": "vfat", "size": 471859200, "label": "SYSTEM",
                "parttype": "c12a7328-f81f-11d2-ba4b-00a0c93ec93b",
                "parttypename": "EFI System",
                "mountpoint": None, "mountpoints": [None],
            },
            {
                "name": "nvme0n1p2", "path": "/dev/nvme0n1p2", "type": "part",
                "fstype": "ntfs", "size": 554696704, "label": "Recovery",
                "parttype": "de94bba4-06d1-4d40-a16a-bfd50179d6ac",
                "parttypename": "Windows recovery environment",
                "mountpoint": None, "mountpoints": [None],
            },
            {
                "name": "nvme0n1p3", "path": "/dev/nvme0n1p3", "type": "part",
                "fstype": "ntfs", "size": 1999200000000,
                "partlabel": "Basic data partition",
                "parttype": "ebd0a0a2-b9e5-4433-87c0-68b6b72699c7",
                "parttypename": "Microsoft basic data",
                "mountpoint": None, "mountpoints": [None],
            },
            {
                "name": "nvme0n1p4", "path": "/dev/nvme0n1p4", "type": "part",
                "fstype": "ntfs", "size": 500000000000,
                "parttype": "ebd0a0a2-b9e5-4433-87c0-68b6b72699c7",
                "mountpoint": None, "mountpoints": [None],
            },
        ],
    },
]


def build_service(tmp_path, monkeypatch) -> VolumeService:
    monkeypatch.setattr(volumes_module, "_lsblk_json", lambda: LSBLK)
    mounts_file = tmp_path / "mounts"
    mounts_file.write_text(MOUNTS, encoding="utf-8")
    return VolumeService(
        MountService(str(mounts_file), is_dir=lambda _p: True),
        # Isolate from the real GVFS mounts of whoever runs the tests.
        gvfs_root=lambda: str(tmp_path / "no-gvfs"),
    )


def by_name(service: VolumeService) -> dict:
    return {volume.name: volume for volume in service.volumes()}


def test_shortest_mountpoint_wins():
    """lsblk's scalar mountpoint is arbitrary; the volume root is the shortest."""
    device = {
        "mountpoint": "/home/u/proj/.git/hooks",
        "mountpoints": ["/", "/home", "/home/u/proj/.git/hooks"],
    }
    assert _first_mountpoint(device) == "/"


def test_swap_and_unmounted_pseudo_paths_ignored():
    assert _first_mountpoint({"mountpoint": "[SWAP]", "mountpoints": ["[SWAP]"]}) is None
    assert _first_mountpoint({"mountpoint": None, "mountpoints": [None]}) is None


def test_unmounted_usb_disk_is_listed(tmp_path, monkeypatch):
    """The whole point: a drive no daemon mounted must still be offered."""
    volume = by_name(build_service(tmp_path, monkeypatch))["Backup Drive"]
    assert volume.kind == REMOVABLE
    assert not volume.is_mounted
    assert volume.device == "/dev/sdb2"
    # Nothing to eject until it is mounted.
    assert not volume.is_ejectable


def test_mounted_removable_is_ejectable(tmp_path, monkeypatch):
    volume = by_name(build_service(tmp_path, monkeypatch))["USB STICK"]
    assert volume.kind == REMOVABLE
    assert volume.is_mounted
    assert volume.is_ejectable


def test_system_volume_named_and_not_ejectable(tmp_path, monkeypatch):
    volumes = [v for v in build_service(tmp_path, monkeypatch).volumes() if v.kind == SYSTEM]
    assert len(volumes) == 1
    system = volumes[0]
    assert system.mount_point == "/"
    assert not system.is_ejectable
    # Named after the machine rather than the raw ATA model string.
    assert "INTEL" not in system.name


def test_noise_excluded(tmp_path, monkeypatch):
    names = by_name(build_service(tmp_path, monkeypatch))
    devices = {volume.device for volume in names.values()}
    assert "/dev/zram0" not in devices  # swap
    assert "/dev/sda1" not in devices  # EFI/boot partition
    assert "/dev/sda" not in devices  # partitioned parent disk
    assert "/dev/sdb" not in devices


def test_network_share_deduplicated(tmp_path, monkeypatch):
    """A triggered autofs share appears twice in /proc/mounts; show it once."""
    shares = [v for v in build_service(tmp_path, monkeypatch).volumes() if v.kind == NETWORK]
    transport = [v for v in shares if v.mount_point == "/mnt/transport"]
    assert len(transport) == 1
    # The concrete mount wins over the autofs placeholder.
    assert transport[0].fstype == "cifs"
    assert {v.mount_point for v in shares} == {"/mnt/transport", "/mnt/Anime"}


def test_internal_partition_not_confused_with_removable(tmp_path, monkeypatch):
    for volume in build_service(tmp_path, monkeypatch).volumes():
        if volume.device == "/dev/sda2":
            assert volume.kind in (SYSTEM, INTERNAL)


def test_firmware_partitions_hidden(tmp_path, monkeypatch):
    """EFI and recovery partitions hold real filesystems but are not user data."""
    names = by_name(build_service(tmp_path, monkeypatch))
    devices = {volume.device for volume in names.values()}
    assert "/dev/nvme0n1p1" not in devices  # EFI System
    assert "/dev/nvme0n1p2" not in devices  # Windows Recovery
    # The USB installer's own EFI partition goes too, keeping only its data half.
    assert "EFI" not in names
    assert "/dev/sdb1" not in devices
    assert "/dev/sdb2" in devices


def test_windows_data_partition_offered(tmp_path, monkeypatch):
    volume = by_name(build_service(tmp_path, monkeypatch))["Basic data partition"]
    assert volume.device == "/dev/nvme0n1p3"
    assert not volume.is_mounted


def test_unlabelled_partition_named_by_size(tmp_path, monkeypatch):
    """Siblings must not all inherit the parent disk's model name."""
    names = by_name(build_service(tmp_path, monkeypatch))
    assert "500.00 GB Volume" in names
    assert names["500.00 GB Volume"].device == "/dev/nvme0n1p4"
    assert "Samsung SSD 980 PRO 2TB" not in names


def test_mount_output_parsing():
    parse = VolumeService._parse_mount_output
    assert parse("Mounted /dev/sdb1 at /run/media/u/BACKUP.") == "/run/media/u/BACKUP"
    assert parse("nothing useful") is None


# --------------------------------------------------------------- GVFS mounts
#
# /proc/mounts lists only the single gvfsd-fuse root, never the individual
# shares, so a GVFS mount used to be invisible in the sidebar.


def test_parse_smb_share_dir():
    assert _parse_gvfs_dir("smb-share:server=172.16.0.47,share=data") == (
        "data",
        "smb://172.16.0.47/data",
    )


def test_parse_uses_the_share_name_not_the_host():
    label, _ = _parse_gvfs_dir("smb-share:server=nas,share=tv shows")
    assert label == "tv shows"


def test_parse_host_only_backends():
    # sftp and ftp expose one filesystem, so the host is the name.
    assert _parse_gvfs_dir("sftp:host=buildbox") == ("buildbox", "sftp://buildbox")
    assert _parse_gvfs_dir("ftp:host=files.example") == (
        "files.example",
        "ftp://files.example",
    )


def test_parse_other_backend_key_names():
    assert _parse_gvfs_dir("nfs:host=box,export=vol1")[0] == "vol1"
    assert _parse_gvfs_dir("afp-volume:host=mac,volume=Media")[0] == "Media"


def test_parse_rejects_non_mount_names():
    assert _parse_gvfs_dir("not-a-mount") is None
    assert _parse_gvfs_dir("") is None
    # Nothing identifying in the parameters.
    assert _parse_gvfs_dir("smb-share:ssl=true") is None


def test_gvfs_shares_appear_as_network_volumes(tmp_path, monkeypatch):
    root = tmp_path / "gvfs"
    root.mkdir()
    (root / "smb-share:server=172.16.0.47,share=data").mkdir()
    (root / "sftp:host=buildbox").mkdir()
    (root / "junk-file").write_text("")  # not a directory
    service = VolumeService(MountService(), gvfs_root=lambda: str(root))
    found = service._gvfs_volumes()

    assert sorted(v.name for v in found) == ["buildbox", "data"]
    assert all(v.kind == NETWORK for v in found)
    # Network mounts get an eject control.
    assert all(v.is_ejectable for v in found)


def test_gvfs_share_mount_point_is_the_fuse_dir(tmp_path, monkeypatch):
    root = tmp_path / "gvfs"
    root.mkdir()
    share = root / "smb-share:server=nas,share=media"
    share.mkdir()
    service = VolumeService(MountService(), gvfs_root=lambda: str(root))
    volume = service._gvfs_volumes()[0]
    assert volume.mount_point == str(share)
    assert volume.is_mounted


def test_missing_gvfs_root_is_not_fatal():
    service = VolumeService(MountService(), gvfs_root=lambda: "/nonexistent/gvfs")
    assert service._gvfs_volumes() == []
