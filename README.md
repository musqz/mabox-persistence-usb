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
  `ext4`, labeled `MABOX_PERSIST` — sized to all remaining free space, for a
  writable overlay.
- Every `write` run wipes and rebuilds the whole device — there is no
  preserve-across-runs mode. Re-running `write` *is* the reset mechanism.
- Works with source ISOs up to ~2TiB devices (the ISO's own hybrid layout
  uses a classic MBR partition table, which cannot address more than that).

## Persistence requires a matching mabox-snapshot

The boot-time mechanism that actually mounts `MABOX_PERSIST` as a writable
overlay (`miso_persist`, an initramfs hook) lives in the `mabox-snapshot`
repo, not here. As of mabox-snapshot 0.2.6, plain persistence has been
verified end-to-end on real hardware: build, write, boot, and changes
survive a reboot. `write` checks each ISO for a `mabox/.persist-hook-version`
marker before creating `MABOX_PERSIST`: an ISO built by a mabox-snapshot
older than 0.2.6 (marker version 1) is refused by default -- its persistence
never actually mounted at boot, due to two bugs fixed in 0.2.6 (a
boot-device-resolution bug and a partition-table-overwrite bug). `--force`
to create the partition anyway, or `--no-persist` for a plain
non-persistent stick. See
`docs/superpowers/specs/2026-08-20-persistent-usb-design.md` for the design.

## Choosing a USB stick

Persistence performance depends far more on the stick's **random 4K write**
speed than on its advertised sequential MB/s. A cheap, phone-transfer-oriented
drive (independently measured at ~0.01 MB/s random write) made a live session
unusably slow even though the tool itself was working correctly — every write
during the session (and every file overlayfs has to copy up before it can
modify it) goes through the stick, so weak random-write performance shows up
as constant, pervasive lag, not just a slow boot.

Before trusting a stick for persistent use, look for one with published
random-write numbers (not just sequential), or check an independent benchmark
site — sequential-only marketing specs hide exactly this weakness. Dual-connector
"OTG"/phone-transfer drives are usually the worst offenders; a dedicated USB
3.x flash drive built for general storage is a safer bet.

## Installation

### Mabox Linux Only

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
