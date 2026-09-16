"""Tests for MountService."""

from hyprfind.core.mounts import MountService, parse_mounts


SAMPLE_MOUNTS = """\
/dev/nvme0n1p2 / ext4 rw,relatime 0 0
/dev/nvme0n1p2 /home ext4 rw,relatime 0 0
//server/share /mnt/smb/share cifs rw,relatime 0 0
tmpfs /run/user/1000/gvfs fuse.gvfsd-fuse rw,nosuid,nodev,relatime 0 0
"""

# A CachyOS-style table: btrfs subvolumes, bind mounts, autofs shares, and an
# AppImage FUSE mount all sharing devices with real volumes.
NOISY_MOUNTS = """\
/dev/sda2 / btrfs rw,subvol=/@ 0 0
/dev/sda2 /home btrfs rw,subvol=/@home 0 0
/dev/sda2 /var/cache btrfs rw,subvol=/@cache 0 0
/dev/sda2 /var/log btrfs rw,subvol=/@log 0 0
/dev/sda2 /home/u/proj/.git/hooks btrfs ro,subvol=/@home 0 0
/dev/sda1 /boot vfat rw,relatime 0 0
systemd-1 /mnt/Anime autofs rw,relatime 0 0
systemd-1 /mnt/transport autofs rw,relatime 0 0
Cursor.AppImage /tmp/.mount_CursorX fuse.Cursor.AppImage ro,nosuid 0 0
/dev/sdb1 /run/media/u/BACKUP exfat rw,relatime 0 0
tmpfs /tmp tmpfs rw,noatime 0 0
"""


def service_from(text: str, tmp_path) -> MountService:
    """A MountService that reads `text` instead of the live mount table."""
    path = tmp_path / "mounts"
    path.write_text(text, encoding="utf-8")
    return MountService(str(path), is_dir=lambda _p: True)


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


def test_volume_mounts_filters_system(tmp_path):
    service = service_from(SAMPLE_MOUNTS, tmp_path)
    mount_points = {m.mount_point for m in service.volume_mounts()}
    assert "/" in mount_points
    assert "/mnt/smb/share" in mount_points
    assert "/run/user/1000/gvfs" not in mount_points


def test_volume_mounts_collapses_subvolumes_and_binds(tmp_path):
    service = service_from(NOISY_MOUNTS, tmp_path)
    mount_points = {m.mount_point for m in service.volume_mounts()}

    # One entry per backing device, using its shortest mount point.
    assert "/" in mount_points
    assert "/home" not in mount_points
    assert "/var/cache" not in mount_points
    assert "/home/u/proj/.git/hooks" not in mount_points

    # Real removable media survives; boot, tmpfs, and AppImage noise does not.
    assert "/run/media/u/BACKUP" in mount_points
    assert "/boot" not in mount_points
    assert "/tmp" not in mount_points
    assert "/tmp/.mount_CursorX" not in mount_points


def test_volume_mounts_keeps_each_autofs_share(tmp_path):
    """Pseudo devices reuse one name, so they must not be deduplicated."""
    service = service_from(NOISY_MOUNTS, tmp_path)
    mount_points = {m.mount_point for m in service.volume_mounts()}
    assert "/mnt/Anime" in mount_points
    assert "/mnt/transport" in mount_points


def test_autofs_counts_as_network(tmp_path):
    service = service_from(NOISY_MOUNTS, tmp_path)
    assert service.is_network_path("/mnt/Anime/show")
