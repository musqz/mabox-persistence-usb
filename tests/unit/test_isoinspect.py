import hashlib
from pathlib import Path

import pytest

from mabox_persistence_usb import constants, isoinspect


def write_fake_iso(path: Path, volume_id: str, extra_size: int = 0) -> None:
    pvd_offset = constants.ISO9660_PVD_OFFSET
    volid_offset = constants.ISO9660_VOLID_OFFSET_IN_PVD
    volid_len = constants.ISO9660_VOLID_LENGTH
    padded = volume_id.encode("ascii").ljust(volid_len)[:volid_len]
    buf = bytearray(pvd_offset + volid_offset + volid_len + extra_size)
    buf[pvd_offset + volid_offset : pvd_offset + volid_offset + volid_len] = padded
    path.write_bytes(bytes(buf))


def test_read_iso9660_volume_id_matches_written_value(tmp_path):
    iso_path = tmp_path / "fake.iso"
    write_fake_iso(iso_path, "MABOX_LIVE")
    assert isoinspect.read_iso9660_volume_id(iso_path) == "MABOX_LIVE"


def test_read_iso9660_volume_id_strips_trailing_padding(tmp_path):
    iso_path = tmp_path / "fake.iso"
    write_fake_iso(iso_path, "SHORT")
    assert isoinspect.read_iso9660_volume_id(iso_path) == "SHORT"


@pytest.mark.parametrize(
    "stem,expected_mode,expected_stamp",
    [
        ("mabox-preserving-23-08-2026-1830", "preserving", "23-08-2026-1830"),
        ("mabox-reset-01-01-2026-0000", "reset", "01-01-2026-0000"),
        ("custom-name", None, None),
    ],
)
def test_parse_iso_filename(tmp_path, stem, expected_mode, expected_stamp):
    iso_path = tmp_path / f"{stem}.iso"
    info = isoinspect.parse_iso_filename(iso_path)
    assert info.mode == expected_mode
    assert info.stamp == expected_stamp


def test_find_checksum_file_present(tmp_path):
    iso_path = tmp_path / "mabox.iso"
    iso_path.write_bytes(b"x")
    checksum_path = tmp_path / "mabox.iso.sha256"
    checksum_path.write_text("abc123  mabox.iso\n")
    assert isoinspect.find_checksum_file(iso_path) == checksum_path


def test_find_checksum_file_absent(tmp_path):
    iso_path = tmp_path / "mabox.iso"
    iso_path.write_bytes(b"x")
    assert isoinspect.find_checksum_file(iso_path) is None


def test_read_expected_checksum_takes_first_field():
    checksum_path_content = "deadbeef  mabox.iso\n"
    assert "deadbeef" in checksum_path_content.split()[0]


def test_hash_file_matches_hashlib(tmp_path):
    path = tmp_path / "data.bin"
    path.write_bytes(b"hello world" * 1000)
    expected = hashlib.sha256(b"hello world" * 1000).hexdigest()
    assert isoinspect.hash_file(path) == expected


def test_verify_source_checksum_ok(tmp_path):
    iso_path = tmp_path / "mabox.iso"
    iso_path.write_bytes(b"payload")
    digest = hashlib.sha256(b"payload").hexdigest()
    checksum_path = tmp_path / "mabox.iso.sha256"
    checksum_path.write_text(f"{digest}  mabox.iso\n")
    assert isoinspect.verify_source_checksum(iso_path, checksum_path) is True


def test_verify_source_checksum_mismatch(tmp_path):
    iso_path = tmp_path / "mabox.iso"
    iso_path.write_bytes(b"payload")
    checksum_path = tmp_path / "mabox.iso.sha256"
    checksum_path.write_text("0" * 64 + "  mabox.iso\n")
    assert isoinspect.verify_source_checksum(iso_path, checksum_path) is False


def test_parse_bsdtar_listing_strips_blank_lines():
    raw = "mabox/x86_64/rootfs.sfs\n\n  \nboot/grub/grub.cfg\n"
    assert isoinspect.parse_bsdtar_listing(raw) == ["mabox/x86_64/rootfs.sfs", "boot/grub/grub.cfg"]


def test_detect_rootfs_encryption_luks():
    members = ["mabox/x86_64/rootfs.sfs.luks", "boot/grub/grub.cfg"]
    assert isoinspect.detect_rootfs_encryption(members) is True


def test_detect_rootfs_encryption_plain():
    members = ["mabox/x86_64/rootfs.sfs", "boot/grub/grub.cfg"]
    assert isoinspect.detect_rootfs_encryption(members) is False


def test_detect_rootfs_encryption_neither():
    members = ["boot/grub/grub.cfg"]
    assert isoinspect.detect_rootfs_encryption(members) is None


def test_evaluate_hook_support_unsupported_when_marker_absent():
    result = isoinspect.evaluate_hook_support(["boot/grub/grub.cfg"], extract_member=lambda m: "")
    assert result is isoinspect.HookSupport.UNSUPPORTED


def test_evaluate_hook_support_supported_when_version_meets_minimum():
    members = [constants.PERSIST_HOOK_MARKER_PATH]
    result = isoinspect.evaluate_hook_support(members, extract_member=lambda m: "1")
    assert result is isoinspect.HookSupport.SUPPORTED


def test_evaluate_hook_support_unsupported_when_version_below_minimum():
    members = [constants.PERSIST_HOOK_MARKER_PATH]
    result = isoinspect.evaluate_hook_support(members, extract_member=lambda m: "0")
    assert result is isoinspect.HookSupport.UNSUPPORTED


def test_evaluate_hook_support_unknown_when_marker_unparseable():
    members = [constants.PERSIST_HOOK_MARKER_PATH]
    result = isoinspect.evaluate_hook_support(members, extract_member=lambda m: "not-a-number")
    assert result is isoinspect.HookSupport.UNKNOWN
