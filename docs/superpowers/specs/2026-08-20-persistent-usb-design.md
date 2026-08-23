# Persistent USB write — design spec

## Status

Design approved by user 2026-08-20. Not yet implemented. Supersedes the
mount-detection-related open questions in the earlier brainstorm memory
(`project-persistent-usb-brainstorm`) — see "Decisions" below for what changed
and what's newly resolved.

## Problem

`mabox-snapshot create` only ever produces a `.iso` file. The user wants a
`mabox-snapshot usb write` command that can turn a built ISO into a **persistent**
live USB stick: one that behaves like a normal, everyday bootable system rather
than a one-shot live/install medium — package updates, new files, settings
changes made while running from the stick should survive a reboot.

## Scope

In scope: writing the ISO plus a persistence overlay onto a user-selected USB
device, and the boot-time mechanism that makes changes on that overlay persist.
Out of scope (deliberately, per prior brainstorming): a shared/exchange FAT32
partition, Ventoy-style multi-ISO layouts, any partition-content beyond the ISO's
own boot content plus the one overlay partition.

This design **reuses, unchanged**, the device-selection safety flow from a
separately-planned `usb write` feature (insert-detect / confirm / physically
remove-and-reinsert-to-reverify / hard removable-only filter / final typed
confirmation) — see that plan for the full design of `usb.py`'s detection layer.
This spec only covers what's specific to persistence: the partition layout added
on top of a plain write, and the new boot-time mount mechanism.

## Decisions

Confirmed with the user this session, resolving every open question left in the
earlier brainstorm:

1. **Overlay discovery scope — same device only.** The boot-time hook only ever
   looks at the disk it booted from, never scans other attached storage by label.
   Structurally impossible for boot to touch a different stick's persistence data,
   even if multiple mabox USB sticks are plugged in at once. (Rejected alternative:
   scanning any attached device by label/UUID — reintroduces the same
   multiple-candidates ambiguity problem the write-time safety flow exists to
   avoid, just at boot time instead.)

2. **Overlay identification — fixed filesystem label, not partition number or GPT
   type GUID.** The overlay partition is formatted `ext4` with label `MABOX_PERSIST`
   at write time; the boot hook mounts by `LABEL=MABOX_PERSIST`. A fixed partition
   number was rejected: the ISO's own hybrid boot layout already claims specific
   partition-table entries for its BIOS/EFI boot scheme (see the existing
   `xorriso ... -append_partition 2 0xef ...` assemble step), so "the overlay is
   always partition N" can't be safely assumed. The label survives regardless of
   exactly which slot `usb write` ends up using when it appends the new partition.

3. **Refresh behavior — always fresh, no preservation.** Every `usb write` run
   wipes and rebuilds the whole device unconditionally: base image partitions plus
   a brand-new, empty `MABOX_PERSIST` partition. No detection of a pre-existing
   overlay, no preserve-and-refresh-only-the-base code path. This was a reversal
   mid-session from an initial "preserve the overlay across refreshes" answer —
   the user reconsidered once it was clear the tool can always rebuild a USB stick
   from scratch cheaply, and preferred the simpler one-code-path tool over
   preservation logic.

4. **Overlay growth policy — no cap, no warning mechanism, resolved as moot by
   decision 3.** The overlay still grows unbounded *between* refreshes (every
   package update/cache/log write accumulates in `upper/` across however many
   boots happen before the next `usb write` run) — but there's no need for a
   capacity-warning subsystem, because re-running `usb write` is already the
   reset/reclaim-space mechanism, by design, per decision 3. Nothing separate to
   build here.

## Partition layout

Written by `usb write` (extends the already-planned plain-write path): the ISO's
own hybrid content is written first, exactly as it is for a plain (non-persistent)
write today — its existing BIOS/EFI partition-table entries are untouched. After
that, `usb write` appends one new partition covering all remaining free space on
the device: `ext4`, label `MABOX_PERSIST`. No specific partition number is assumed
anywhere in this design (see decision 2) — "the next available slot, sized to
whatever's left after the ISO's own content."

## Boot-time mechanism

