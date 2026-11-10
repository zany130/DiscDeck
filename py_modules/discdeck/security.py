"""Read-only command policy and export redaction.

The diagnostic runner may inspect processes and buses. It must not start
services, mount filesystems, or invoke disc tools beyond an explicit
``--version`` probe.
"""

from __future__ import annotations

import os
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
