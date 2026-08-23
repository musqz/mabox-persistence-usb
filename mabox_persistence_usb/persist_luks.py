"""LUKS2-encrypts the MABOX_PERSIST overlay partition (--encrypt-persist),
independently of whether the source ISO's own rootfs was built with
mabox-snapshot's --encrypt -- the two protect entirely different things
(the ISO's OS payload vs. whatever gets written to the stick after
booting it) and have no interaction.

Genuinely simpler than mabox_snapshot/luks.py's rootfs encryption: this
formats a real partition block device directly, so there is no sparse
container file and no losetup step -- cryptsetup luksFormat runs straight
against the appended partition.

Same command-builder/executor split as mabox_snapshot/luks.py: the
build_*_command() functions are pure and unit-tested; the functions that
actually run them (real cryptsetup, needs root) are thin subprocess.run()
wrappers and are not unit-tested."""

from __future__ import annotations

import getpass
import subprocess
import sys

from . import constants, partition


def build_luks_format_command(partition_path: str) -> list[str]:
    # -q/--batch-mode: without it, cryptsetup's interactive "this will
    # overwrite data, are you sure?" confirmation would itself try to read
    # from stdin, colliding with --key-file=-.
    return ["cryptsetup", "luksFormat", "-q", "--type", "luks2", "--key-file=-", partition_path]


def build_luks_open_command(partition_path: str, mapper_name: str) -> list[str]:
    return ["cryptsetup", "open", "--type", "luks2", "--key-file=-", partition_path, mapper_name]


def build_luks_close_command(mapper_name: str) -> list[str]:
    return ["cryptsetup", "close", mapper_name]


def prompt_for_passphrase() -> str:
    """getpass twice with a match check (mirrors passwd's UX convention,
    same as mabox_snapshot.luks.prompt_for_passphrase()). Never reads a
    passphrase from a flag, env var, or file -- always prompted, even in
    --yes mode, since there is no safe silent default: proceeding without a
    real passphrase when --encrypt-persist was explicitly requested would
    silently defeat the whole feature."""
    if not sys.stdin.isatty():
        raise RuntimeError(
            "--encrypt-persist requires an interactive terminal to prompt for a passphrase "
            "(no passphrase is ever read from a flag or environment variable)"
        )
    while True:
        p1 = getpass.getpass("LUKS passphrase for the persistence partition: ")
        if not p1:
            print("error: passphrase must not be empty", file=sys.stderr)
            continue
        p2 = getpass.getpass("Confirm passphrase: ")
        if p1 != p2:
            print("error: passphrases did not match, try again", file=sys.stderr)
            continue
        return p1


def format_container(partition_path: str, passphrase: str) -> None:
    subprocess.run(build_luks_format_command(partition_path), input=passphrase.encode(), check=True)


def open_container(partition_path: str, mapper_name: str, passphrase: str) -> None:
    subprocess.run(build_luks_open_command(partition_path, mapper_name), input=passphrase.encode(), check=True)


def close_container(mapper_name: str) -> None:
    subprocess.run(build_luks_close_command(mapper_name), check=True)


def format_persist_encrypted(
    partition_path: str,
    passphrase: str,
    mapper_name: str = constants.PERSIST_LUKS_MAPPER_NAME,
) -> None:
    """LUKS2-formats partition_path, opens it, and builds the MABOX_PERSIST
    ext4 filesystem on the opened mapper -- then always closes the mapper
    again, success or failure, so nothing is left attached. The mapper name
    is a hardcoded constant (constants.PERSIST_LUKS_MAPPER_NAME) that a
    future miso_persist LUKS-unlock branch (in mabox-snapshot) must use
    identically at boot."""
    opened = False
    try:
        format_container(partition_path, passphrase)
        open_container(partition_path, mapper_name, passphrase)
        opened = True
        partition.format_persist_plain(f"/dev/mapper/{mapper_name}")
    finally:
        if opened:
            close_container(mapper_name)
