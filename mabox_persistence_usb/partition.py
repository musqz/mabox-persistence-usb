"""Appending and formatting the MABOX_PERSIST overlay partition.

parted, not sgdisk (gptfdisk's tool is GPT-specific -- wrong fit for the
msdos/MBR label the ISO's own hybrid layout uses) and not raw sfdisk
scripting (would require hand-reconstructing the ISO's own two-entry table
as a string). parted natively understands the existing msdos table and can
append a new primary entry in one scripted command without needing to know
or preserve the ISO's own partition-table entries by hand.

Command-builder functions are pure and unit-tested; the functions that
actually run them (real parted/mkfs.ext4, needs root) are thin subprocess.run()
wrappers and are not unit-tested -- same untested-execution-layer precedent
as mabox_snapshot/luks.py."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from . import constants, device


def compute_partition_start(iso_size_bytes: int, alignment: int = constants.PARTITION_ALIGNMENT_BYTES) -> int:
    """Rounds the ISO's own byte size up to the next alignment boundary. No
    gap to account for beyond alignment: mabox-snapshot's xorriso assembly
    appends the EFI image's bytes onto the end of the ISO file itself
    (isobuild.py's `-append_partition 2 0xef efi.img`), so the ISO's own two
    MBR entries already span [0, iso_size_bytes) with nothing left unclaimed
    in between."""
    remainder = iso_size_bytes % alignment
    if remainder == 0:
        return iso_size_bytes
    return iso_size_bytes + (alignment - remainder)


_SIZE_UNITS = {
    "TiB": 1024**4, "GiB": 1024**3, "MiB": 1024**2, "KiB": 1024,
    "TB": 1000**4, "GB": 1000**3, "MB": 1000**2, "KB": 1000,
    "B": 1,
}


def compute_persist_size_bytes(size_spec: str) -> int:
    """Parses a parted-style size string ('50GiB', '512MiB', a bare byte
    count, ...) into bytes."""
    size_spec = size_spec.strip()
    for suffix in sorted(_SIZE_UNITS, key=len, reverse=True):
        if size_spec.endswith(suffix):
            number = size_spec[: -len(suffix)].strip()
            return int(float(number) * _SIZE_UNITS[suffix])
    return int(size_spec)


def compute_partition_end_spec(start_bytes: int, persist_size_bytes: int | None, device_size_bytes: int) -> str:
    """Returns a parted-compatible end position: '100%' when no explicit
    size was requested (the default -- all remaining space), else an
    absolute byte offset. Raises ValueError if an explicit size would not
    fit on the device."""
    if persist_size_bytes is None:
        return "100%"
    end = start_bytes + persist_size_bytes
    if end > device_size_bytes:
        shortfall = end - device_size_bytes
        raise ValueError(
            f"--persist-size does not fit: the device would need to be at least "
            f"{shortfall} more bytes."
        )
    return f"{end}B"


def build_parted_mkpart_command(device_path: str, start_bytes: int, end_spec: str) -> list[str]:
    return [
        "parted", "--script", "--align", "optimal", device_path,
        "unit", "B", "mkpart", "primary", "ext4", f"{start_bytes}B", end_spec,
    ]


def build_partprobe_command(device_path: str) -> list[str]:
    return ["partprobe", device_path]


def build_udevadm_settle_command() -> list[str]:
    return ["udevadm", "settle"]


def is_partition_of(mount_device: str, device_path: str) -> bool:
    """True if mount_device (e.g. '/dev/sdd1', '/dev/nvme0n1p1') is a
    partition of device_path -- not just any string with device_path as a
    prefix, since a bare prefix match also catches an unrelated disk, e.g.
    '/dev/sdaa1'.startswith('/dev/sda') is True once sd-naming overflows
    past sdz, and the same collision applies to NVMe namespaces
    (nvme0n1 vs nvme0n10+)."""
    if not mount_device.startswith(device_path):
        return False
    suffix = mount_device[len(device_path):]
    return suffix.lstrip("p").isdigit()


def _clear_stale_holders(device_path: str) -> None:
    """A desktop automount daemon (udisks2/gvfs) doesn't just react once --
    it re-mounts on sight. dd rewriting the disk makes its filesystem label
    (e.g. MABOX_LIVE) reappear, which the daemon treats as newly inserted
    removable media and auto-mounts again, even though the tool unmounted it
    itself before writing. A previous run's --encrypt-persist overlay can
    also still be open as /dev/mapper/PERSIST_LUKS_MAPPER_NAME from an
    earlier session on this same stick -- device.py's lsblk parser
    explicitly ignores dm-crypt 'crypt' children, so nothing upstream ever
    notices or closes it. Either one holds a partition busy exactly the way
    a manually-mounted partition would, which is what actually blocks the
    kernel's BLKRRPART with "in use" -- no amount of waiting fixes it if
    something keeps re-grabbing the device, which is why a plain retry loop
    (and even a reboot, since the daemon just comes back) can fail forever.
    Best-effort throughout, deliberately swallowing OSError as well as a
    failed command: there may be nothing to clear, and `umount`/`cryptsetup`
    not being on PATH, or /proc/mounts being unreadable, should never abort
    the retry loop that calls this."""
    mapper_source = f"/dev/mapper/{constants.PERSIST_LUKS_MAPPER_NAME}"
    try:
        mounts = device.parse_proc_mounts(constants.PROC_MOUNTS_FILE.read_text())
    except OSError:
        mounts = []
    for mount_device, mountpoint in mounts:
        if is_partition_of(mount_device, device_path) or mount_device == mapper_source:
            try:
                subprocess.run(device.build_umount_command(mountpoint), check=False)
            except OSError:
                pass
    try:
        subprocess.run(
            ["cryptsetup", "close", constants.PERSIST_LUKS_MAPPER_NAME],
            check=False, stderr=subprocess.DEVNULL,
        )
    except OSError:
        pass


def _partprobe_with_retry(
    device_path: str,
    retries: int = constants.PARTPROBE_RETRIES,
    delay_s: float = constants.PARTPROBE_RETRY_DELAY_S,
) -> None:
    """partprobe can transiently fail the same way parted's own mkpart can
    ("unable to inform the kernel ... probably because it/they are in use")
    when a desktop automount daemon (udisks2/gvfs) is still reacting to the
    device having just been written/repartitioned. Safe to retry: partprobe
    only asks the kernel to reread, no destructive side effects. The first
    attempt is left alone (no automount race has been observed yet); only
    once partprobe has actually failed once do later attempts first clear
    whatever's holding the device busy -- see _clear_stale_holders -- since
    that's the actual blocker, not just transient busy-ness that time alone
    resolves."""
    last_error = None
    for attempt in range(retries):
        if attempt > 0:
            _clear_stale_holders(device_path)
        try:
            subprocess.run(build_partprobe_command(device_path), check=True)
            return
        except subprocess.CalledProcessError as e:
            last_error = e
            if attempt < retries - 1:
                time.sleep(delay_s)
    raise last_error


def reread_partition_table(device_path: str) -> None:
    """Forces the kernel to notice the partition table dd just wrote before
    anything else touches the device. Without this, the kernel keeps
    whatever partition table it had cached from before the write (e.g. a
    previous run's own MABOX_PERSIST layout) -- append_persist_partition()'s
    later `parted mkpart` then fails with parted's "unable to inform the
    kernel of the change ... probably because it/they are in use", because
    parted is trying to update a table the kernel doesn't think is current.
    Settles first too, so any udev/automount reaction already queued from
    dd's own write has a chance to finish before partprobe competes with it.
    Note this can forcibly unmount and close things on device_path (see
    _partprobe_with_retry / _clear_stale_holders) -- not a read-only probe
    once the first attempt fails."""
    subprocess.run(build_udevadm_settle_command(), check=True)
    _partprobe_with_retry(device_path)
    subprocess.run(build_udevadm_settle_command(), check=True)


def build_lsblk_partitions_command(device_path: str) -> list[str]:
    return ["lsblk", "-J", "-b", "-o", "NAME,PATH", device_path]


def parse_lsblk_partition_paths(raw: str) -> set[str]:
    data = json.loads(raw)
    paths = set()
    for node in data.get("blockdevices", []):
        for child in node.get("children") or []:
            path = child.get("path")
            if path:
                paths.add(path)
    return paths


def resolve_new_partition(before: set[str], after: set[str]) -> str:
    """Diffs partition paths before/after the parted mkpart call -- never
    assumes the new partition is 'partition N', since the ISO's own content
    may already have claimed some of the msdos table's 4 primary slots."""
    new_paths = after - before
    if len(new_paths) != 1:
        raise RuntimeError(
            f"expected exactly one new partition after mkpart, found {len(new_paths)}: {sorted(new_paths)}"
        )
    return new_paths.pop()


def build_mkfs_ext4_command(partition_path: str, label: str = constants.PERSIST_LABEL) -> list[str]:
    return ["mkfs.ext4", "-F", "-L", label, partition_path]


def read_partition_paths(device_path: str) -> set[str]:
    raw = subprocess.run(
        build_lsblk_partitions_command(device_path), capture_output=True, text=True, check=True
    ).stdout
    return parse_lsblk_partition_paths(raw)


def _resolve_new_partition_with_retry(
    device_path: str,
    before: set[str],
    retries: int = constants.PARTITION_DIFF_RETRIES,
    delay_s: float = constants.PARTITION_DIFF_RETRY_DELAY_S,
) -> str:
    """partprobe exiting 0 and `udevadm settle` returning are both about the
    kernel's partition table, not about lsblk's view of it -- the new
    partition's device node can still take another beat to show up. Retries
    the read+diff itself rather than assuming settle's success means the
    node is already visible; see PARTITION_DIFF_RETRIES in constants.py."""
    last_error = None
    for attempt in range(retries):
        after = read_partition_paths(device_path)
        try:
            return resolve_new_partition(before, after)
        except RuntimeError as e:
            last_error = e
            if attempt < retries - 1:
                time.sleep(delay_s)
    raise last_error


def append_persist_partition(device_path: str, start_bytes: int, end_spec: str) -> str:
    """Appends the partition and returns its resolved device path."""
    before = read_partition_paths(device_path)
    try:
        subprocess.run(build_parted_mkpart_command(device_path, start_bytes, end_spec), check=True)
    except subprocess.CalledProcessError:
        # parted's own mkpart can fail with the identical automount-race
        # "unable to inform the kernel ... in use" error partprobe does --
        # and by the time this surfaces, parted has already committed the
        # new table to disk; only the kernel's view is stale. Don't retry
        # mkpart itself: the table write already happened, so running it
        # again would append the same partition entry a second time. Force
        # a reread instead and check whether the partition parted already
        # wrote actually showed up; if it didn't, this wasn't that race and
        # the original failure stands.
        _partprobe_with_retry(device_path)
        if len(read_partition_paths(device_path) - before) != 1:
            raise
    _partprobe_with_retry(device_path)
    subprocess.run(build_udevadm_settle_command(), check=True)
    return _resolve_new_partition_with_retry(device_path, before)


def format_persist_plain(partition_path: str) -> None:
    subprocess.run(build_mkfs_ext4_command(partition_path), check=True)
