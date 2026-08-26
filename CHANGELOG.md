# Changelog

## 0.2.8

- Removed `--encrypt-persist` and `--persist-size`. Neither had a consumer:
  no shipped or merged mabox-snapshot has a `miso_persist` LUKS-unlock
  branch, so an encrypted `MABOX_PERSIST` was never usable at boot, and
  `--persist-size` had no real-world need over the default (all remaining
  space). `MABOX_PERSIST` is now always plain `ext4`, sized to all
  remaining space. `persist_luks.py`, `verify.verify_persist_luks()`, and
  the encrypted-hook-support check are gone with it. ISO inspection still
  reports the source ISO's own rootfs encryption status (`inspect`,
  informational only, unrelated to this).

## 0.2.7

- Cleanup pass ahead of external review: fixed docs that still described
  persistence as unverified/pending after 0.2.6 shipped it confirmed
  working on real hardware (design spec, `isoinspect.py`, a
  self-contradicting comment in `constants.py`, the man page), removed an
  accidentally-committed stale 0.2.5 release tarball from git, removed an
  unused import, and added a "Choosing a USB stick" README section. No
  behavior changes.

## 0.2.6

- `write` now requires marker version 2 (`MIN_SUPPORTED_HOOK_VERSION`), not
  1, to create a plain `MABOX_PERSIST` partition -- and version 3
  (`MIN_SUPPORTED_ENCRYPTED_HOOK_VERSION`) for `--encrypt-persist`. Version 1
  ISOs are refused by default, not because anything changed here, but
  because their persistence never actually worked at boot: mabox-snapshot
  0.2.6 fixed the underlying `_find_dev_by_path()` boot-device-resolution
  bug and a partition-table-overwrite bug that both silently broke every
  `MABOX_PERSIST` write against earlier ISOs. Confirmed end-to-end on real
  hardware this session: build a v2-marked ISO, `write` it, boot it,
  persistence survives a reboot. `--force`/`--no-persist` still work as
  before for anyone who wants to override the check.

## 0.2.5

- Fixed `write` still failing on `partprobe`'s "unable to inform the kernel
  of the change ... probably because it/they are in use" even with 0.2.4's
  retry loop, and even after a reboot. The actual cause: a desktop
  automount daemon (udisks2/gvfs) re-mounts the drive the instant `dd`
  makes its filesystem label (e.g. `MABOX_LIVE`) reappear, so it can keep
  winning the race no matter how long the retry loop waits -- and comes
  right back after a reboot too. Each retry now actively unmounts whatever
  reappeared, and closes a lingering `--encrypt-persist` LUKS mapper left
  open from a previous run on the same stick. `parted`'s own `mkpart` call,
  which could hit the identical error with no retry protection at all, is
  now covered too.

## 0.2.4

- Fixed `write` occasionally crashing with parted's "unable to inform the
  kernel of the change ... probably because it/they are in use" from our
  own `partprobe` call right after the `dd` write -- most likely a desktop
  automount daemon (udisks2/gvfs) racing to probe the device the instant
  `dd` closes it. `partprobe` is now retried a few times with a short
  delay at both call sites, and the post-`dd` partition-table reread
  settles udev before its own `partprobe` too, not just after.

## 0.2.3

- `write` now prints an intro (what it does, and that the target drive
  will be completely erased) below the banner before device detection
  starts, and the "Attach the target USB drive now" prompt renders bold
  bright-yellow on a tty so it stands out from surrounding status lines.

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
