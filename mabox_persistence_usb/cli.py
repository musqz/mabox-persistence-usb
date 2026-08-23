"""argparse dispatch for the mabox-persistence-usb CLI."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from . import __version__, constants, device, isoinspect, partition, persist_luks, privilege, safety, verify, writer


def cmd_version(_args: argparse.Namespace) -> int:
    print(f"mabox-persistence-usb {__version__}")
    return 0


def cmd_doctor(_args: argparse.Namespace) -> int:
    ok = True
    for tool in constants.REQUIRED_TOOLS:
        if shutil.which(tool):
            print(f"[ok]   {tool} found")
        else:
            print(f"[fail] {tool} not found")
            ok = False
    for tool in constants.OPTIONAL_TOOLS:
        if shutil.which(tool):
            print(f"[ok]   {tool} found (optional)")
        else:
            print(f"[warn] {tool} not found (optional, needed for --encrypt-persist)")

    try:
        disks = device.list_removable_usb_disks()
        print(f"[info] {len(disks)} removable USB disk(s) currently attached")
    except Exception as e:  # lsblk/udevadm missing or failing -- already reported as [fail] above if missing
        print(f"[warn] could not enumerate removable USB disks: {e}")

    return 0 if ok else 1


def cmd_devices_list(_args: argparse.Namespace) -> int:
    disks = device.list_removable_usb_disks()
    if not disks:
        print("no removable USB disks currently attached")
        return 0
    for disk in disks:
        print(safety.format_identification_block(disk))
        print()
    return 0


def cmd_inspect(args: argparse.Namespace) -> int:
    iso_path: Path = args.iso
    if not iso_path.exists():
        print(f"error: {iso_path} does not exist", file=sys.stderr)
        return 1

    report = isoinspect.inspect_iso(iso_path)
    print(f"path:             {report.path}")
    match_note = "matches" if report.volume_id_ok else "DOES NOT MATCH"
    print(f"volume id:        {report.volume_id!r} ({match_note} {constants.ISO_VOLID!r})")
    if report.filename_info.mode:
        print(f"filename:         mode={report.filename_info.mode} built={report.filename_info.stamp}")
    else:
        print("filename:         not the default mabox-snapshot naming pattern (built with --iso-name)")
    if report.rootfs_encrypted is True:
        print("rootfs:           LUKS2-encrypted (rootfs.sfs.luks) -- irrelevant to how this tool writes bytes")
    elif report.rootfs_encrypted is False:
        print("rootfs:           plain (rootfs.sfs)")
    else:
        print("rootfs:           unknown -- neither rootfs.sfs nor rootfs.sfs.luks found")
    if report.checksum_path:
        print(f"checksum:         {report.checksum_path} ({'OK' if report.checksum_ok else 'MISMATCH'})")
    else:
        print("checksum:         no .sha256 sidecar found alongside the ISO")
    print(
        f"persistence hook: {report.hook_support.value} -- mabox-snapshot has not shipped "
        f"miso_persist support yet as of this tool's {__version__}"
    )
    return 0


def _resolve_target_device(args: argparse.Namespace) -> device.UsbDisk:
    if args.device:
        eligible = device.list_removable_usb_disks()
        return safety.resolve_explicit_device(args.device, eligible)
    if args.yes:
        eligible = device.list_removable_usb_disks()
        if len(eligible) != 1:
            raise safety.AmbiguousDeviceError(
                f"--yes without --device requires exactly one removable USB disk attached "
                f"(found {len(eligible)}) -- pass --device explicitly"
            )
        return eligible[0]
    return safety.enumerate_and_disambiguate(device.list_removable_usb_disks)


def cmd_write(args: argparse.Namespace) -> int:
    try:
        return _cmd_write(args)
    except EOFError:
        print(
            "error: no interactive terminal available to confirm this destructive operation "
            "-- use --yes together with --device for scripted/non-interactive use",
            file=sys.stderr,
        )
        return 1


def _cmd_write(args: argparse.Namespace) -> int:
    iso_path: Path = args.iso
    if not iso_path.exists():
        print(f"error: {iso_path} does not exist", file=sys.stderr)
        return 1

    report = isoinspect.inspect_iso(iso_path)
    if not report.volume_id_ok and not args.force:
        print(
            f"error: {iso_path} has volume id {report.volume_id!r}, expected {constants.ISO_VOLID!r} "
            f"-- this does not look like a mabox-snapshot ISO. Pass --force to write it anyway.",
            file=sys.stderr,
        )
        return 1
    if report.checksum_path and not report.checksum_ok:
        print(
            f"error: {iso_path} does not match its checksum at {report.checksum_path} -- "
            f"the source ISO may be corrupt. Not bypassable by --force.",
            file=sys.stderr,
        )
        return 1

    try:
        disk = _resolve_target_device(args)
    except (safety.AbortedError, safety.NoDeviceFoundError, safety.AmbiguousDeviceError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except safety.UnsafeDeviceError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    mounts_raw = constants.PROC_MOUNTS_FILE.read_text()
    swaps_raw = constants.PROC_SWAPS_FILE.read_text() if constants.PROC_SWAPS_FILE.exists() else "Filename\n"
    try:
        safety.check_guards(disk, mounts_raw, swaps_raw)
    except safety.UnsafeDeviceError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    print(safety.format_identification_block(disk))

    iso_size_bytes = iso_path.stat().st_size
    start = partition.compute_partition_start(iso_size_bytes)
    try:
        persist_size_bytes = partition.compute_persist_size_bytes(args.persist_size) if args.persist_size else None
        end_spec = None if args.no_persist else partition.compute_partition_end_spec(start, persist_size_bytes, disk.size_bytes)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    if args.dry_run:
        print(f"plan:    dd {iso_path} -> {disk.path}")
        print(f"plan:    {' '.join(writer.build_dd_write_command(iso_path, disk.path))}")
        if not args.no_persist:
            print(f"plan:    {' '.join(partition.build_parted_mkpart_command(disk.path, start, end_spec))}")
            if args.encrypt_persist:
                print("plan:    cryptsetup luksFormat + open (passphrase prompted interactively) on the newly appended partition")
                print(f"plan:    mkfs.ext4 (label={constants.PERSIST_LABEL}) on /dev/mapper/{constants.PERSIST_LUKS_MAPPER_NAME}")
            else:
                print(f"plan:    mkfs.ext4 (label={constants.PERSIST_LABEL}) on the newly appended partition")
        else:
            print("plan:    --no-persist -- no overlay partition will be created")
        return 0

    if not args.no_persist:
        hook_note = (
            " mabox-snapshot's miso_persist LUKS-unlock branch does not exist yet either."
            if args.encrypt_persist else ""
        )
        print(
            "warning: persistence boot-hook support cannot be verified yet -- mabox-snapshot "
            "does not ship the miso_persist hook as of this tool's "
            f"{__version__}. MABOX_PERSIST will be created, but the stick will boot exactly "
            f"like a plain ISO until mabox-snapshot adds hook support.{hook_note}"
        )

    if any(p.mountpoints for p in disk.partitions):
        if args.yes:
            if not args.force_unmount:
                print(
                    "error: target has mounted partitions -- pass --force-unmount to "
                    "auto-unmount in --yes mode",
                    file=sys.stderr,
                )
                return 1
        else:
            if not safety.confirm_unmount(disk):
                print("error: aborted (mounted partitions not unmounted)", file=sys.stderr)
                return 1
        for part in disk.partitions:
            for mountpoint in part.mountpoints:
                device.unmount_partition(mountpoint)

    if not args.yes:
        if not safety.confirm_typed(disk.path):
            print("error: confirmation did not match -- aborting", file=sys.stderr)
            return 1
        if not args.skip_reinsert_check:
            try:
                disk = safety.wait_for_reinsert(disk, device.list_removable_usb_disks)
            except safety.ReinsertTimeoutError as e:
                print(f"error: {e}", file=sys.stderr)
                return 1

    safety.countdown()

    try:
        privilege.require_root("mabox-persistence-usb write")
    except privilege.NotRootError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    passphrase = None
    if args.encrypt_persist:
        try:
            passphrase = persist_luks.prompt_for_passphrase()
        except RuntimeError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1

    print(f"writing {iso_path} to {disk.path} ...")
    writer.write_iso_to_device(iso_path, disk.path)

    new_partition = None
    if not args.no_persist:
        print("appending MABOX_PERSIST partition ...")
        new_partition = partition.append_persist_partition(disk.path, start, end_spec)
        if args.encrypt_persist:
            persist_luks.format_persist_encrypted(new_partition, passphrase)
        else:
            partition.format_persist_plain(new_partition)

    print(f"done: {disk.path} written")

    if not args.no_verify:
        print("verifying ...")
        problems = []
        if new_partition:
            if args.encrypt_persist:
                if not verify.verify_persist_luks(new_partition):
                    problems.append(f"{new_partition} does not report TYPE=crypto_LUKS")
            elif not verify.verify_persist_label(new_partition, constants.PERSIST_LABEL):
                problems.append(f"{new_partition} does not report label {constants.PERSIST_LABEL}")
        if report.checksum_path:
            expected = isoinspect.read_expected_checksum(report.checksum_path)
            actual = verify.hash_device_prefix(disk.path, iso_size_bytes)
            if actual.lower() != expected:
                problems.append("device's ISO byte range does not match the source checksum")
        if problems:
            for problem in problems:
                print(f"error: verification failed -- {problem}", file=sys.stderr)
            return 3
        print("verification passed")

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mabox-persistence-usb")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("version", help="Print the version").set_defaults(func=cmd_version)
    sub.add_parser("doctor", help="Check prerequisites, read-only").set_defaults(func=cmd_doctor)

    devices_parser = sub.add_parser("devices", help="Inspect currently-attached removable USB disks")
    devices_sub = devices_parser.add_subparsers(dest="devices_command", required=True)
    devices_sub.add_parser("list", help="List removable USB disks, read-only, no root").set_defaults(func=cmd_devices_list)

    inspect_parser = sub.add_parser(
        "inspect", help="Validate a mabox-snapshot ISO before writing it, read-only, no root"
    )
    inspect_parser.add_argument("iso", type=Path, help="Path to the ISO file")
    inspect_parser.set_defaults(func=cmd_inspect)

    write_parser = sub.add_parser(
        "write",
        help="Write an ISO to a USB disk with a persistent overlay partition (root required)",
        description="Write a mabox-snapshot ISO to a USB device plus a MABOX_PERSIST overlay partition.",
        epilog=(
            "example:\n"
            "  sudo mabox-persistence-usb write ./mabox-preserving-23-08-2026-1830.iso --dry-run\n"
            "  sudo mabox-persistence-usb write ./mabox-preserving-23-08-2026-1830.iso\n"
            "  sudo mabox-persistence-usb write ./mabox-preserving-23-08-2026-1830.iso --encrypt-persist\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    write_parser.add_argument("iso", type=Path, help="Path to the ISO file")
    write_parser.add_argument(
        "--device", help="Target disk explicitly (e.g. /dev/sdb) instead of the interactive insert/detect flow"
    )
    write_parser.add_argument(
        "-y", "--yes", action="store_true",
        help="Non-interactive: skip typed confirmation and physical reinsert re-verification "
             "(the removable-USB-only filter and both safety guards still apply, always)",
    )
    write_parser.add_argument(
        "--force-unmount", action="store_true",
        help="With --yes, auto-unmount mounted partitions on the target instead of erroring",
    )
    write_parser.add_argument(
        "--persist-size",
        help="Cap the MABOX_PERSIST partition instead of using all remaining space (e.g. 50GiB)",
    )
    persist_group = write_parser.add_mutually_exclusive_group()
    persist_group.add_argument(
        "--no-persist", action="store_true",
        help="Write only the raw ISO bytes, skip creating MABOX_PERSIST entirely",
    )
    persist_group.add_argument(
        "--encrypt-persist", action="store_true",
        help="LUKS2-encrypt the MABOX_PERSIST partition, independently of whether the source "
             "ISO's own rootfs is encrypted. Always prompts interactively for a passphrase, "
             "even with --yes -- never via a flag or environment variable.",
    )
    write_parser.add_argument(
        "--force", action="store_true",
        help="Bypass the ISO volume-id soft check. Never bypasses the removable/USB filter, "
             "critical-mount guard, or the 2TiB size guard.",
    )
    write_parser.add_argument(
        "--skip-reinsert-check", action="store_true",
        help="Interactive-mode-only: skip the physical unplug/replug re-verification (e.g. VM testing)",
    )
    write_parser.add_argument(
        "--no-verify", action="store_true", help="Skip the post-write verification pass"
    )
    write_parser.add_argument(
        "--dry-run", action="store_true",
        help="Resolve and print the plan and every command that would run; touch nothing",
    )
    write_parser.set_defaults(func=cmd_write)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
