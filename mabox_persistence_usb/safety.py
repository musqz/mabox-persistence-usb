"""Device-selection safety flow -- the centerpiece of this tool. Every
destructive `write` run passes through this module before touching a
device. All I/O (candidate listing, prompting, polling, sleeping) is
injectable so the flow's *logic* is unit-testable without real hardware.

Two classes of failure are deliberately distinct: UnsafeDeviceError marks
the hard, non-bypassable safety filter/guards (maps to CLI exit code 2);
AbortedError/NoDeviceFoundError/ReinsertTimeoutError mark ordinary
user-facing failures (exit code 1)."""

from __future__ import annotations

import time

from . import constants, device


class AbortedError(RuntimeError):
    """User declined a confirmation or explicitly aborted."""


class UnsafeDeviceError(RuntimeError):
    """A hard safety filter or guard rejected the device. Never bypassable
    by any flag, interactive or scripted."""


class NoDeviceFoundError(RuntimeError):
    pass


class AmbiguousDeviceError(RuntimeError):
    """--yes was given without --device and more (or less) than one
    removable USB disk is attached -- a usage error, not the user aborting."""


class ReinsertTimeoutError(RuntimeError):
    pass


def resolve_explicit_device(requested_path: str, eligible_disks: list[device.UsbDisk]) -> device.UsbDisk:
    """--device escape hatch: still must be among the hard-filtered eligible
    set (removable + USB) -- never trusted blindly, interactive or not."""
    disk = device.get_disk_by_path(requested_path, eligible_disks)
    if disk is None:
        raise UnsafeDeviceError(
            f"{requested_path} is not a removable USB disk (or is not currently attached) "
            f"-- refusing. Run 'mabox-persistence-usb devices list' to see eligible disks."
        )
    return disk


def check_guards(disk: device.UsbDisk, mounts_raw: str, swaps_raw: str) -> None:
    """The two unconditional guards that run immediately after the hard
    filter, before the device is ever displayed to the user. Raises
    UnsafeDeviceError -- never a soft warning, never bypassable."""
    if not device.fits_in_mbr(disk.size_bytes):
        raise UnsafeDeviceError(
            f"{disk.path} is {disk.size_bytes} bytes, at or beyond the 2TiB MBR limit "
            f"({constants.MAX_MBR_DEVICE_BYTES} bytes) -- refusing (see README's "
            f"'~2TiB devices' limitation)."
        )
    mounts = device.parse_proc_mounts(mounts_raw)
    swaps = device.parse_proc_swaps(swaps_raw)
    if device.is_hosting_critical_mount(disk.path, mounts, swaps):
        raise UnsafeDeviceError(
            f"{disk.path} hosts a critical mountpoint (/, /boot, /home, /var) or active "
            f"swap -- refusing to treat it as a removable target."
        )


def format_size(size_bytes: int) -> str:
    size = float(size_bytes)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024:
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TiB"


def format_identification_block(disk: device.UsbDisk) -> str:
    lines = [
        f"device:  {disk.path}",
        f"size:    {disk.size_bytes} bytes ({format_size(disk.size_bytes)})",
        f"vendor:  {disk.vendor or '(unknown)'}",
        f"model:   {disk.model or '(unknown)'}",
        f"serial:  {disk.serial or '(unknown -- reinsert re-verification will use a weaker fingerprint)'}",
        f"bus:     {disk.tran or '(unknown)'}",
    ]
    if disk.partitions:
        lines.append("existing partitions:")
        for part in disk.partitions:
            mp = ", ".join(part.mountpoints) if part.mountpoints else "(not mounted)"
            lines.append(
                f"  {part.path}: {part.fstype or '(no filesystem)'} "
                f"label={part.label or '(none)'} mounted at {mp}"
            )
    else:
        lines.append("existing partitions: none")
    return "\n".join(lines)


