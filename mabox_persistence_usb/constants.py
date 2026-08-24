"""Every hardcoded path, label, and cross-repo contract constant, in one place."""

from pathlib import Path

# Must stay in sync by hand with mabox_snapshot.constants.ISO_VOLID -- the two
# repos share no runtime code, so this is a single source of truth kept
# identical across both, same precedent as ISO_LUKS_MAPPER_NAME below.
ISO_VOLID = "MABOX_LIVE"

# The overlay partition's fixed ext4 label. Never user-overridable -- the
# miso_persist boot hook in mabox-snapshot (merged upstream, not yet in a
# tagged release) looks it up by this exact label via
# /dev/disk/by-label/MABOX_PERSIST.
PERSIST_LABEL = "MABOX_PERSIST"

# dm-crypt mapper name for an --encrypt-persist overlay. Hardcoded and must
# match whatever a future miso_persist LUKS-unlock branch uses to
# `cryptsetup open` it at boot -- same manual-sync-across-two-repos
# precedent as mabox_snapshot.constants.ISO_LUKS_MAPPER_NAME ("mabox_rootfs").
# No such branch exists yet: the merged miso_persist hook only looks for a
# plain ext4 MABOX_PERSIST by label, so an --encrypt-persist stick is not
# usable at boot until one is added (see MIN_SUPPORTED_ENCRYPTED_HOOK_VERSION
# below).
PERSIST_LUKS_MAPPER_NAME = "mabox_persist"

# 1 MiB alignment for the appended partition's start offset -- standard
# practice for flash media, cheap relative to typical stick sizes.
PARTITION_ALIGNMENT_BYTES = 1024 * 1024

# MBR's 32-bit LBA field addresses at most 2^32 sectors; the ISO's own hybrid
# boot layout (mabox-snapshot's isobuild.py) uses a classic msdos partition
# table, not GPT, so this is a hard ceiling on total device size, not just a
# convention. Converting the whole hybrid scheme to GPT would risk
# mabox-snapshot's carefully-built BIOS+EFI boot layout for no requested
# benefit -- devices at or beyond this size are refused outright rather than
# silently mishandled.
MAX_MBR_DEVICE_BYTES = 2**32 * 512

REQUIRED_TOOLS = [
    "lsblk", "udevadm", "blkid", "parted", "partprobe",
    "mkfs.ext4", "dd", "sha256sum", "bsdtar",
]
OPTIONAL_TOOLS = ["cryptsetup"]

# Mountpoints that make a device "the currently running system" rather than
# incidental/removable storage -- refuse outright if the target device hosts
# any of these, regardless of how it was selected. Deliberately broader than
# just "/": a USB-attached enclosure could plausibly host /home or /var too.
CRITICAL_MOUNTPOINTS = frozenset({"/", "/boot", "/home", "/var"})

PROC_MOUNTS_FILE = Path("/proc/mounts")
PROC_SWAPS_FILE = Path("/proc/swaps")

# ISO9660 Primary Volume Descriptor: sector 16 (0-indexed) of a 2048-byte
# sector image; the Volume Identifier field is a fixed 32-byte, space-padded
# field starting at byte offset 40 within that sector. Reading this directly
# needs no external tool and works whether or not the ISO is mounted.
ISO9660_PVD_OFFSET = 0x8000
ISO9660_VOLID_OFFSET_IN_PVD = 40
ISO9660_VOLID_LENGTH = 32

# Marker for the miso_persist hook support check (see
# docs/superpowers/specs/2026-08-20-persistent-usb-design.md and
# isoinspect.evaluate_hook_support()) -- a plain text file inside the ISO9660
# tree, parallel to isobuild.py's existing ".miso" marker convention, rather
# than requiring this tool to decompress and walk the initramfs cpio. Matches
# mabox_snapshot.constants.PERSIST_HOOK_MARKER_RELPATH /
# PERSIST_HOOK_VERSION exactly (merged in mabox-snapshot PR #61, 2026-08-23 --
# not yet in a tagged mabox-snapshot release as of this tool's version).
PERSIST_HOOK_MARKER_PATH = "mabox/.persist-hook-version"

# Version 1: plain (unencrypted) MABOX_PERSIST support -- the merged
# miso_persist hook overlays a plain ext4 partition found by label.
MIN_SUPPORTED_HOOK_VERSION = 1

# No shipped or merged mabox-snapshot version advertises this yet: the
# merged miso_persist hook has no cryptsetup/LUKS-unlock branch at all, so it
# cannot find or open an --encrypt-persist partition (which shows up as
# TYPE=crypto_LUKS, not a labeled ext4 volume, until unlocked). Set one
# version ahead of MIN_SUPPORTED_HOOK_VERSION so isoinspect.evaluate_hook_support()
# correctly reports UNSUPPORTED for --encrypt-persist against every ISO today,
# without conflating "supports plain persistence" with "supports encrypted
# persistence" -- bump this only once mabox-snapshot ships and advertises a
# real LUKS-unlock branch.
MIN_SUPPORTED_ENCRYPTED_HOOK_VERSION = 2

# Physical remove/reinsert re-verification timing (safety.wait_for_reinsert).
REINSERT_DISAPPEAR_TIMEOUT_S = 30.0
REINSERT_REAPPEAR_TIMEOUT_S = 60.0
REINSERT_POLL_INTERVAL_S = 1.0

# Always runs, even with --yes -- a last visible window before anything
# destructive starts, interruptible via Ctrl-C.
PRE_WRITE_COUNTDOWN_S = 5

DD_BLOCK_SIZE = "4M"

# partprobe can transiently fail with parted's "unable to inform the kernel
# of the change ... probably because it/they are in use" -- a desktop
# automount daemon (udisks2/gvfs) keeps re-mounting the drive as soon as its
# filesystem label reappears from the write, not just a one-off race. Each
# retry actively unmounts whatever reappeared (see
# partition._unmount_reappeared_partitions) rather than just waiting, but
# the daemon can re-win a couple of rounds on a slow/loaded desktop, so give
# it real headroom before giving up for good.
PARTPROBE_RETRIES = 10
PARTPROBE_RETRY_DELAY_S = 1.5

# partprobe exiting 0 and `udevadm settle` returning don't guarantee
# lsblk's/parted's own view is caught up yet -- the new partition can still
# lag a beat behind both of those reporting done, even with no automount
# daemon in the picture (observed after a long dd leaves the kernel busy on
# that same device). Retry partition._find_partition_by_start itself before
# giving up, separate from PARTPROBE_RETRIES above which only covers
# partprobe itself failing. 15s of headroom, matching PARTPROBE_RETRIES'
# budget: 5s (the original guess) proved too short in real use.
PARTITION_LOOKUP_RETRIES = 10
PARTITION_LOOKUP_RETRY_DELAY_S = 1.5
