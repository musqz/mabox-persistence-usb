# Changelog

## 0.2.2

- Fixed `write` crashing with an unhandled `parted` error ("unable to
  inform the kernel of the change ... probably because it/they are in
  use") when appending `MABOX_PERSIST` to a device that still held a
  previous run's stale partition table in the kernel's live view. The
  device's partition table is now re-read (`partprobe` + `udevadm
  settle`) immediately after the `dd` write, before anything else
  touches it.
- Added a "Detecting attached USB drives ..." status message around each
  USB scan in `write` (the underlying `lsblk`/`udevadm` calls previously
  ran silently), an upfront "Attach the target USB drive now" prompt
  before detection starts, and a colored ASCII welcome banner shown
  before every subcommand (plain text when stdout isn't a tty).

## 0.2.1

- Fixed a post-write verification bug: the ISO byte-range checksum was
  re-hashed after `parted` appended the `MABOX_PERSIST` partition, which
  rewrites the ISO's own embedded MBR partition table inside that same byte
  range -- so `write` reported `verification failed` on every default write
  (persistence enabled) with a `.sha256` sidecar next to the ISO, even
  though the write itself was correct. The checksum is now hashed
  immediately after the `dd` write, before partitioning touches the MBR.

## 0.2.0

- `--encrypt-persist`: LUKS2-encrypts the `MABOX_PERSIST` overlay partition,
  independently of whether the source ISO's own rootfs was built with
  mabox-snapshot's `--encrypt`. Always prompts interactively for a
  passphrase, even with `--yes` — never via a flag or environment variable.
  Mutually exclusive with `--no-persist`.
- Post-write verification now checks for `TYPE=crypto_LUKS` on an encrypted
  persistence partition instead of its (LUKS-hidden) ext4 label.
- Persistence boot-hook support is now a real pre-flight gate on `write`:
  mabox-snapshot's `miso_persist` hook and `mabox/.persist-hook-version`
  marker merged upstream (mabox-snapshot#61) — `write` refuses to create
  `MABOX_PERSIST` by default on an ISO that doesn't advertise support
  (`--force` to override, `--no-persist` to skip persistence entirely).
  `--encrypt-persist` is gated separately and more strictly: the merged
  `miso_persist` hook has no LUKS-unlock branch yet, so it's refused by
  default regardless of which mabox-snapshot built the ISO, until one ships.
- `inspect` now reports plain and encrypted persistence-hook support
  separately.

## 0.1.0

- Initial release: `write` a mabox-snapshot ISO to a removable USB disk with
  a persistent `MABOX_PERSIST` ext4 overlay partition.
- Device-safety flow: hard removable-USB-only filter, critical-mount guard,
  2TiB MBR size guard, insert/detect disambiguation, typed confirmation,
  physical remove-and-reinsert re-verification.
- `doctor`, `devices list`, and `inspect` read-only commands.
- Persistence boot-hook support detection is not yet implemented — see
  `docs/superpowers/specs/2026-08-20-persistent-usb-design.md` and the
  project README for the current status of the `mabox-snapshot` side of
  this feature.
