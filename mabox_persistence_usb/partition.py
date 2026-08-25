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


def build_parted_print_command(device_path: str) -> list[str]:
    # --machine: colon-delimited, stable across parted versions -- unlike
    # the human tabular format, whose column widths and which trailing
    # columns (File system/Flags) are even present both vary by content,
    # which parted itself documents --machine as the fix for.
    return ["parted", "--machine", "--script", device_path, "unit", "B", "print"]


def parse_parted_partition_starts(raw: str) -> dict[int, int]:
    """Maps partition number -> start offset in bytes, from `parted
    --machine ... unit B print` output. Only Number/Start are parsed here;
    the header lines ('BYT;', the disk-info line) don't start with a
    partition number and are skipped by the isdigit() check rather than by
    position, since machine mode doesn't guarantee a fixed header length
    across parted versions either."""
    starts = {}
    for line in raw.splitlines():
        fields = line.strip().rstrip(";").split(":")
        if len(fields) < 2 or not fields[0].isdigit():
            continue
        starts[int(fields[0])] = int(fields[1].rstrip("B"))
    return starts


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


def _partition_number(mount_device: str, device_path: str) -> int | None:
    """The partition number from a partition's device path (e.g.
    '/dev/sdd1' -> 1, '/dev/nvme0n1p3' -> 3), or None if mount_device isn't
    a partition of device_path -- reuses is_partition_of's own prefix/'p'
    handling rather than duplicating it."""
    if not is_partition_of(mount_device, device_path):
        return None
    return int(mount_device[len(device_path):].lstrip("p"))


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


def build_mkfs_ext4_command(partition_path: str, label: str = constants.PERSIST_LABEL) -> list[str]:
    return ["mkfs.ext4", "-F", "-L", label, partition_path]


def read_partition_paths(device_path: str) -> set[str]:
    raw = subprocess.run(
        build_lsblk_partitions_command(device_path), capture_output=True, text=True, check=True
    ).stdout
    return parse_lsblk_partition_paths(raw)


def resolve_partition_by_start(
    starts: dict[int, int], paths: set[str], device_path: str, start_bytes: int
) -> str | None:
    """Pure matching logic for _find_partition_by_start (see that
    docstring for why matching by position, unbounded above start_bytes,
    is the right approach here). Picks the partition whose start is the
    smallest value >= start_bytes; raises RuntimeError instead of silently
    picking one if more than one qualifies, rather than risk mkfs.ext4
    silently formatting the wrong partition if append_persist_partition's
    documented precondition (device freshly reimaged before this call)
    doesn't actually hold for some future caller."""
    candidates = []
    for path in paths:
        number = _partition_number(path, device_path)
        if number is None:
            continue
        actual_start = starts.get(number)
        if actual_start is not None and actual_start >= start_bytes:
            candidates.append((actual_start, path))
    if not candidates:
        return None
    candidates.sort()
    if len(candidates) > 1:
        raise RuntimeError(
            f"expected at most one partition starting at or after {start_bytes}B on "
            f"{device_path}, found {len(candidates)}: {[path for _, path in candidates]}"
        )
    return candidates[0][1]


