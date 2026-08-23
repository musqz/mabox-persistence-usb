# Sources

Design and conventions in this repo are modeled directly on its sibling
project, [mabox-snapshot](https://github.com/musqz/mabox-snapshot) — the tool
that produces the ISOs this tool writes to USB. In particular:

- `ISO_VOLID = "MABOX_LIVE"` (`mabox_persistence_usb/constants.py`) must stay
  in sync with `mabox_snapshot.constants.ISO_VOLID`.
- The `command-builder / thin executor` split (pure `build_*_command()`
  functions, unit-tested; the functions that actually run them via
  `subprocess.run()`, needing root and real hardware, are not unit-tested)
  mirrors `mabox_snapshot/luks.py` and `mabox_snapshot/squashfs.py`.
- The persistence partition design (`MABOX_PERSIST` ext4 label, same-device-
  only boot discovery, always-fresh refresh semantics) originates from
  `mabox-snapshot`'s own approved design spec,
  `docs/superpowers/specs/2026-08-20-persistent-usb-design.md`, carried over
  into this repo's `docs/superpowers/specs/` unchanged for reference.
