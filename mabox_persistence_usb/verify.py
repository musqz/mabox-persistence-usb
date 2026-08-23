"""Post-write verification: confirm blkid reports the expected label on the
new partition, and (if a source checksum was available) confirm the
device's own ISO byte range still matches it. A failure here is reported
distinctly from a failure during the write itself (see cli.py's exit code 3)."""

from __future__ import annotations

import hashlib
import subprocess


def build_blkid_command(partition_path: str, tag: str) -> list[str]:
    return ["blkid", "-o", "value", "-s", tag, partition_path]


def read_blkid_tag(partition_path: str, tag: str) -> str:
    result = subprocess.run(
        build_blkid_command(partition_path, tag), capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def verify_persist_label(partition_path: str, expected_label: str) -> bool:
    return read_blkid_tag(partition_path, "LABEL") == expected_label


def hash_device_prefix(device_path: str, length_bytes: int, chunk_size: int = 4 * 1024 * 1024) -> str:
    """Streams exactly length_bytes off the start of device_path and returns
    its sha256 hex digest -- used to re-verify the ISO's own bytes after
    writing, without depending on GNU dd's count_bytes/skip_bytes iflag
    combination."""
    digest = hashlib.sha256()
    remaining = length_bytes
    with open(device_path, "rb") as f:
        while remaining > 0:
            chunk = f.read(min(chunk_size, remaining))
            if not chunk:
                break
            digest.update(chunk)
            remaining -= len(chunk)
    return digest.hexdigest()
