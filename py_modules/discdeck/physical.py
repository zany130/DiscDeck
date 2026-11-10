"""Phase 1 physical actions.

Mount is read-only and only for a filesystem UDisks2 already exposed. Eject
requires an explicit confirmation, unmounts that drive first, and stops when
UDisks2 reports busy or unauthorized. Tray close is not attempted.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from discdeck.errors import UnsafeCommand
from discdeck.models import envelope_error, envelope_ok
from discdeck.security import assert_physical_udisks_argv


class GenerationTracker:
    """Session generations. A recycled block node or returning drive gets a new one."""

    def __init__(self) -> None:
        self._seen: dict[str, dict[str, Any]] = {}

    def observe(self, drives: list[dict[str, Any]]) -> None:
        present: set[str] = set()
        for drive in drives:
            drive_id = str(drive["drive_id"])
            present.add(drive_id)
            previous = self._seen.get(drive_id)
            generation = 1
            media_generation = 1
            if previous is not None:
                generation = int(previous["generation"])
                media_generation = int(previous["media_generation"])
                identity_changed = previous.get("absent") or previous.get("block_node") != drive.get("block_node") or previous.get("sysfs_device") != drive.get("sysfs_device")
                if identity_changed:
                    generation += 1
                if previous.get("media_present") != drive.get("media_present"):
                    media_generation += 1
            drive["generation"] = generation
            drive["media_generation"] = media_generation
            drive["generation_tracking"] = "session"
            self._seen[drive_id] = {
                "generation": generation,
                "media_generation": media_generation,
                "block_node": drive.get("block_node"),
                "sysfs_device": drive.get("sysfs_device"),
                "media_present": drive.get("media_present"),
                "absent": False,
            }
        for drive_id, previous in self._seen.items():
            if drive_id not in present:
                previous["absent"] = True


class PhysicalOperations:
    def __init__(self, service: Any) -> None:
        self.service = service
        self.leases: dict[str, str] = {}
        self.owned_mounts: dict[str, dict[str, str]] = {}

    def mount(self, drive_id: str, generation: int, media_generation: int) -> dict[str, Any]:
        drive, error = self._prepare(drive_id, generation, media_generation, "physical_mount")
        if error is not None:
            return error
        assert drive is not None
        if drive.get("media_present") is not True:
            self._release(drive_id)
            return self._error("NOT_READY", "This drive has no mounted-capable media in the current UDisks2 snapshot.")
        if not drive.get("filesystem"):
            self._release(drive_id)
            return self._error("UNSUPPORTED", "UDisks2 did not expose a filesystem. Audio and blank discs are not mounted.")
        block_path = drive.get("udisks_block_path")
        if not isinstance(block_path, str):
            self._release(drive_id)
            return self._error("NOT_READY", "UDisks2 has no block object for this drive.")
        try:
            result, failure, via = self._invoke(mount_argv(block_path), "Mount")
        finally:
            self._release(drive_id)
        if failure is not None or result is None:
            return self._error(*(failure or ("UNSUPPORTED", "Mount did not run.")))
        mount_path = parse_mount_path(result.stdout)
        self.owned_mounts[drive_id] = {"block_path": block_path, "mount_path": mount_path or ""}
        return self._ok(
            {
                "action": "mount",
                "drive_id": drive_id,
                "mount_path": mount_path,
                "read_only": True,
                "hardware_validated": False,
                "via": via,
            }
        )

    def unmount(self, drive_id: str, generation: int) -> dict[str, Any]:
        drive, error = self._prepare(drive_id, generation, None, "physical_mount")
        if error is not None:
            return error
        assert drive is not None
        owned = self.owned_mounts.get(drive_id)
        if owned is None:
            self._release(drive_id)
            return self._error("NOT_READY", "DiscDeck has no mount record for this drive, so it will not unmount a foreign filesystem.")
        try:
            _result, failure, _via = self._invoke(unmount_argv(owned["block_path"]), "Unmount")
        finally:
            self._release(drive_id)
        if failure is not None:
            code, message = failure
            return self._error("UNMOUNT_FAILED" if code not in {"PERMISSION_DENIED", "DRIVE_BUSY"} else code, message)
        self.owned_mounts.pop(drive_id, None)
        return self._ok({"action": "unmount", "drive_id": drive_id, "hardware_validated": False})

    def eject(self, drive_id: str, generation: int, confirmed: bool) -> dict[str, Any]:
        if not confirmed:
            return self._error("CONSENT_REQUIRED", "Eject needs a second confirmation. No UDisks2 method was called.")
        drive, error = self._prepare(drive_id, generation, None, "physical_mount")
        if error is not None:
            return error
        assert drive is not None
        drive_path = drive.get("udisks_drive_path")
        if not isinstance(drive_path, str):
            self._release(drive_id)
            return self._error("NOT_READY", "UDisks2 has no drive object to eject.")
        try:
            owned = self.owned_mounts.get(drive_id)
            mount_points = drive.get("mount_points") or []
            if owned is not None or mount_points:
                block_path = owned["block_path"] if owned is not None else drive.get("udisks_block_path")
                if not isinstance(block_path, str):
                    return self._error("UNMOUNT_FAILED", "A mount is present, but UDisks2 has no block object to unmount before eject.")
                _unmounted, failure, _via = self._invoke(unmount_argv(block_path), "Unmount")
                if failure is not None:
                    code, message = failure
                    return self._error("UNMOUNT_FAILED" if code not in {"PERMISSION_DENIED", "DRIVE_BUSY"} else code, message)
                self.owned_mounts.pop(drive_id, None)
            _ejected, failure, via = self._invoke(eject_argv(drive_path), "Eject")
        finally:
            self._release(drive_id)
        if failure is not None:
            self._log(f"UDisks2 eject failed for {drive.get('block_node')}: {failure[0]} {failure[1]}")
            if failure[0] == "PERMISSION_DENIED":
                fallback = self._user_eject(drive)
                if fallback is None:
                    self._log(f"User eject command succeeded for {drive.get('block_node')}.")
                    return self._ok(
                        {
                            "action": "eject",
                            "drive_id": drive_id,
                            "hardware_validated": False,
                            "via": "user-eject",
                        }
                    )
                self._log(f"User eject command was not successful for {drive.get('block_node')}: {fallback}")
                return self._error("PERMISSION_DENIED", f"{failure[1]} {fallback}")
            return self._error(*failure)
        self._log(f"UDisks2 eject succeeded for {drive.get('block_node')} via {via}.")
        return self._ok({"action": "eject", "drive_id": drive_id, "hardware_validated": False, "via": via})

    def close_tray(self, drive_id: str) -> dict[str, Any]:
        return self._error("UNSUPPORTED", f"Tray close for {drive_id} is TRAY_CLOSE_UNSUPPORTED. No ioctl was issued.")

    def _prepare(
        self,
        drive_id: str,
        generation: int,
        media_generation: int | None,
        reason: str,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        if not isinstance(drive_id, str) or not drive_id:
            return None, self._error("UNSUPPORTED", "drive_id is required.")
        snapshot = self.service.snapshot()
        physical = next((item for item in snapshot["modules"] if item["id"] == "physical"), None)
        if physical is None or physical["effective"] != "active":
            return None, self._error("DEPENDENCY_MISSING", "The physical module is not active, so no mount or eject was attempted.")
        if drive_id in self.leases:
            return None, self._error("DRIVE_BUSY", "This drive already has a DiscDeck operation in progress.")
        drive = next((item for item in snapshot["drives"] if item["drive_id"] == drive_id), None)
        if drive is None:
            return None, self._error("DEVICE_LOST", "That drive is not in the current inventory.")
        if int(drive["generation"]) != int(generation):
            return None, self._error("STALE_DEVICE", "The drive generation changed. Refresh and choose the drive again.")
        if media_generation is not None and int(drive["media_generation"]) != int(media_generation):
            return None, self._error("STALE_MEDIA", "The media generation changed. Refresh before mounting.")
        self.leases[drive_id] = reason
        return drive, None

    def _release(self, drive_id: str) -> None:
        self.leases.pop(drive_id, None)

    def _invoke(self, argv: list[str], action: str) -> tuple[Any, tuple[str, str] | None, str]:
        try:
            result = self.service.mutation_runner(argv, timeout=20)
        except UnsafeCommand as exc:
            return None, ("UNSUPPORTED", str(exc)), "direct"
        failure = _dbus_failure(result, action)
        if failure is None or failure[0] != "PERMISSION_DENIED":
            return result, failure, "direct"
        try:
            retried = self.service.mutation_runner(
                session_argv(argv),
                timeout=25,
                env=session_environment(getattr(self.service, "environ", {}), int(self.service.os_module.geteuid())),
            )
        except UnsafeCommand:
            return result, failure, "direct"
        if retried.code == 127:
            return result, (failure[0], f"{failure[1]} User-session retry did not start."), "direct"
        retry_failure = _dbus_failure(retried, action)
        if retry_failure is None:
            return retried, None, "user-session"
        return retried, retry_failure, "user-session"

    def _user_eject(self, drive: dict[str, Any]) -> str | None:
        node = drive.get("block_node")
        if not isinstance(node, str) or _SR_NODE.fullmatch(node) is None:
            return "The block node is not an sr device, so the eject command was not run."
        access = self.service.access or os.access
        try:
            writable = bool(access(node, os.W_OK))
        except OSError:
            writable = False
        if not writable:
            return "This process cannot write that sr device, so the eject command was not run."
        try:
            result = self.service.mutation_runner(["eject", node], timeout=15)
        except UnsafeCommand as exc:
            return str(exc)
        if result.code == 0:
            return None
        detail = " ".join(f"{result.stderr} {result.stdout}".split())[:180]
        return f"The current user's eject command failed ({result.code}). {detail}".strip()

    def _log(self, message: str) -> None:
        logger = getattr(self.service, "log", None)
        if callable(logger):
            logger(message)

    def _ok(self, result: dict[str, Any]) -> dict[str, Any]:
        self.service.revision += 1
        return envelope_ok(result, self.service.revision, self.service.epoch)

    def _error(self, code: str, message: str) -> dict[str, Any]:
        return envelope_error(code, message, retryable=code in {"DRIVE_BUSY", "STALE_DEVICE", "STALE_MEDIA", "NOT_READY"}, revision=self.service.revision, epoch=self.service.epoch)


_SR_NODE = re.compile(r"/dev/sr[0-9]+")


def session_environment(base: dict[str, str], euid: int) -> dict[str, str]:
    env = dict(base)
    if env.get("XDG_RUNTIME_DIR") or euid <= 0:
        return env
    candidate = Path(f"/run/user/{euid}")
    if candidate.is_dir():
        env["XDG_RUNTIME_DIR"] = str(candidate)
        env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path={candidate}/bus")
    return env


def session_argv(argv: list[str]) -> list[str]:
    wrapped = ["systemd-run", "--user", "--pipe", "--wait", "--collect", "--quiet", *argv]
    assert_physical_udisks_argv(wrapped)
    return wrapped


def mount_argv(block_path: str) -> list[str]:
    argv = [
        "busctl",
        "--system",
        "--no-pager",
        "--allow-interactive-authorization=false",
        "call",
        "org.freedesktop.UDisks2",
        block_path,
        "org.freedesktop.UDisks2.Filesystem",
        "Mount",
        "a{sv}",
        "1",
        "options",
        "s",
        "ro",
    ]
    assert_physical_udisks_argv(argv)
    return argv


def unmount_argv(block_path: str) -> list[str]:
    argv = [
        "busctl",
        "--system",
        "--no-pager",
        "--allow-interactive-authorization=false",
        "call",
        "org.freedesktop.UDisks2",
        block_path,
        "org.freedesktop.UDisks2.Filesystem",
        "Unmount",
        "a{sv}",
        "0",
    ]
    assert_physical_udisks_argv(argv)
    return argv


def eject_argv(drive_path: str) -> list[str]:
    argv = [
        "busctl",
        "--system",
        "--no-pager",
        "--allow-interactive-authorization=false",
        "call",
        "org.freedesktop.UDisks2",
        drive_path,
        "org.freedesktop.UDisks2.Drive",
        "Eject",
        "a{sv}",
        "0",
    ]
    assert_physical_udisks_argv(argv)
    return argv


def parse_mount_path(stdout: str) -> str | None:
    text = stdout.strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, str) and data.startswith("/"):
            return data
        if isinstance(data, list) and data and isinstance(data[0], str) and str(data[0]).startswith("/"):
            return str(data[0])
    for token in text.replace('"', " ").split():
        if token.startswith("/"):
            return token
    return None


def _dbus_failure(result: Any, action: str) -> tuple[str, str] | None:
    if result.code == 0:
        return None
    text = f"{result.stderr}\n{result.stdout}"
    lowered = text.lower()
    if (
        "notauthorized" in lowered
        or "not authorized" in lowered
        or "access denied" in lowered
        or "interactiveauthorization" in lowered
        or "interactive authentication" in lowered
    ):
        detail = " ".join(text.split())[:180]
        return ("PERMISSION_DENIED", f"UDisks2 refused {action}. {detail}".strip())
    if "devicebusy" in lowered or "busy" in lowered:
        return ("DRIVE_BUSY", f"UDisks2 reported the drive busy during {action}.")
    detail = " ".join(text.split())[:240]
    return ("UNSUPPORTED", f"UDisks2 {action} failed ({result.code}). {detail}".strip())
