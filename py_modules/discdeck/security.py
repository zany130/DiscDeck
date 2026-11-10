"""Command policy and export redaction.

Diagnostic probes stay read-only. The physical manager may call three UDisks2
methods, and only with arguments this module builds: read-only ``Mount``,
``Unmount``, and ``Drive.Eject``. Loop setup, the ``mount`` and ``eject``
binaries, and ioctl tray close stay refused.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from discdeck.errors import UnsafeCommand


def assert_readonly_argv(argv: list[str]) -> None:
    if not argv or any(not isinstance(part, str) or part == "" for part in argv):
        raise UnsafeCommand("Command arguments must be non-empty strings.")
    if any("\n" in part or "\x00" in part for part in argv):
        raise UnsafeCommand("Command arguments contain unsupported characters.")

    program = Path(argv[0]).name
    blocked = {
        "sudo",
        "pkexec",
        "mount",
        "umount",
        "eject",
        "modprobe",
        "insmod",
        "cdemu",
        "cdemu-daemon",
        "steam",
        "steamcmd",
        "chmod",
        "chown",
        "setfacl",
    }
    if program in blocked:
        raise UnsafeCommand(f"Refusing to run {program}.")

    if program == "systemctl":
        allowed = {"--user", "--system", "is-active", "--no-pager", "cdemu-daemon.service"}
        if any(part not in allowed for part in argv[1:]):
            raise UnsafeCommand("systemctl is limited to reading cdemu-daemon.service activity.")
        if "is-active" not in argv:
            raise UnsafeCommand("systemctl must be an is-active query.")
        return

    if program == "busctl":
        if "call" in argv and "GetManagedObjects" not in argv:
            raise UnsafeCommand("The only permitted D-Bus method is GetManagedObjects.")
        forbidden_methods = {"Mount", "Unmount", "Eject", "LoopSetup", "PowerOff", "Rescan"}
        if any(part in forbidden_methods for part in argv):
            raise UnsafeCommand("Refusing a mutating UDisks2 method.")
        return

    if program == "getfacl":
        return

    if program == "redumper":
        if argv[1:] != ["--version"]:
            raise UnsafeCommand("Redumper may only be asked for --version, with no drive arguments.")
        return

    raise UnsafeCommand(f"Program is not on the Phase 0 read-only allowlist: {program}")


_UDISKS_OBJECT = re.compile(r"^/org/freedesktop/UDisks2/(block_devices|drives)/[A-Za-z0-9_.+-]+$")


def assert_physical_udisks_argv(argv: list[str]) -> None:
    """Allow one read-only mount, unmount, or eject call built by DiscDeck."""
    if not argv or any(not isinstance(part, str) or part == "" for part in argv):
        raise UnsafeCommand("Command arguments must be non-empty strings.")
    if any("\n" in part or "\x00" in part for part in argv):
        raise UnsafeCommand("Command arguments contain unsupported characters.")
    if Path(argv[0]).name != "busctl":
        raise UnsafeCommand("Physical actions use busctl, not a mount or eject binary.")
    if any(part in {"LoopSetup", "PowerOff", "Rescan", "rw"} for part in argv):
        raise UnsafeCommand("Refusing a UDisks2 method outside the physical manager.")
    prefix = [
        "busctl",
        "--system",
        "--no-pager",
        "call",
        "org.freedesktop.UDisks2",
    ]
    if argv[:5] != prefix or len(argv) < 9:
        raise UnsafeCommand("Physical busctl calls must target the system UDisks2 service.")
    object_path, interface, method = argv[5], argv[6], argv[7]
    if _UDISKS_OBJECT.match(object_path) is None:
        raise UnsafeCommand("UDisks2 object path is not a block device or drive.")
    if method == "Mount" and argv[6:] == [
        "org.freedesktop.UDisks2.Filesystem",
        "Mount",
        "a{sv}",
        "1",
        "options",
        "s",
        "ro",
    ]:
        return
    if method == "Unmount" and argv[6:] == ["org.freedesktop.UDisks2.Filesystem", "Unmount", "a{sv}", "0"]:
        return
    if method == "Eject" and interface == "org.freedesktop.UDisks2.Drive" and argv[7:] == ["Eject", "a{sv}", "0"]:
        return
    raise UnsafeCommand("Refusing a UDisks2 call that is not read-only Mount, Unmount, or Drive.Eject.")


def redact_home(value: str | None, home: str | None) -> str | None:
    if value is None:
        return None
    if home and home not in {"", "/"} and (value == home or value.startswith(home + os.sep)):
        return "$HOME" + value[len(home) :]
    return value


def redact_record(record: dict[str, object], home: str | None) -> dict[str, object]:
    redacted: dict[str, object] = {}
    for key, value in record.items():
        if isinstance(value, str):
            redacted[key] = redact_home(value, home)
        elif isinstance(value, dict):
            redacted[key] = redact_record(value, home)
        elif isinstance(value, list):
            redacted[key] = [
                redact_record(item, home) if isinstance(item, dict) else redact_home(item, home) if isinstance(item, str) else item
                for item in value
            ]
        else:
            redacted[key] = value
    return redacted
