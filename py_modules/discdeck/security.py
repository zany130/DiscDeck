"""Command policy and export redaction.

Diagnostic probes stay read-only. Explicit actions may use the exact UDisks2
calls this module recognizes: read-only ``Mount``, ``Unmount``, ``Drive.Eject``,
read-only ``LoopSetup``, ``Loop.Delete``, and a ``BackingFile`` read. The
``mount`` binary and ioctl tray close stay refused.
"""

from __future__ import annotations

import os
import re
from pathlib import Path, PurePosixPath

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
_LOOP_OBJECT = re.compile(r"^/org/freedesktop/UDisks2/block_devices/loop[0-9]+$")
_LOOP_NODE = re.compile(r"^/dev/loop[0-9]+$")
_BUSCTL_HEAD = [
    "busctl",
    "--system",
    "--no-pager",
    "--allow-interactive-authorization=false",
    "call",
    "org.freedesktop.UDisks2",
]
_SESSION_HEAD = ["systemd-run", "--user", "--pipe", "--wait", "--collect", "--quiet"]
_GET_PROPERTY_HEAD = ["busctl", "--system", "--no-pager", "get-property", "org.freedesktop.UDisks2"]


def _iso_path_ok(path: str) -> bool:
    if not path.startswith("/") or path != PurePosixPath(path).as_posix():
        return False
    parts = PurePosixPath(path).parts
    if any(part in {"", ".", ".."} for part in parts):
        return False
    return PurePosixPath(path).suffix.lower() == ".iso"


def _accept_image_argv(argv: list[str]) -> bool:
    """Accept one exact ISO-loop call, or reject a near miss. Unrelated argv returns False."""
    name = Path(argv[0]).name
    if name == "udisksctl":
        if len(argv) == 5 and argv[1:3] == ["loop-setup", "-f"] and argv[4] == "-r" and _iso_path_ok(argv[3]):
            return True
        if len(argv) == 4 and argv[1:3] == ["loop-delete", "-b"] and _LOOP_NODE.fullmatch(argv[3]):
            return True
        raise UnsafeCommand("udisksctl is only allowed for read-only loop-setup of an ISO or loop-delete of a loop device.")
    if name != "busctl":
        return False
    if argv[: len(_GET_PROPERTY_HEAD)] == _GET_PROPERTY_HEAD:
        if len(argv) == 8 and _LOOP_OBJECT.fullmatch(argv[5]) and argv[6:] == ["org.freedesktop.UDisks2.Loop", "BackingFile"]:
            return True
        raise UnsafeCommand("The only UDisks2 property read allowed here is Loop.BackingFile on a loop device.")
    if "LoopSetup" in argv or (len(argv) > 8 and argv[8] == "Delete" and "org.freedesktop.UDisks2.Loop" in argv):
        fd_ok = len(argv) == 15 and argv[10].isdigit() and int(argv[10]) > 2
        setup = (
            fd_ok
            and argv[6:10] == ["/org/freedesktop/UDisks2/Manager", "org.freedesktop.UDisks2.Manager", "LoopSetup", "ha{sv}"]
            and argv[11:] == ["1", "read-only", "b", "true"]
        )
        delete = (
            len(argv) == 11
            and _LOOP_OBJECT.fullmatch(argv[6])
            and argv[7:] == ["org.freedesktop.UDisks2.Loop", "Delete", "a{sv}", "0"]
        )
        if argv[: len(_BUSCTL_HEAD)] == _BUSCTL_HEAD and (setup or delete):
            return True
        raise UnsafeCommand("Refusing a loop call that is not read-only LoopSetup or Loop.Delete.")
    return False


def assert_physical_udisks_argv(argv: list[str]) -> None:
    """Allow one explicit UDisks2 action built by DiscDeck."""
    if not argv or any(not isinstance(part, str) or part == "" for part in argv):
        raise UnsafeCommand("Command arguments must be non-empty strings.")
    if any("\n" in part or "\x00" in part for part in argv):
        raise UnsafeCommand("Command arguments contain unsupported characters.")
    if Path(argv[0]).name == "eject" and len(argv) == 2 and re.fullmatch(r"/dev/sr[0-9]+", argv[1]):
        return
    if Path(argv[0]).name == "systemd-run":
        if argv[: len(_SESSION_HEAD)] != _SESSION_HEAD:
            raise UnsafeCommand("systemd-run is only allowed as a user-session wrapper around one UDisks2 call.")
        assert_physical_udisks_argv(argv[len(_SESSION_HEAD) :])
        return
    if _accept_image_argv(argv):
        return
    if Path(argv[0]).name != "busctl":
        raise UnsafeCommand("Physical actions use busctl, not a mount or eject binary.")
    if any(part in {"LoopSetup", "PowerOff", "Rescan", "rw"} for part in argv):
        raise UnsafeCommand("Refusing a UDisks2 method outside the physical manager.")
    head = [Path(argv[0]).name, *argv[1 : len(_BUSCTL_HEAD)]]
    if head != _BUSCTL_HEAD or len(argv) < len(_BUSCTL_HEAD) + 3:
        raise UnsafeCommand("Physical busctl calls must target the system UDisks2 service.")
    object_path = argv[len(_BUSCTL_HEAD)]
    interface = argv[len(_BUSCTL_HEAD) + 1]
    method = argv[len(_BUSCTL_HEAD) + 2]
    tail = argv[len(_BUSCTL_HEAD) + 1 :]
    if _UDISKS_OBJECT.match(object_path) is None:
        raise UnsafeCommand("UDisks2 object path is not a block device or drive.")
    if method == "Mount" and tail == [
        "org.freedesktop.UDisks2.Filesystem",
        "Mount",
        "a{sv}",
        "1",
        "options",
        "s",
        "ro",
    ]:
        return
    if method == "Unmount" and tail == ["org.freedesktop.UDisks2.Filesystem", "Unmount", "a{sv}", "0"]:
        return
    if method == "Eject" and interface == "org.freedesktop.UDisks2.Drive" and tail == [
        "org.freedesktop.UDisks2.Drive",
        "Eject",
        "a{sv}",
        "0",
    ]:
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
