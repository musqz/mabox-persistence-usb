# mabox-persistence-usb

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)
![Platform](https://img.shields.io/badge/platform-Mabox%20Linux-2f4f4f.svg)

Write a [mabox-snapshot](https://github.com/musqz/mabox-snapshot) ISO to a USB
stick, with a persistent overlay partition so changes made while running from
the stick survive a reboot. CLI-only, Python, safety-first: it will not touch
a drive unless it is certain that drive is a removable USB disk you have
explicitly identified, confirmed, and (interactively) physically re-verified.

## What it does

- `write <iso>` copies the ISO's raw bytes to a USB device exactly as its own
  hybrid BIOS/UEFI boot layout expects, then appends one more partition —
  `ext4`, labeled `MABOX_PERSIST` — sized to all remaining free space (or
  `--persist-size`) for a writable overlay.
- `--encrypt-persist` LUKS2-encrypts that overlay partition, independently of
  whether the source ISO's own rootfs was built with mabox-snapshot's
  `--encrypt`. The two are unrelated: one protects the ISO's OS payload, the
  other protects what you write to the stick after booting it.
- Every `write` run wipes and rebuilds the whole device — there is no
  preserve-across-runs mode. Re-running `write` *is* the reset mechanism.
- Works with source ISOs up to ~2TiB devices (the ISO's own hybrid layout
  uses a classic MBR partition table, which cannot address more than that).

## Persistence requires a matching mabox-snapshot

The boot-time mechanism that actually mounts `MABOX_PERSIST` as a writable
overlay (`miso_persist`, an initramfs hook) lives in the `mabox-snapshot`
repo, not here, and is not implemented yet. Until it ships, a stick written
by this tool boots exactly like a plain mabox-snapshot ISO and **the
persistence partition is present but unused** — `write` prints an explicit
warning about this every time. See
`docs/superpowers/specs/2026-08-20-persistent-usb-design.md` for the approved
design.

## Installation

Arch/Manjaro-based only (Mabox itself, or any Arch derivative with the same
dependencies).

```sh
git clone https://github.com/musqz/mabox-persistence-usb.git
cd mabox-persistence-usb/packaging
makepkg -si
```

## Quick start

```sh
mabox-persistence-usb doctor                        # check prerequisites, read-only, no root needed
mabox-persistence-usb inspect ./mabox-preserving-23-08-2026-1830.iso
sudo mabox-persistence-usb write ./mabox-preserving-23-08-2026-1830.iso --dry-run
sudo mabox-persistence-usb write ./mabox-preserving-23-08-2026-1830.iso
```

## Usage

Full command reference: `man mabox-persistence-usb`, installed with the
package.

```
usage: mabox-persistence-usb [-h] {version,doctor,devices,inspect,write} ...
```

`write` is the destructive command — it always runs the full device-safety
flow first: enumerate removable USB disks only, disambiguate by insert/
detect if more than one is attached, display full device identification,
require a typed confirmation of the exact device path, then ask you to
physically unplug and reinsert the same stick as a final re-verification
before anything is written. `--device`/`--yes` exist for scripted use but
never bypass the removable-USB-only hard filter, the critical-mount guard, or
the 2TiB size guard — those have no override.
