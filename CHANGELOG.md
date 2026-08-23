# Changelog

## 0.1.0

- Initial release: `write` a mabox-snapshot ISO to a removable USB disk with
  a persistent `MABOX_PERSIST` ext4 overlay partition, optionally LUKS2
  encrypted (`--encrypt-persist`).
- Device-safety flow: hard removable-USB-only filter, critical-mount guard,
  2TiB MBR size guard, insert/detect disambiguation, typed confirmation,
  physical remove-and-reinsert re-verification.
- `doctor`, `devices list`, and `inspect` read-only commands.
- Persistence boot-hook support detection is not yet implemented — see
  `docs/superpowers/specs/2026-08-20-persistent-usb-design.md` and the
  project README for the current status of the `mabox-snapshot` side of
  this feature.
