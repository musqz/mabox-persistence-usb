"""Device enumeration and the hard removable-USB-only safety filter.

Command-builder/parser functions are pure and unit-tested; list_removable_usb_disks()
is a thin executor that wires them to real subprocess calls by default but accepts
injectable runners for testing -- same split as mabox_snapshot/luks.py."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass

from . import constants


@dataclass(frozen=True)
class UsbPartition:
    path: str
    fstype: str | None
    label: str | None
    mountpoints: tuple[str, ...]


@dataclass(frozen=True)
class UsbDisk:
    path: str
    size_bytes: int
    vendor: str | None
    model: str | None
    serial: str | None
    tran: str | None
    removable: bool
    partitions: tuple[UsbPartition, ...]


LSBLK_COLUMNS = "NAME,PATH,TYPE,SIZE,MODEL,VENDOR,SERIAL,TRAN,RM,RO,FSTYPE,LABEL,MOUNTPOINTS"


def build_lsblk_command() -> list[str]:
    return ["lsblk", "-J", "-b", "-o", LSBLK_COLUMNS]


def build_udevadm_info_command(devpath: str) -> list[str]:
    return ["udevadm", "info", "--query=property", f"--name={devpath}"]


def build_umount_command(mountpoint: str) -> list[str]:
    return ["umount", mountpoint]


def _clean(value) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _parse_partition(node: dict) -> UsbPartition:
    mountpoints_raw = node.get("mountpoints") or []
    mountpoints = tuple(m for m in mountpoints_raw if m)
    return UsbPartition(
        path=node.get("path") or f"/dev/{node.get('name')}",
        fstype=_clean(node.get("fstype")),
        label=_clean(node.get("label")),
        mountpoints=mountpoints,
    )


def parse_lsblk_json(raw: str) -> list[UsbDisk]:
    """Parses `lsblk -J -b -o <LSBLK_COLUMNS>` output into UsbDisk objects,
    one per TYPE=="disk" top-level entry. Partitions (TYPE=="part") nested
    under a disk's "children" become its UsbPartition list; anything else
    (e.g. a "rom" optical entry, or a nested "crypt"/"lvm" mapping) is
    ignored -- neither is ever a valid write target."""
    data = json.loads(raw)
    disks = []
    for node in data.get("blockdevices", []):
        if node.get("type") != "disk":
            continue
        children = node.get("children") or []
        partitions = tuple(
            _parse_partition(child) for child in children if child.get("type") == "part"
        )
        disks.append(
            UsbDisk(
                path=node.get("path") or f"/dev/{node.get('name')}",
                size_bytes=int(node.get("size") or 0),
                vendor=_clean(node.get("vendor")),
                model=_clean(node.get("model")),
                serial=_clean(node.get("serial")),
                tran=_clean(node.get("tran")),
                removable=bool(node.get("rm")),
                partitions=partitions,
            )
        )
    return disks


def parse_udevadm_properties(raw: str) -> dict[str, str]:
    props = {}
    for line in raw.splitlines():
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        props[key.strip()] = value.strip()
    return props


def is_removable_usb(disk: UsbDisk, udev_props: dict[str, str] | None = None) -> bool:
    """The hard filter. A disk is only ever eligible if it is both kernel-
    removable and USB-attached -- checked via lsblk's TRAN column first,
    falling back to udevadm's ID_BUS for USB bridge chipsets confirmed to
    report an empty TRAN."""
    if not disk.removable:
        return False
    if disk.tran == "usb":
        return True
    if udev_props is not None and udev_props.get("ID_BUS") == "usb":
        return True
    return False


def fits_in_mbr(size_bytes: int) -> bool:
    return size_bytes < constants.MAX_MBR_DEVICE_BYTES


def _run_lsblk() -> str:
    return subprocess.run(build_lsblk_command(), capture_output=True, text=True, check=True).stdout


def _run_udevadm(devpath: str) -> str:
    return subprocess.run(
        build_udevadm_info_command(devpath), capture_output=True, text=True, check=True
    ).stdout


def list_removable_usb_disks(lsblk_runner=None, udevadm_runner=None) -> list[UsbDisk]:
    """Thin executor: parse_lsblk_json()/is_removable_usb() hold the real
    logic and are unit-tested directly; this just wires them to real
    subprocess calls by default, accepting injectable runners for tests."""
    lsblk_runner = lsblk_runner or _run_lsblk
    udevadm_runner = udevadm_runner or _run_udevadm

    disks = parse_lsblk_json(lsblk_runner())
    eligible = []
    for disk in disks:
        udev_props = None
        if disk.tran != "usb":
            udev_props = parse_udevadm_properties(udevadm_runner(disk.path))
        if is_removable_usb(disk, udev_props):
            eligible.append(disk)
    return eligible


def get_disk_by_path(path: str, disks: list[UsbDisk]) -> UsbDisk | None:
    for disk in disks:
        if disk.path == path:
            return disk
    return None


def unmount_partition(mountpoint: str) -> None:
    subprocess.run(build_umount_command(mountpoint), check=True)


# --- critical-mount guard -------------------------------------------------


def parse_proc_mounts(raw: str) -> list[tuple[str, str]]:
    """Returns a list of (device, mountpoint) pairs from /proc/mounts-format text."""
    pairs = []
    for line in raw.splitlines():
        fields = line.split()
        if len(fields) < 2:
            continue
        pairs.append((fields[0], fields[1]))
    return pairs


def parse_proc_swaps(raw: str) -> list[str]:
    """Returns the device column of each active swap entry from
    /proc/swaps-format text (header line first, skipped)."""
    devices = []
    for line in raw.splitlines()[1:]:
        fields = line.split()
        if fields:
            devices.append(fields[0])
    return devices


def is_hosting_critical_mount(
    disk_path: str,
    mounts: list[tuple[str, str]],
    swap_devices: list[str],
    critical_mountpoints: frozenset[str] = constants.CRITICAL_MOUNTPOINTS,
) -> bool:
    """True if any partition of disk_path backs a critical mountpoint (/,
    /boot, /home, /var) or active swap. Matches by device-path prefix
    (disk_path="/dev/sdb" matches partition device "/dev/sdb1")."""
    for device_path, mountpoint in mounts:
        if device_path.startswith(disk_path) and mountpoint in critical_mountpoints:
            return True
    for device_path in swap_devices:
        if device_path.startswith(disk_path):
            return True
    return False
