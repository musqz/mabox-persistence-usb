from pathlib import Path

from mabox_persistence_usb import writer


def test_build_dd_write_command_uses_expected_flags():
    cmd = writer.build_dd_write_command(Path("/tmp/mabox.iso"), "/dev/sdb")
    assert "if=/tmp/mabox.iso" in cmd
    assert "of=/dev/sdb" in cmd
    assert "bs=4M" in cmd
    assert "status=progress" in cmd
    assert "conv=fsync" in cmd
    assert "oflag=direct" in cmd


def test_build_dd_write_command_custom_block_size():
    cmd = writer.build_dd_write_command(Path("/tmp/mabox.iso"), "/dev/sdb", block_size="1M")
    assert "bs=1M" in cmd
    assert "bs=4M" not in cmd


def test_build_sync_command():
    assert writer.build_sync_command() == ["sync"]
