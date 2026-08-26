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


def test_build_parted_print_command():
    assert partition.build_parted_print_command("/dev/sdb") == [
        "parted", "--machine", "--script", "/dev/sdb", "unit", "B", "print",
    ]


def test_parse_parted_partition_starts():
    raw = (
        "BYT;\n"
        "/dev/sdd:124017180672B:scsi:512:512:msdos:Kingston DT microDuo 3C:;\n"
        "2:15783211008B:15787405311B:4194304B:primary::esp;\n"
        "1:15788408832B:124017180671B:108228771840B:primary::;\n"
    )
    assert partition.parse_parted_partition_starts(raw) == {
        2: 15783211008,
        1: 15788408832,
    }


def test_parse_parted_partition_starts_empty_disk():
    raw = "BYT;\n/dev/sdd:124017180672B:scsi:512:512:msdos:Kingston DT microDuo 3C:;\n"
    assert partition.parse_parted_partition_starts(raw) == {}


@pytest.mark.parametrize(
    "mount_device,device_path,expected",
    [
        ("/dev/sdd1", "/dev/sdd", 1),
        ("/dev/sdd12", "/dev/sdd", 12),
        ("/dev/nvme0n1p3", "/dev/nvme0n1", 3),
        ("/dev/sdd", "/dev/sdd", None),
        ("/dev/sde1", "/dev/sdd", None),
    ],
)
def test_partition_number(mount_device, device_path, expected):
    assert partition._partition_number(mount_device, device_path) == expected


def test_resolve_partition_by_start_matches_smallest_start_at_or_after():
    # The exact collision both real crashes hit: /dev/sdd1 already existed
    # (leftover from a prior run at a different, smaller start), and the
    # freshly mkpart'd partition reused that same path -- must still match
    # by position, not be confused by the path having existed before.
    starts = {1: 15788408832, 2: 15783211008}
    paths = {"/dev/sdd1", "/dev/sdd2"}
    assert partition.resolve_partition_by_start(starts, paths, "/dev/sdd", 15788408832) == "/dev/sdd1"


def test_resolve_partition_by_start_tolerates_alignment_snap_past_the_old_fixed_window():
    # --align optimal can push the actual start further than a small fixed
    # tolerance would allow (the previous, replaced implementation's bug) --
    # matching by "smallest start >= requested" has no such ceiling.
    snapped = 15788408832 + 4 * 1024 * 1024
    starts = {1: snapped, 2: 15783211008}
    paths = {"/dev/sdd1", "/dev/sdd2"}
    assert partition.resolve_partition_by_start(starts, paths, "/dev/sdd", 15788408832) == "/dev/sdd1"


def test_resolve_partition_by_start_returns_none_when_nothing_qualifies():
    starts = {2: 15783211008}
    paths = {"/dev/sdd2"}
    assert partition.resolve_partition_by_start(starts, paths, "/dev/sdd", 15788408832) is None


def test_resolve_partition_by_start_raises_on_more_than_one_candidate():
    # Would only happen if append_persist_partition's documented
    # precondition (device freshly reimaged before this call) didn't hold --
    # must fail loud rather than silently pick one and mkfs.ext4 it.
    starts = {1: 15788408832, 3: 20000000000}
    paths = {"/dev/sdd1", "/dev/sdd3"}
    with pytest.raises(RuntimeError, match="found 2"):
        partition.resolve_partition_by_start(starts, paths, "/dev/sdd", 15788408832)
