# Changelog

## 0.2.0

- `--encrypt-persist`: LUKS2-encrypts the `MABOX_PERSIST` overlay partition,
  independently of whether the source ISO's own rootfs was built with
  mabox-snapshot's `--encrypt`. Always prompts interactively for a
  passphrase, even with `--yes` — never via a flag or environment variable.
  Mutually exclusive with `--no-persist`.
- Post-write verification now checks for `TYPE=crypto_LUKS` on an encrypted
  persistence partition instead of its (LUKS-hidden) ext4 label.

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