New initramfs hook, `miso_persist` (`configs/initcpio/hooks/miso_persist`,
`configs/initcpio/install/miso_persist`), modeled directly on the existing custom
`miso_luks` hook's own structure and conventions (same class of problem: do
something to the live boot device before `switch_root` that the stock `miso` hook
doesn't know how to do).

Runs immediately after `miso`/`miso_luks` finish mounting the read-only squashfs
base, before `switch_root`:

1. Determine the boot device — reuses whatever mechanism `miso_luks` already uses
   to identify its own device (same-device constraint, decision 1).
2. Look for a partition labeled `MABOX_PERSIST` on that device, via
   `/dev/disk/by-label/MABOX_PERSIST` (once udev has settled) with a direct
   `blkid` scan as a fallback.
3. **Not found** → no-op. Boot proceeds exactly as it does today, read-only
   squashfs root. This is what happens for a plain non-persistent stick, or any
   ISO booted directly (e.g. in QEMU, as tested this session) — persistence is
   strictly additive, never a hard requirement.
4. **Found** → mount it read-write at a scratch path (e.g.
   `/run/mabox-snapshot/persist`); create `upper/` and `work/` subdirectories
   inside it if they don't already exist (idempotent — always true on a
   freshly-written "always fresh" stick, but safe if ever re-run); mount an
   overlayfs merging the read-only squashfs (`lowerdir`) with `persist/upper`
   (`upperdir`) and `persist/work` (`workdir`) at the path the boot process
   expects as root.
5. Everything downstream — Calamares (if run live), the desktop session, package
   installs — runs against this writable merged view. Writes land in `upper/` on
   the `ext4` partition and survive reboot.

### Error handling

- No `MABOX_PERSIST` partition found → silent no-op (step 3 above), never a hard
  boot failure over a missing optional feature.
- `MABOX_PERSIST` partition found but broken (e.g. corrupt filesystem, overlay
  mount fails) → fall back to a read-only boot with a visible warning, rather than
  stranding the user at an initramfs shell. Recommended mechanism: reuse
  `miso_luks`'s existing `plymouth`-message pattern (already proven this session)
  for surfacing the warning if `plymouth` is running, plain stderr otherwise. A
  working non-persistent boot beats no boot at all.

## Testing

Same precedent as `miso_luks`: the shell hook itself is real-hardware/real-boot
territory, not unit-testable in `tests/unit/` (confirmed — `miso_luks`'s own shell
hook has no corresponding Python unit test; only `luks.py`'s Python-side build
helpers are). `usb.py`'s Python-side partition/`mkfs` command-builder functions
(pure `build_*_command()` style, same convention as the rest of the codebase) get
the normal direct unit tests. The hook itself is verified manually via QEMU boot,
matching how `miso_luks` was verified this session.

## Relationship to the plain `usb write` plan

The device-selection safety flow (insert/detect, confirm, remove-reinsert
re-verify, hard removable-only filter, final typed confirmation, `--device`/`--yes`
escape hatches) is designed once, in the separate plain-write plan, and applies
unchanged here. This spec only adds: an (optional, presumably a
`--persistent`-style flag or similar — not yet decided, see Open Questions) branch
in the write step that also creates the `MABOX_PERSIST` partition, plus the new
`miso_persist` boot hook. The write-time safety story does not change based on
what's being written.

## Open questions for the implementation plan (not blocking this spec)

- Exact CLI shape for opting into persistence on `usb write` (a flag? a
  positional mode? always-on when the ISO was built a certain way?) — not decided
  in this brainstorm, left for the implementation-planning step.
- Exact command(s) for appending the new partition after the ISO's own content is
  already on the device (`sfdisk`/`parted`/`sgdisk` — which tool, exact invocation)
  — an implementation detail, not a design-level decision.
- Whether `--encrypt` (currently preserving-mode-only, LUKS2 on `rootfs.sfs`) has
  any interaction with a persistent overlay (e.g. should the overlay itself ever
  be encrypted too) — not raised or discussed this session; flag for a future
  brainstorm if it becomes relevant, don't block this feature on it.
