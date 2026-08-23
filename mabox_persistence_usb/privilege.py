"""Root check. No silent sudo re-exec -- the user runs `sudo mabox-persistence-usb ...` themselves."""

import os


class NotRootError(RuntimeError):
    pass


def require_root(action: str) -> None:
    if os.geteuid() != 0:
        raise NotRootError(f"{action} requires root -- re-run with sudo.")


def is_root() -> bool:
    return os.geteuid() == 0
