import pytest

from mabox_persistence_usb import device, safety


def make_disk(path="/dev/sdb", size_bytes=8_000_000_000, serial="ABC123", vendor="Generic",
              model="Flash Drive", tran="usb", partitions=()):
    return device.UsbDisk(
        path=path, size_bytes=size_bytes, vendor=vendor, model=model, serial=serial,
        tran=tran, removable=True, partitions=partitions,
    )


def make_partition(path="/dev/sdb1", fstype="ext4", label=None, mountpoints=()):
    return device.UsbPartition(path=path, fstype=fstype, label=label, mountpoints=tuple(mountpoints))


# --- guards ----------------------------------------------------------------


def test_check_guards_passes_for_clean_small_device():
    disk = make_disk()
    safety.check_guards(disk, mounts_raw="", swaps_raw="Filename\n")  # must not raise


def test_check_guards_rejects_device_at_mbr_limit():
    disk = make_disk(size_bytes=device.constants.MAX_MBR_DEVICE_BYTES)
    with pytest.raises(safety.UnsafeDeviceError, match="2TiB"):
        safety.check_guards(disk, mounts_raw="", swaps_raw="Filename\n")


def test_check_guards_rejects_critical_mount():
    disk = make_disk(path="/dev/sdb")
    mounts_raw = "/dev/sdb1 / ext4 rw 0 0\n"
    with pytest.raises(safety.UnsafeDeviceError, match="critical mountpoint"):
        safety.check_guards(disk, mounts_raw=mounts_raw, swaps_raw="Filename\n")


def test_check_guards_rejects_active_swap():
    disk = make_disk(path="/dev/sdb")
    swaps_raw = "Filename\tType\n/dev/sdb2\tpartition\n"
    with pytest.raises(safety.UnsafeDeviceError):
        safety.check_guards(disk, mounts_raw="", swaps_raw=swaps_raw)


# --- resolve_explicit_device -------------------------------------------


def test_resolve_explicit_device_found():
    disk = make_disk()
    assert safety.resolve_explicit_device("/dev/sdb", [disk]) is disk


def test_resolve_explicit_device_not_eligible_raises_unsafe():
    with pytest.raises(safety.UnsafeDeviceError):
        safety.resolve_explicit_device("/dev/sda", [make_disk(path="/dev/sdb")])


# --- formatting --------------------------------------------------------


def test_format_size_bytes():
    assert safety.format_size(512) == "512 B"


def test_format_size_gib():
    assert safety.format_size(8 * 1024**3) == "8.0 GiB"


def test_format_identification_block_includes_key_fields():
    disk = make_disk(partitions=(make_partition(label="OLDDATA", mountpoints=("/mnt/x",)),))
    block = safety.format_identification_block(disk)
    assert "/dev/sdb" in block
    assert "ABC123" in block
    assert "OLDDATA" in block
    assert "/mnt/x" in block


def test_format_identification_block_no_partitions():
    block = safety.format_identification_block(make_disk(partitions=()))
    assert "existing partitions: none" in block


# --- enumerate_and_disambiguate -----------------------------------------


def test_enumerate_returns_single_candidate_immediately():
    disk = make_disk()
    result = safety.enumerate_and_disambiguate(lambda: [disk], input_fn=lambda _: "", print_fn=lambda _: None)
    assert result is disk


def test_enumerate_rescans_until_a_candidate_appears():
    calls = {"n": 0}

    def list_candidates():
        calls["n"] += 1
        return [] if calls["n"] < 3 else [make_disk()]

    result = safety.enumerate_and_disambiguate(list_candidates, input_fn=lambda _: "", print_fn=lambda _: None)
    assert result.path == "/dev/sdb"
    assert calls["n"] == 3


def test_enumerate_aborts_on_q_while_waiting():
    with pytest.raises(safety.AbortedError):
        safety.enumerate_and_disambiguate(lambda: [], input_fn=lambda _: "q", print_fn=lambda _: None)


def test_enumerate_disambiguates_multiple_by_number():
    a, b = make_disk(path="/dev/sdb"), make_disk(path="/dev/sdc")
    result = safety.enumerate_and_disambiguate(lambda: [a, b], input_fn=lambda _: "2", print_fn=lambda _: None)
    assert result is b


