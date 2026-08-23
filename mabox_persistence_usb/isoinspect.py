"""Read-only ISO validation: ISO9660 volume-ID check, checksum verification,
filename parsing, rootfs-encryption detection, and (future) persistence
boot-hook support detection. Pure/streaming logic against the ISO file
directly -- no mounting, no root needed.

inspect_iso() is the thin executor (shells out to bsdtar); everything it
calls is pure and unit-tested directly, same command-builder/executor split
as mabox_snapshot/luks.py."""

from __future__ import annotations

import enum
import hashlib
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import constants


def read_iso9660_volume_id(iso_path: Path) -> str:
    """Reads the Volume Identifier straight out of the Primary Volume
    Descriptor -- no mounting, no external tool needed."""
    with open(iso_path, "rb") as f:
        f.seek(constants.ISO9660_PVD_OFFSET + constants.ISO9660_VOLID_OFFSET_IN_PVD)
        raw = f.read(constants.ISO9660_VOLID_LENGTH)
    return raw.decode("ascii", errors="replace").rstrip()


ISO_FILENAME_RE = re.compile(r"^mabox-(?P<mode>preserving|reset)-(?P<stamp>\d{2}-\d{2}-\d{4}-\d{4})$")


@dataclass(frozen=True)
class IsoFilenameInfo:
    mode: str | None
    stamp: str | None


def parse_iso_filename(iso_path: Path) -> IsoFilenameInfo:
    """Best-effort: mabox-snapshot's default stem is mabox-<mode>-<DD-MM-YYYY-HHMM>,
    but --iso-name can override it entirely, so a non-match is informational
    only, never an error."""
    match = ISO_FILENAME_RE.match(iso_path.stem)
    if not match:
        return IsoFilenameInfo(mode=None, stamp=None)
    return IsoFilenameInfo(mode=match.group("mode"), stamp=match.group("stamp"))


def find_checksum_file(iso_path: Path) -> Path | None:
    candidate = iso_path.with_suffix(iso_path.suffix + ".sha256")
    return candidate if candidate.exists() else None


def read_expected_checksum(checksum_path: Path) -> str:
    return checksum_path.read_text().split()[0].strip().lower()


def hash_file(path: Path, chunk_size: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def verify_source_checksum(iso_path: Path, checksum_path: Path) -> bool:
    return hash_file(iso_path).lower() == read_expected_checksum(checksum_path)


def build_bsdtar_list_command(iso_path: Path) -> list[str]:
    return ["bsdtar", "-tf", str(iso_path)]


def build_bsdtar_extract_command(iso_path: Path, member: str) -> list[str]:
    return ["bsdtar", "-xO", "-f", str(iso_path), member]


def parse_bsdtar_listing(raw: str) -> list[str]:
    return [line.strip() for line in raw.splitlines() if line.strip()]


ROOTFS_LUKS_MEMBER_SUFFIX = "rootfs.sfs.luks"
ROOTFS_PLAIN_MEMBER_SUFFIX = "rootfs.sfs"


def detect_rootfs_encryption(members: list[str]) -> bool | None:
    """True if rootfs.sfs.luks is present (--encrypt build), False if plain
    rootfs.sfs is present, None if neither is found (unexpected ISO layout).
    Informational only -- irrelevant to how this tool writes bytes, since a
    raw dd copy has no awareness of ISO9660 contents at all."""
    has_luks = any(m.endswith(ROOTFS_LUKS_MEMBER_SUFFIX) for m in members)
    if has_luks:
        return True
    has_plain = any(m.endswith(ROOTFS_PLAIN_MEMBER_SUFFIX) for m in members)
    if has_plain:
        return False
    return None


class HookSupport(enum.Enum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


def evaluate_hook_support(
    members: list[str],
    extract_member: Callable[[str], str],
    min_version: int = constants.MIN_SUPPORTED_HOOK_VERSION,
) -> HookSupport:
    """Checks for the proposed mabox/.persist-hook-version marker (see
    constants.PERSIST_HOOK_MARKER_PATH). mabox-snapshot does not write this
    marker yet as of this tool's 0.1.0 -- every real ISO today evaluates to
    UNSUPPORTED, which is accurate, not a bug: `write` does not gate on this
    result yet (see cli.cmd_write's unconditional warning instead), it only
    informs `inspect`'s report until mabox-snapshot ships the marker."""
    if constants.PERSIST_HOOK_MARKER_PATH not in members:
        return HookSupport.UNSUPPORTED
    raw = extract_member(constants.PERSIST_HOOK_MARKER_PATH).strip()
    try:
        version = int(raw)
    except ValueError:
        return HookSupport.UNKNOWN
    return HookSupport.SUPPORTED if version >= min_version else HookSupport.UNSUPPORTED


@dataclass(frozen=True)
class IsoInspection:
    path: Path
    volume_id: str
    volume_id_ok: bool
    filename_info: IsoFilenameInfo
    checksum_path: Path | None
    checksum_ok: bool | None
    rootfs_encrypted: bool | None
    hook_support: HookSupport


def inspect_iso(iso_path: Path) -> IsoInspection:
    volume_id = read_iso9660_volume_id(iso_path)
    listing_raw = subprocess.run(
        build_bsdtar_list_command(iso_path), capture_output=True, text=True, check=True
    ).stdout
    members = parse_bsdtar_listing(listing_raw)

    checksum_path = find_checksum_file(iso_path)
    checksum_ok = verify_source_checksum(iso_path, checksum_path) if checksum_path else None

    def _extract(member: str) -> str:
        return subprocess.run(
            build_bsdtar_extract_command(iso_path, member), capture_output=True, text=True, check=True
        ).stdout

    return IsoInspection(
        path=iso_path,
        volume_id=volume_id,
        volume_id_ok=volume_id == constants.ISO_VOLID,
        filename_info=parse_iso_filename(iso_path),
        checksum_path=checksum_path,
        checksum_ok=checksum_ok,
        rootfs_encrypted=detect_rootfs_encryption(members),
        hook_support=evaluate_hook_support(members, _extract),
    )
