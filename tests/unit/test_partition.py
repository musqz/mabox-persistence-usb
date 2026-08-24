import json

import pytest

from mabox_persistence_usb import constants, partition


def test_compute_partition_start_exact_multiple_stays_same():
    assert partition.compute_partition_start(2 * 1024 * 1024) == 2 * 1024 * 1024


def test_compute_partition_start_rounds_up_to_alignment():
    size = 1500 * 1024  # 1.46 MiB, not aligned
    result = partition.compute_partition_start(size)
    assert result == 2 * 1024 * 1024
    assert result % constants.PARTITION_ALIGNMENT_BYTES == 0


@pytest.mark.parametrize(
    "spec,expected",
    [
        ("50GiB", 50 * 1024**3),
        ("512MiB", 512 * 1024**2),
        ("1TiB", 1024**4),
        ("1000", 1000),
    ],
)
def test_compute_persist_size_bytes(spec, expected):
    assert partition.compute_persist_size_bytes(spec) == expected


def test_compute_partition_end_spec_defaults_to_100_percent():
    assert partition.compute_partition_end_spec(1024, None, 10_000_000) == "100%"


def test_compute_partition_end_spec_returns_absolute_offset_when_it_fits():
    end = partition.compute_partition_end_spec(1000, 5000, 10_000)
    assert end == "6000B"


def test_compute_partition_end_spec_raises_when_it_does_not_fit():
    with pytest.raises(ValueError, match="does not fit"):
        partition.compute_partition_end_spec(1000, 50_000, 10_000)


def test_build_parted_mkpart_command():
    cmd = partition.build_parted_mkpart_command("/dev/sdb", 1048576, "100%")
    assert cmd == [
        "parted", "--script", "--align", "optimal", "/dev/sdb",
        "unit", "B", "mkpart", "primary", "ext4", "1048576B", "100%",
    ]


def test_build_partprobe_command():
    assert partition.build_partprobe_command("/dev/sdb") == ["partprobe", "/dev/sdb"]


def test_build_udevadm_settle_command():
    assert partition.build_udevadm_settle_command() == ["udevadm", "settle"]


def test_build_mkfs_ext4_command_uses_persist_label_by_default():
    cmd = partition.build_mkfs_ext4_command("/dev/sdb3")
    assert cmd == ["mkfs.ext4", "-F", "-L", constants.PERSIST_LABEL, "/dev/sdb3"]


@pytest.mark.parametrize(
    "mount_device,device_path,expected",
    [
        ("/dev/sdd1", "/dev/sdd", True),
        ("/dev/sdd12", "/dev/sdd", True),
        ("/dev/nvme0n1p1", "/dev/nvme0n1", True),
        ("/dev/sdd", "/dev/sdd", False),
        ("/dev/sdaa1", "/dev/sda", False),
        ("/dev/nvme0n10p1", "/dev/nvme0n1", False),
        ("/dev/sde1", "/dev/sdd", False),
    ],
)
def test_is_partition_of(mount_device, device_path, expected):
    assert partition.is_partition_of(mount_device, device_path) is expected


def test_parse_lsblk_partition_paths():
    raw = json.dumps({
        "blockdevices": [
            {"name": "sdb", "path": "/dev/sdb", "children": [
                {"name": "sdb1", "path": "/dev/sdb1"},
                {"name": "sdb2", "path": "/dev/sdb2"},
            ]}
        ]
    })
    assert partition.parse_lsblk_partition_paths(raw) == {"/dev/sdb1", "/dev/sdb2"}


def test_resolve_new_partition_finds_the_diff():
    before = {"/dev/sdb1", "/dev/sdb2"}
    after = {"/dev/sdb1", "/dev/sdb2", "/dev/sdb3"}
    assert partition.resolve_new_partition(before, after) == "/dev/sdb3"


def test_resolve_new_partition_raises_when_not_exactly_one_new():
    with pytest.raises(RuntimeError):
        partition.resolve_new_partition({"/dev/sdb1"}, {"/dev/sdb1"})
    with pytest.raises(RuntimeError):
        partition.resolve_new_partition({"/dev/sdb1"}, {"/dev/sdb1", "/dev/sdb2", "/dev/sdb3"})
