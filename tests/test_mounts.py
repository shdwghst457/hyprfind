"""Tests for MountService."""

from hyprfind.core.mounts import MountService, parse_mounts


SAMPLE_MOUNTS = """\
/dev/nvme0n1p2 / ext4 rw,relatime 0 0
/dev/nvme0n1p2 /home ext4 rw,relatime 0 0
//server/share /mnt/smb/share cifs rw,relatime 0 0
tmpfs /run/user/1000/gvfs fuse.gvfsd-fuse rw,nosuid,nodev,relatime 0 0
"""


def test_parse_mounts():
    mounts = parse_mounts(SAMPLE_MOUNTS)
    assert len(mounts) == 4
    assert mounts[2].mount_point == "/mnt/smb/share"
    assert mounts[2].fstype == "cifs"
    assert mounts[2].is_network


def test_mount_for_path_longest_prefix(tmp_path):
    service = MountService()
    service._mounts = parse_mounts(SAMPLE_MOUNTS)

    assert service.mount_for_path("/mnt/smb/share/docs").fstype == "cifs"
    assert service.mount_for_path("/home/user").fstype == "ext4"
    assert service.mount_for_path("/").fstype == "ext4"


def test_is_network_path():
    service = MountService()
    service._mounts = parse_mounts(SAMPLE_MOUNTS)

    assert service.is_network_path("/mnt/smb/share/file.txt")
    assert not service.is_network_path("/home/user/file.txt")


def test_volume_mounts_filters_system():
    service = MountService()
    service._mounts = parse_mounts(SAMPLE_MOUNTS)
    volumes = service.volume_mounts()
    mount_points = {m.mount_point for m in volumes}
    assert "/" in mount_points
    assert "/mnt/smb/share" in mount_points
    assert "/run/user/1000/gvfs" not in mount_points