def _find_partition_by_start(device_path: str, start_bytes: int) -> str | None:
    """Identifies the partition parted just created by matching the start
    offset it was told to use, instead of diffing partition paths
    before/after the mkpart call. Diffing is fundamentally the wrong tool
    for this: on a repeat write to the same physical stick (this tool's own
    normal, designed-for use case -- see the "always-fresh" refresh
    semantics), parted always assigns MABOX_PERSIST to the same free msdos
    table slot, so it gets the same device path (e.g. /dev/sdd1) as any
    leftover MABOX_PERSIST from a previous run on that stick. A before/after
    path diff can then never see it as "new" -- before and after are
    literally the same path string -- no matter how long it retries,
    reproduced twice in real use (two different ISO sizes, same stick).

    Matches the smallest start >= start_bytes rather than an exact or
    windowed match: --align optimal can nudge the actual start forward from
    the literal start_bytes requested by an amount that depends on the
    device's own reported optimal I/O alignment, not reliably bounded by
    any fixed constant (some USB/SSD media report a larger optimal_io_size
    than PARTITION_ALIGNMENT_BYTES's 1 MiB). Safe to leave the upper end
    unbounded: append_persist_partition's caller always reimages the whole
    device (dd) and forces the kernel/on-disk table back to just the ISO's
    own two entries -- both below start_bytes -- before calling this, so
    nothing else on the disk can legitimately have a start >= start_bytes;
    see append_persist_partition's docstring for that precondition."""
    raw = subprocess.run(
        build_parted_print_command(device_path), capture_output=True, text=True, check=True
    ).stdout
    starts = parse_parted_partition_starts(raw)
    paths = read_partition_paths(device_path)
    return resolve_partition_by_start(starts, paths, device_path, start_bytes)


def _await_partition_by_start(
    device_path: str,
    start_bytes: int,
    retries: int = constants.PARTITION_LOOKUP_RETRIES,
    delay_s: float = constants.PARTITION_LOOKUP_RETRY_DELAY_S,
) -> str | None:
    """partprobe exiting 0 and `udevadm settle` returning are both about the
    kernel's partition table, not about lsblk's/parted's view of it -- the
    new partition can still take another beat to show up in either. Retries
    the lookup itself rather than assuming settle's success means it's
    already visible; see PARTITION_LOOKUP_RETRIES in constants.py.

    Also tolerates _find_partition_by_start's own subprocess calls (parted
    print, lsblk) transiently failing with CalledProcessError -- the same
    "device busy" automount-race class of error partprobe/mkpart are
    already known to hit elsewhere in this module -- rather than letting
    the first such failure abort the whole retry budget. A RuntimeError
    from resolve_partition_by_start (more than one candidate) is not
    caught here and propagates immediately: that's a structural precondition
    violation retrying can't fix, not a transient race."""
    for attempt in range(retries):
        try:
            found = _find_partition_by_start(device_path, start_bytes)
        except subprocess.CalledProcessError:
            found = None
        if found is not None:
            return found
        if attempt < retries - 1:
            time.sleep(delay_s)
    return None


def append_persist_partition(device_path: str, start_bytes: int, end_spec: str) -> str:
    """Appends the partition and returns its resolved device path.

    Precondition: device_path must have just been reimaged (dd) and had
    reread_partition_table() run on it, so the kernel/on-disk table
    reflects only the ISO's own two entries (both below start_bytes) before
    this call's mkpart adds at most one more -- see
    _find_partition_by_start's docstring for why that's load-bearing for
    correctly identifying the new partition. Calling this a second time on
    a device that already has a partition at or past start_bytes (i.e.
    without reimaging in between) will resolve to that pre-existing
    partition instead of surfacing an error."""
    mkpart_error = None
    try:
        subprocess.run(build_parted_mkpart_command(device_path, start_bytes, end_spec), check=True)
    except subprocess.CalledProcessError as exc:
        # parted's own mkpart can fail with the identical automount-race
        # "unable to inform the kernel ... in use" error partprobe does --
        # and by the time this surfaces, parted has already committed the
        # new table to disk; only the kernel's view is stale. Don't retry
        # mkpart itself: the table write already happened, so running it
        # again would append the same partition entry a second time.
        # Fall through to the same by-start lookup as the success path
        # below; only re-raise this if that lookup comes up empty too.
        mkpart_error = exc
    _partprobe_with_retry(device_path)
    subprocess.run(build_udevadm_settle_command(), check=True)
    new_partition = _await_partition_by_start(device_path, start_bytes)
    if new_partition is None:
        if mkpart_error is not None:
            raise mkpart_error
        raise RuntimeError(
            f"expected a new partition starting at {start_bytes}B on {device_path}, found none"
        )
    return new_partition


def format_persist_plain(partition_path: str) -> None:
    subprocess.run(build_mkfs_ext4_command(partition_path), check=True)
