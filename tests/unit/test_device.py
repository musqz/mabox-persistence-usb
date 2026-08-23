import json

from mabox_persistence_usb import device


def lsblk_json(disks):
    return json.dumps({"blockdevices": disks})


def make_disk_node(name="sdb", type_="disk", size=8_000_000_000, rm=True, tran="usb", children=None, **overrides):
    node = {
        "name": name, "path": f"/dev/{name}", "type": type_, "size": size,
        "model": "Flash Drive", "vendor": "Generic", "serial": "ABC123",
        "tran": tran, "rm": rm, "ro": False, "fstype": None, "label": None,
        "mountpoints": [None],
    }
    if children is not None:
        node["children"] = children
    node.update(overrides)
    return node


def make_part_node(name="sdb1", fstype="ext4", label=None, mountpoints=None):
    return {
        "name": name, "path": f"/dev/{name}", "type": "part",
        "fstype": fstype, "label": label, "mountpoints": mountpoints or [None],
    }


def test_parse_lsblk_json_extracts_disk_fields():
    raw = lsblk_json([make_disk_node()])
    disks = device.parse_lsblk_json(raw)
    assert len(disks) == 1
    disk = disks[0]
    assert disk.path == "/dev/sdb"
    assert disk.size_bytes == 8_000_000_000
    assert disk.vendor == "Generic"
    assert disk.model == "Flash Drive"
    assert disk.serial == "ABC123"
    assert disk.tran == "usb"
    assert disk.removable is True
    assert disk.partitions == ()


def test_parse_lsblk_json_ignores_non_disk_top_level_entries():
    raw = lsblk_json([make_disk_node(type_="rom", name="sr0")])
    assert device.parse_lsblk_json(raw) == []


def test_parse_lsblk_json_parses_child_partitions():
    children = [make_part_node(label="MABOX_LIVE", mountpoints=["/mnt/x"]), make_part_node(name="sdb2", fstype=None)]
    raw = lsblk_json([make_disk_node(children=children)])
    disk = device.parse_lsblk_json(raw)[0]
    assert len(disk.partitions) == 2
    assert disk.partitions[0].path == "/dev/sdb1"
    assert disk.partitions[0].label == "MABOX_LIVE"
    assert disk.partitions[0].mountpoints == ("/mnt/x",)
    assert disk.partitions[1].fstype is None


def test_parse_lsblk_json_ignores_non_partition_children():
    children = [make_part_node(), {"name": "sdb1_crypt", "type": "crypt", "path": "/dev/mapper/x"}]
    raw = lsblk_json([make_disk_node(children=children)])
    disk = device.parse_lsblk_json(raw)[0]
    assert len(disk.partitions) == 1


def test_parse_udevadm_properties():
    raw = "ID_BUS=usb\nID_SERIAL_SHORT=ABC123\nDEVTYPE=disk\n"
    props = device.parse_udevadm_properties(raw)
    assert props == {"ID_BUS": "usb", "ID_SERIAL_SHORT": "ABC123", "DEVTYPE": "disk"}


def _disk(removable=True, tran="usb"):
    return device.UsbDisk(
        path="/dev/sdb", size_bytes=1, vendor=None, model=None, serial=None,
        tran=tran, removable=removable, partitions=(),
    )


def test_is_removable_usb_true_when_rm_and_tran_usb():
    assert device.is_removable_usb(_disk(removable=True, tran="usb")) is True


def test_is_removable_usb_false_when_not_removable():
    assert device.is_removable_usb(_disk(removable=False, tran="usb")) is False


def test_is_removable_usb_false_when_tran_not_usb_and_no_udev_fallback():
    assert device.is_removable_usb(_disk(removable=True, tran="sata")) is False


def test_is_removable_usb_uses_udev_fallback_when_tran_empty():
    disk = _disk(removable=True, tran=None)
    assert device.is_removable_usb(disk, udev_props={"ID_BUS": "usb"}) is True


def test_is_removable_usb_false_when_udev_fallback_reports_non_usb_bus():
    disk = _disk(removable=True, tran=None)
    assert device.is_removable_usb(disk, udev_props={"ID_BUS": "ata"}) is False


def test_fits_in_mbr_just_under_limit():
    assert device.fits_in_mbr(device.constants.MAX_MBR_DEVICE_BYTES - 1) is True


def test_fits_in_mbr_at_or_over_limit():
    assert device.fits_in_mbr(device.constants.MAX_MBR_DEVICE_BYTES) is False


def test_list_removable_usb_disks_filters_and_uses_udev_fallback():
    non_usb = make_disk_node(name="sda", tran="sata", rm=False)
    usb_direct = make_disk_node(name="sdb", tran="usb")
    usb_via_udev = make_disk_node(name="sdc", tran=None)
    raw = lsblk_json([non_usb, usb_direct, usb_via_udev])

    def fake_lsblk():
        return raw

    def fake_udevadm(devpath):
        if devpath == "/dev/sdc":
            return "ID_BUS=usb\n"
        return "ID_BUS=ata\n"

    result = device.list_removable_usb_disks(lsblk_runner=fake_lsblk, udevadm_runner=fake_udevadm)
    assert {d.path for d in result} == {"/dev/sdb", "/dev/sdc"}


def test_get_disk_by_path_found_and_missing():
    disk = _disk()
    assert device.get_disk_by_path("/dev/sdb", [disk]) is disk
    assert device.get_disk_by_path("/dev/sdz", [disk]) is None


def test_parse_proc_mounts():
    raw = "/dev/sda1 / ext4 rw,relatime 0 0\n/dev/sdb1 /mnt/usb vfat rw 0 0\n"
    assert device.parse_proc_mounts(raw) == [("/dev/sda1", "/"), ("/dev/sdb1", "/mnt/usb")]


def test_parse_proc_swaps_skips_header():
    raw = "Filename\t\t\t\tType\t\tSize\tUsed\tPriority\n/dev/sda2               partition\t2097148\t0\t-2\n"
    assert device.parse_proc_swaps(raw) == ["/dev/sda2"]


def test_is_hosting_critical_mount_true_for_root():
    mounts = [("/dev/sdb1", "/")]
    assert device.is_hosting_critical_mount("/dev/sdb", mounts, []) is True


def test_is_hosting_critical_mount_false_for_unrelated_disk():
    mounts = [("/dev/sda1", "/")]
    assert device.is_hosting_critical_mount("/dev/sdb", mounts, []) is False


def test_is_hosting_critical_mount_false_for_non_critical_mountpoint():
    mounts = [("/dev/sdb1", "/mnt/usb")]
    assert device.is_hosting_critical_mount("/dev/sdb", mounts, []) is False


def test_is_hosting_critical_mount_true_for_active_swap():
    assert device.is_hosting_critical_mount("/dev/sdb", [], ["/dev/sdb2"]) is True


def test_build_lsblk_command_includes_columns():
    cmd = device.build_lsblk_command()
    assert cmd[0] == "lsblk"
    assert device.LSBLK_COLUMNS in cmd


def test_build_udevadm_info_command():
    assert device.build_udevadm_info_command("/dev/sdb") == [
        "udevadm", "info", "--query=property", "--name=/dev/sdb"
    ]


def test_build_umount_command():
    assert device.build_umount_command("/mnt/usb") == ["umount", "/mnt/usb"]
