"""Raw ISO -> device byte copy. Command builder is pure/tested; the
executor actually runs dd against a real device and needs root -- not
unit-tested, same untested-execution-layer precedent as
mabox_snapshot.luks.copy_plaintext_onto_mapper()."""

from __future__ import annotations

import subprocess
from pathlib import Path

from . import constants


def build_dd_write_command(iso_path: Path, device_path: str, block_size: str = constants.DD_BLOCK_SIZE) -> list[str]:
    # oflag=direct: new here, not present in mabox-snapshot's own loop-device
    # dd copy -- bypasses the page cache on the write side so status=progress
    # reflects real physical write throughput, and combined with conv=fsync
    # means a successful exit is a strong guarantee the bytes are actually on
    # the media before the caller proceeds to partition the rest of the
    # device. 4M blocks safely satisfy O_DIRECT's alignment requirement on
    # any standard 512e/4Kn USB drive.
    return [
        "dd", f"if={iso_path}", f"of={device_path}", f"bs={block_size}",
        "status=progress", "conv=fsync", "oflag=direct",
    ]


def build_sync_command() -> list[str]:
    return ["sync"]


def write_iso_to_device(iso_path: Path, device_path: str) -> None:
    subprocess.run(build_dd_write_command(iso_path, device_path), check=True)
    subprocess.run(build_sync_command(), check=True)