def test_enumerate_aborts_on_q_while_disambiguating():
    a, b = make_disk(path="/dev/sdb"), make_disk(path="/dev/sdc")
    with pytest.raises(safety.AbortedError):
        safety.enumerate_and_disambiguate(lambda: [a, b], input_fn=lambda _: "q", print_fn=lambda _: None)


def test_enumerate_rescans_on_invalid_then_valid_selection():
    a, b = make_disk(path="/dev/sdb"), make_disk(path="/dev/sdc")
    answers = iter(["9", "1"])
    result = safety.enumerate_and_disambiguate(lambda: [a, b], input_fn=lambda _: next(answers), print_fn=lambda _: None)
    assert result is a


# --- confirm_typed / confirm_unmount ------------------------------------


def test_confirm_typed_matches_exactly():
    assert safety.confirm_typed("/dev/sdb", input_fn=lambda _: "/dev/sdb", print_fn=lambda _: None) is True


def test_confirm_typed_rejects_mismatch_with_no_retry():
    assert safety.confirm_typed("/dev/sdb", input_fn=lambda _: "/dev/sdc", print_fn=lambda _: None) is False


def test_confirm_typed_rejects_empty():
    assert safety.confirm_typed("/dev/sdb", input_fn=lambda _: "", print_fn=lambda _: None) is False


def test_confirm_unmount_yes():
    disk = make_disk(partitions=(make_partition(mountpoints=("/mnt/x",)),))
    assert safety.confirm_unmount(disk, input_fn=lambda _: "y", print_fn=lambda _: None) is True


def test_confirm_unmount_no():
    disk = make_disk(partitions=(make_partition(mountpoints=("/mnt/x",)),))
    assert safety.confirm_unmount(disk, input_fn=lambda _: "n", print_fn=lambda _: None) is False


# --- wait_for_reinsert ---------------------------------------------------


def test_wait_for_reinsert_matches_by_serial_across_path_rename():
    original = make_disk(path="/dev/sdb", serial="ABC123")
    renumbered = make_disk(path="/dev/sdc", serial="ABC123")
    sequence = iter([[original], [], [], [renumbered]])

    result = safety.wait_for_reinsert(
        original, lambda: next(sequence), sleep_fn=lambda _: None, print_fn=lambda _: None,
        disappear_timeout=100, reappear_timeout=100, poll_interval=1,
    )
    assert result.path == "/dev/sdc"


def test_wait_for_reinsert_falls_back_to_fingerprint_without_serial():
    original = make_disk(path="/dev/sdb", serial=None, vendor="Generic", model="Flash Drive", size_bytes=123)
    renumbered = make_disk(path="/dev/sdc", serial=None, vendor="Generic", model="Flash Drive", size_bytes=123)
    sequence = iter([[original], [], [renumbered]])

    result = safety.wait_for_reinsert(
        original, lambda: next(sequence), sleep_fn=lambda _: None, print_fn=lambda _: None,
        disappear_timeout=100, reappear_timeout=100, poll_interval=1,
    )
    assert result.path == "/dev/sdc"


def test_wait_for_reinsert_raises_if_never_unplugged():
    disk = make_disk()
    with pytest.raises(safety.ReinsertTimeoutError):
        safety.wait_for_reinsert(
            disk, lambda: [disk], sleep_fn=lambda _: None, print_fn=lambda _: None,
            disappear_timeout=0, reappear_timeout=100, poll_interval=1,
        )


def test_wait_for_reinsert_raises_if_never_reappears():
    disk = make_disk()
    with pytest.raises(safety.ReinsertTimeoutError):
        safety.wait_for_reinsert(
            disk, lambda: [], sleep_fn=lambda _: None, print_fn=lambda _: None,
            disappear_timeout=100, reappear_timeout=0, poll_interval=1,
        )


# --- countdown -----------------------------------------------------------


def test_countdown_prints_and_sleeps_once_per_second():
    prints = []
    sleeps = []
    safety.countdown(seconds=3, sleep_fn=sleeps.append, print_fn=prints.append)
    assert len(prints) == 3
    assert sleeps == [1, 1, 1]
