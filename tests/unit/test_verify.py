import hashlib

from mabox_persistence_usb import verify


def test_build_blkid_command():
    assert verify.build_blkid_command("/dev/sdb3", "LABEL") == [
        "blkid", "-o", "value", "-s", "LABEL", "/dev/sdb3"
    ]


def test_hash_device_prefix_hashes_exactly_requested_length(tmp_path):
    fake_device = tmp_path / "fake-device"
    fake_device.write_bytes(b"A" * 1000 + b"B" * 1000)

    digest = verify.hash_device_prefix(str(fake_device), 1000)

    assert digest == hashlib.sha256(b"A" * 1000).hexdigest()


def test_hash_device_prefix_stops_at_end_of_file_if_shorter_than_requested(tmp_path):
    fake_device = tmp_path / "fake-device"
    fake_device.write_bytes(b"A" * 500)

    digest = verify.hash_device_prefix(str(fake_device), 1000)

    assert digest == hashlib.sha256(b"A" * 500).hexdigest()


def test_verify_persist_label_matches(monkeypatch):
    monkeypatch.setattr(verify, "read_blkid_tag", lambda p, tag: "MABOX_PERSIST")
    assert verify.verify_persist_label("/dev/sdb3", "MABOX_PERSIST") is True


def test_verify_persist_label_mismatch(monkeypatch):
    monkeypatch.setattr(verify, "read_blkid_tag", lambda p, tag: "OTHER")
    assert verify.verify_persist_label("/dev/sdb3", "MABOX_PERSIST") is False


def test_verify_persist_luks_matches(monkeypatch):
    monkeypatch.setattr(verify, "read_blkid_tag", lambda p, tag: "crypto_LUKS")
    assert verify.verify_persist_luks("/dev/sdb3") is True


def test_verify_persist_luks_mismatch(monkeypatch):
    monkeypatch.setattr(verify, "read_blkid_tag", lambda p, tag: "ext4")
    assert verify.verify_persist_luks("/dev/sdb3") is False
