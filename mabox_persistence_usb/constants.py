"""Every hardcoded path, label, and cross-repo contract constant, in one place."""

from pathlib import Path

# Must stay in sync by hand with mabox_snapshot.constants.ISO_VOLID -- the two
# repos share no runtime code, so this is a single source of truth kept
# identical across both, same precedent as ISO_LUKS_MAPPER_NAME below.
ISO_VOLID = "MABOX_LIVE"

# The overlay partition's fixed ext4 label. Never user-overridable -- the
# (not-yet-implemented) miso_persist boot hook in mabox-snapshot looks it up
# by this exact label via /dev/disk/by-label/MABOX_PERSIST.
PERSIST_LABEL = "MABOX_PERSIST"

# dm-crypt mapper name for an --encrypt-persist overlay. Hardcoded and must
# match whatever the future miso_persist LUKS branch uses to `cryptsetup
# open` it at boot -- same manual-sync-across-two-repos precedent as
# mabox_snapshot.constants.ISO_LUKS_MAPPER_NAME ("mabox_rootfs").
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

# Proposed marker for the not-yet-implemented miso_persist hook support
# check (see docs/superpowers/specs/2026-08-20-persistent-usb-design.md and
# isoinspect.evaluate_hook_support()) -- a plain text file inside the ISO9660
# tree, parallel to isobuild.py's existing ".miso" marker convention, rather
# than requiring this tool to decompress and walk the initramfs cpio.
PERSIST_HOOK_MARKER_PATH = "mabox/.persist-hook-version"
MIN_SUPPORTED_HOOK_VERSION = 1

# Physical remove/reinsert re-verification timing (safety.wait_for_reinsert).
REINSERT_DISAPPEAR_TIMEOUT_S = 30.0
REINSERT_REAPPEAR_TIMEOUT_S = 60.0
REINSERT_POLL_INTERVAL_S = 1.0

# Always runs, even with --yes -- a last visible window before anything
# destructive starts, interruptible via Ctrl-C.
PRE_WRITE_COUNTDOWN_S = 5

DD_BLOCK_SIZE = "4M"