def enumerate_and_disambiguate(list_candidates, input_fn=input, print_fn=print, max_rescans=10000) -> device.UsbDisk:
    """Interactive insert/detect + disambiguation loop. Never assumes the
    user already knows a /dev/sdX name -- zero candidates means "plug it in
    and press Enter", not a hard failure."""
    for _ in range(max_rescans):
        print_fn("Detecting attached USB drives ...")
        candidates = list_candidates()
        if not candidates:
            print_fn("No removable USB disk detected.")
            answer = input_fn("Insert the target USB drive, then press Enter to rescan (q to abort): ")
            if answer.strip().lower() == "q":
                raise AbortedError("aborted while waiting for a USB drive to be inserted")
            continue
        if len(candidates) == 1:
            return candidates[0]
        print_fn(f"{len(candidates)} removable USB disks found:")
        for i, disk in enumerate(candidates, start=1):
            print_fn(
                f"  [{i}] {disk.path}  {format_size(disk.size_bytes)}  "
                f"{disk.vendor or ''} {disk.model or ''}  serial={disk.serial or '?'}"
            )
        answer = input_fn("Select a number, or press Enter to rescan (q to abort): ").strip()
        if answer.lower() == "q":
            raise AbortedError("aborted while disambiguating multiple USB drives")
        if not answer:
            continue
        if answer.isdigit() and 1 <= int(answer) <= len(candidates):
            return candidates[int(answer) - 1]
        print_fn("Not a valid selection.")
    raise NoDeviceFoundError("gave up after too many rescans")


def confirm_typed(expected_path: str, input_fn=input, print_fn=print) -> bool:
    """One shot, no retry loop -- unlike a passphrase prompt, a destructive
    confirmation shouldn't invite 'try again until you get it right'."""
    print_fn(f"About to irreversibly erase {expected_path}.")
    typed = input_fn(f"Type the device path exactly ({expected_path}) to confirm: ")
    return typed.strip() == expected_path


def confirm_unmount(disk: device.UsbDisk, input_fn=input, print_fn=print) -> bool:
    mounted = [p for p in disk.partitions if p.mountpoints]
    print_fn("The following partitions are currently mounted:")
    for p in mounted:
        print_fn(f"  {p.path} at {', '.join(p.mountpoints)}")
    answer = input_fn("Unmount them and continue? [y/N]: ").strip().lower()
    return answer == "y"


def wait_for_reinsert(
    disk: device.UsbDisk,
    list_candidates,
    sleep_fn=time.sleep,
    print_fn=print,
    disappear_timeout: float = constants.REINSERT_DISAPPEAR_TIMEOUT_S,
    reappear_timeout: float = constants.REINSERT_REAPPEAR_TIMEOUT_S,
    poll_interval: float = constants.REINSERT_POLL_INTERVAL_S,
) -> device.UsbDisk:
    """Instructs a physical unplug/replug and re-identifies the SAME device
    afterward by matching on USB serial (never on /dev/sdX, which can
    renumber on replug). Falls back to vendor+model+size, with an explicit
    reduced-confidence warning, when the device reports no serial."""

    def _matches(candidate: device.UsbDisk) -> bool:
        if disk.serial:
            return candidate.serial == disk.serial
        return (
            candidate.vendor == disk.vendor
            and candidate.model == disk.model
            and candidate.size_bytes == disk.size_bytes
        )

    if not disk.serial:
        print_fn(
            "warning: this device reports no serial number -- reinsert re-verification "
            "will match on vendor+model+size only, a weaker fingerprint."
        )

    print_fn(f"Physically unplug {disk.path} now, then plug it back in.")

    elapsed = 0.0
    while any(_matches(c) for c in list_candidates()):
        if elapsed >= disappear_timeout:
            raise ReinsertTimeoutError(f"{disk.path} was not unplugged within {disappear_timeout:.0f}s")
        sleep_fn(poll_interval)
        elapsed += poll_interval

    elapsed = 0.0
    while True:
        matches = [c for c in list_candidates() if _matches(c)]
        if matches:
            return matches[0]
        if elapsed >= reappear_timeout:
            raise ReinsertTimeoutError("the same device did not reappear within " f"{reappear_timeout:.0f}s")
        sleep_fn(poll_interval)
        elapsed += poll_interval


def countdown(seconds: int = constants.PRE_WRITE_COUNTDOWN_S, sleep_fn=time.sleep, print_fn=print) -> None:
    for remaining in range(seconds, 0, -1):
        print_fn(f"Writing in {remaining}... (Ctrl-C to abort)")
        sleep_fn(1)
