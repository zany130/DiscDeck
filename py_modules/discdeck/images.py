"""Read-only filesystem images through UDisks2 LoopSetup.

An ISO loop is a file mount. It is not a virtual optical drive and it does not
call CDEmu. DiscDeck records only the loops it created and deletes one only
when the live object still matches that record.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from discdeck.models import envelope_error, envelope_ok
from discdeck.physical import (
    _dbus_failure,
    mount_argv,
    parse_mount_path,
    session_argv,
    session_environment,
    unmount_argv,
)
from discdeck.security import assert_physical_udisks_argv

_LOOP_OBJECT = re.compile(r"/org/freedesktop/UDisks2/block_devices/loop[0-9]+")
_LOOP_NODE = re.compile(r"/dev/loop[0-9]+")
_GONE = ("unknown object", "unknownobject", "no such object", "does not exist")


class OsOpener:
    def open(self, path: Path) -> int:
        return os.open(path, os.O_RDONLY | os.O_CLOEXEC)

    def close(self, fd: int) -> None:
        os.close(fd)


def validate_iso(raw: str) -> Path:
    if not isinstance(raw, str) or raw == "" or "\x00" in raw or "\n" in raw:
        raise ValueError("The image path is empty or contains unsupported characters.")
    path = Path(raw)
    if not path.is_absolute():
        raise ValueError("The image path must be absolute.")
    current = Path(path.anchor)
    for part in path.parts[1:]:
        if part in {"", ".", ".."}:
            raise ValueError("The image path contains a parent segment.")
        current = current / part
        if current.is_symlink():
            raise ValueError("The image path contains a symlink. DiscDeck will not follow it.")
    if not current.is_file():
        raise ValueError("The image path is not a regular file.")
    if current.suffix.lower() != ".iso":
        raise ValueError("Only a .iso filesystem image can be mounted here. Disc images for CDEmu are not mounted.")
    return current


def file_identity(path: Path) -> str:
    stat = path.stat()
    return f"{stat.st_dev}:{stat.st_ino}:{stat.st_size}:{stat.st_mtime_ns}"


def loop_setup_argv(fd: int) -> list[str]:
    argv = [
        "busctl",
        "--system",
        "--no-pager",
        "--allow-interactive-authorization=false",
        "call",
        "org.freedesktop.UDisks2",
        "/org/freedesktop/UDisks2/Manager",
        "org.freedesktop.UDisks2.Manager",
        "LoopSetup",
        "ha{sv}",
        str(fd),
        "1",
        "read-only",
        "b",
        "true",
    ]
    assert_physical_udisks_argv(argv)
    return argv


def loop_delete_argv(loop_path: str) -> list[str]:
    argv = [
        "busctl",
        "--system",
        "--no-pager",
        "--allow-interactive-authorization=false",
        "call",
        "org.freedesktop.UDisks2",
        loop_path,
        "org.freedesktop.UDisks2.Loop",
        "Delete",
        "a{sv}",
        "0",
    ]
    assert_physical_udisks_argv(argv)
    return argv


def backing_argv(loop_path: str) -> list[str]:
    argv = [
        "busctl",
        "--system",
        "--no-pager",
        "get-property",
        "org.freedesktop.UDisks2",
        loop_path,
        "org.freedesktop.UDisks2.Loop",
        "BackingFile",
    ]
    assert_physical_udisks_argv(argv)
    return argv


def udisksctl_setup_argv(path: str) -> list[str]:
    argv = ["udisksctl", "loop-setup", "-f", path, "-r"]
    assert_physical_udisks_argv(argv)
    return argv


def udisksctl_delete_argv(node: str) -> list[str]:
    argv = ["udisksctl", "loop-delete", "-b", node]
    assert_physical_udisks_argv(argv)
    return argv


def parse_loop_object(stdout: str) -> str | None:
    text = stdout.strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, str):
            match = _LOOP_OBJECT.search(data)
            if match:
                return match.group(0)
    match = _LOOP_OBJECT.search(text)
    if match:
        return match.group(0)
    node = _LOOP_NODE.search(text)
    if node:
        name = node.group(0).rsplit("/", 1)[-1]
        return f"/org/freedesktop/UDisks2/block_devices/{name}"
    return None


def parse_backing(stdout: str) -> str | None:
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
            return data.split("\0", 1)[0]
        if isinstance(data, list) and all(isinstance(item, int) for item in data):
            path = _path_from_bytes(data)
            if path:
                return path
    numbers = [int(token) for token in text.split() if token.isdigit()]
    path = _path_from_bytes(numbers)
    if path:
        return path
    for token in text.replace('"', " ").split():
        if token.startswith("/") and not token.startswith("/org/"):
            return token.split("\0", 1)[0]
    return None


def _path_from_bytes(numbers: list[int]) -> str | None:
    if not numbers:
        return None
    raw = bytes(number for number in numbers if 0 <= number <= 255)
    text = raw.split(b"\0", 1)[0].decode("utf-8", "replace")
    if text.startswith("/"):
        return text
    if len(numbers) > 1:
        return _path_from_bytes(numbers[1:])
    return None


class ImageLibrary:
    def __init__(self, service: Any, opener: Any | None = None) -> None:
        self.service = service
        self.opener = opener or OsOpener()
        self._busy = False

    def journal_path(self) -> Path | None:
        raw = self.service.environ.get("DECKY_PLUGIN_SETTINGS_DIR")
        if not raw:
            return None
        return Path(raw) / "state" / "iso-ownership.json"

    def public_records(self) -> list[dict[str, Any]]:
        records, error = self._load()
        if error or records is None:
            return []
        visible: list[dict[str, Any]] = []
        for record in records:
            visible.append(
                {
                    "image_id": record.get("image_id"),
                    "backing_path": record.get("backing_path"),
                    "mount_path": record.get("mount_path") or "",
                    "loop_object_path": record.get("loop_object_path"),
                    "read_only": record.get("read_only") is True,
                    "hardware_validated": False,
                }
            )
        return visible

    def mount(self, raw_path: str) -> dict[str, Any]:
        if self._busy:
            return self._error("DRIVE_BUSY", "Another filesystem image request is still running.")
        self._busy = True
        try:
            return self._mount(raw_path)
        finally:
            self._busy = False

    def unmount(self, image_id: str) -> dict[str, Any]:
        if self._busy:
            return self._error("DRIVE_BUSY", "Another filesystem image request is still running.")
        self._busy = True
        try:
            return self._unmount(image_id)
        finally:
            self._busy = False

    def _mount(self, raw_path: str) -> dict[str, Any]:
        if self.journal_path() is None:
            return self._error("NOT_READY", "The plugin settings directory is not set, so an ISO cannot be recorded.")
        records, error = self._load()
        if error or records is None:
            return self._error("UNSUPPORTED", error or "The ISO ownership journal could not be read.")
        try:
            path = validate_iso(raw_path)
        except ValueError as exc:
            return self._error("UNSUPPORTED", str(exc))
        if records:
            return self._error("DRIVE_BUSY", "DiscDeck already has a filesystem image mounted. Unmount that image first.")
        try:
            snapshot = self.service.snapshot()
        except Exception as exc:  # noqa: BLE001 - boundary keeps a probe failure inside the envelope
            return self._error("INTERNAL_ERROR", str(exc))
        module = next((item for item in snapshot["modules"] if item["id"] == "images.iso"), None)
        if module is None or module.get("effective") != "active":
            return self._error("DEPENDENCY_MISSING", "UDisks2 is not available for a filesystem image. Nothing was mounted.")
        identity = file_identity(path)
        image_id = hashlib.sha256(f"{path}\n{identity}".encode()).hexdigest()[:16]
        try:
            fd = self.opener.open(path)
        except OSError as exc:
            return self._error("UNSUPPORTED", f"The ISO could not be opened. {exc}")
        try:
            setup = self.service.mutation_runner(loop_setup_argv(fd), timeout=20, pass_fds=(fd,))
        finally:
            self.opener.close(fd)
        loop_path, failure, via = self._loop_from_setup(setup, path)
        if failure or not loop_path:
            self._log(f"ISO LoopSetup failed: {failure}")
            return self._error(failure[0] if failure else "UNSUPPORTED", failure[1] if failure else "LoopSetup did not name a loop device.")
        mounted = self._run_with_session(mount_argv(loop_path), 20)
        mount_failure = _dbus_failure(mounted, "Mount")
        mount_path = "" if mount_failure else (parse_mount_path(mounted.stdout) or "")
        record = {
            "image_id": image_id,
            "loop_object_path": loop_path,
            "filesystem_object_path": loop_path,
            "backing_path": str(path),
            "backing_identity": identity,
            "mount_path": mount_path,
            "session_epoch": self.service.epoch,
            "read_only": True,
            "via": via,
        }
        if mount_failure:
            removed, detail = self._delete_loop(loop_path)
            self._log(f"ISO mount failed for {loop_path}: {mount_failure}")
            if removed:
                return self._error(mount_failure[0], mount_failure[1])
            try:
                self._store([record])
            except OSError:
                detail = f"{detail} The ownership record could not be saved."
            return self._error(
                mount_failure[0],
                f"{mount_failure[1]} The loop {loop_path} could not be removed. {detail}",
            )
        try:
            self._store([record])
        except OSError as exc:
            removed, detail = self._release(loop_path)
            extra = "" if removed else f" The loop {loop_path} could not be removed. {detail}"
            return self._error("UNSUPPORTED", f"The ISO mounted, but the ownership record could not be saved.{extra} {exc}")
        self._log(f"ISO mounted read-only via {via}: {loop_path}")
        return self._ok(
            {
                "action": "mount_iso",
                "image_id": image_id,
                "mount_path": mount_path,
                "loop_object_path": loop_path,
                "backing_path": str(path),
                "read_only": True,
                "hardware_validated": False,
                "via": via,
            }
        )

    def _unmount(self, image_id: str) -> dict[str, Any]:
        if self.journal_path() is None:
            return self._error("NOT_READY", "The plugin settings directory is not set, so no ISO record can be checked.")
        records, error = self._load()
        if error or records is None:
            return self._error("UNSUPPORTED", error or "The ISO ownership journal could not be read.")
        record = next((item for item in records if item.get("image_id") == image_id), None)
        if record is None:
            return self._error("UNSUPPORTED", "DiscDeck does not own that filesystem image. No loop was deleted.")
        loop_path = str(record.get("loop_object_path") or "")
        if _LOOP_OBJECT.fullmatch(loop_path) is None:
            return self._error("UNSUPPORTED", "The ownership record does not name a loop device. Nothing was deleted.")
        status, backing = self._read_backing(loop_path)
        if status == "gone":
            self._store([item for item in records if item.get("image_id") != image_id])
            return self._ok({"action": "unmount_iso", "image_id": image_id, "hardware_validated": False, "via": "already-gone"})
        if status != "ok":
            return self._error("UNSUPPORTED", "The live loop could not be checked, so it was not unmounted or deleted.")
        if backing != record.get("backing_path"):
            return self._error(
                "UNSUPPORTED",
                "The live loop does not match the DiscDeck record. It was not unmounted or deleted.",
            )
        path = Path(str(record.get("backing_path")))
        if path.exists() and not path.is_symlink() and file_identity(path) != record.get("backing_identity"):
            return self._error(
                "UNSUPPORTED",
                "The ISO file changed since DiscDeck mounted it. The loop was not deleted.",
            )
        filesystem = str(record.get("filesystem_object_path") or loop_path)
        unmounted = self._run_with_session(unmount_argv(filesystem), 20)
        if unmounted.code != 0 and not _not_mounted(unmounted):
            failure = _dbus_failure(unmounted, "Unmount")
            return self._error("UNMOUNT_FAILED", failure[1] if failure else "UDisks2 did not unmount the filesystem image.")
        removed, detail = self._delete_loop(loop_path)
        if not removed:
            return self._error("UNSUPPORTED", f"The filesystem was unmounted, but the loop was not removed. {detail}")
        self._store([item for item in records if item.get("image_id") != image_id])
        self._log(f"ISO unmounted and loop removed: {loop_path}")
        return self._ok({"action": "unmount_iso", "image_id": image_id, "hardware_validated": False, "via": "loop-delete"})

    def _loop_from_setup(self, setup: Any, path: Path) -> tuple[str | None, tuple[str, str] | None, str]:
        failure = _dbus_failure(setup, "LoopSetup")
        if failure is None:
            loop_path = parse_loop_object(setup.stdout)
            if loop_path:
                return loop_path, None, "busctl"
            return None, ("UNSUPPORTED", "LoopSetup succeeded without naming a loop device."), "busctl"
        if failure[0] != "PERMISSION_DENIED":
            return None, failure, "busctl"
        ctl = self._run_user_tool(udisksctl_setup_argv(str(path)), 25)
        ctl_failure = _dbus_failure(ctl, "LoopSetup")
        if ctl_failure:
            return None, ctl_failure, "udisksctl"
        loop_path = parse_loop_object(ctl.stdout)
        if not loop_path:
            return None, ("UNSUPPORTED", "udisksctl did not name a loop device."), "udisksctl"
        return loop_path, None, "udisksctl"

    def _read_backing(self, loop_path: str) -> tuple[str, str | None]:
        result = self._run_with_session(backing_argv(loop_path), 10)
        if result.code == 127:
            return "error", "The backing-file read did not run."
        if result.code != 0:
            text = f"{result.stderr}\n{result.stdout}".lower()
            if any(marker in text for marker in _GONE):
                return "gone", None
            return "error", "The backing file could not be read."
        backing = parse_backing(result.stdout)
        if not backing:
            return "error", "BackingFile was not a path."
        return "ok", backing

    def _delete_loop(self, loop_path: str) -> tuple[bool, str]:
        result = self._run_with_session(loop_delete_argv(loop_path), 20)
        if result.code == 0:
            return True, ""
        name = loop_path.rsplit("/", 1)[-1]
        node = f"/dev/{name}"
        if _LOOP_NODE.fullmatch(node) is None:
            return False, "The object path was not a loop device."
        ctl = self._run_user_tool(udisksctl_delete_argv(node), 20)
        if ctl.code == 0:
            return True, ""
        detail = " ".join(f"{result.stderr} {ctl.stderr}".split())[:180]
        return False, detail or "The loop could not be removed."

    def _release(self, loop_path: str) -> tuple[bool, str]:
        unmounted = self._run_with_session(unmount_argv(loop_path), 20)
        if unmounted.code != 0 and not _not_mounted(unmounted):
            failure = _dbus_failure(unmounted, "Unmount")
            return False, failure[1] if failure else "The filesystem could not be unmounted."
        return self._delete_loop(loop_path)

    def _run_with_session(self, argv: list[str], timeout: float) -> Any:
        result = self.service.mutation_runner(argv, timeout=timeout)
        failure = _dbus_failure(result, "call")
        if failure is None or failure[0] != "PERMISSION_DENIED":
            return result
        retried = self.service.mutation_runner(
            session_argv(argv),
            timeout=timeout + 5,
            env=session_environment(self.service.environ, self._euid()),
        )
        if retried.code == 127:
            return result
        return retried

    def _run_user_tool(self, argv: list[str], timeout: float) -> Any:
        result = self.service.mutation_runner(
            session_argv(argv),
            timeout=timeout,
            env=session_environment(self.service.environ, self._euid()),
        )
        if result.code == 127:
            return self.service.mutation_runner(argv, timeout=timeout)
        return result

    def _euid(self) -> int:
        getter = getattr(self.service.os_module, "geteuid", None)
        if callable(getter):
            return int(getter())
        return os.geteuid()

    def _load(self) -> tuple[list[dict[str, Any]] | None, str | None]:
        path = self.journal_path()
        if path is None or not path.is_file():
            return [], None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None, "The ISO ownership journal could not be read. It was not replaced."
        if not isinstance(payload, dict) or payload.get("schema_version") != 1 or not isinstance(payload.get("records"), list):
            return None, "The ISO ownership journal has an unknown shape. It was not replaced."
        records: list[dict[str, Any]] = []
        for item in payload["records"]:
            if not isinstance(item, dict):
                return None, "The ISO ownership journal has an unknown shape. It was not replaced."
            records.append(item)
        return records, None

    def _store(self, records: list[dict[str, Any]]) -> None:
        path = self.journal_path()
        if path is None:
            raise OSError("The plugin settings directory is not set.")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump({"schema_version": 1, "records": records}, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)

    def _ok(self, result: dict[str, Any]) -> dict[str, Any]:
        self.service.revision += 1
        return envelope_ok(result, self.service.revision, self.service.epoch)

    def _error(self, code: str, message: str) -> dict[str, Any]:
        return envelope_error(
            code,
            message,
            retryable=code in {"DRIVE_BUSY", "NOT_READY"},
            revision=self.service.revision,
            epoch=self.service.epoch,
        )

    def _log(self, message: str) -> None:
        logger = getattr(self.service, "log", None)
        if callable(logger):
            logger(message)


def _not_mounted(result: Any) -> bool:
    text = f"{result.stderr}\n{result.stdout}".lower()
    return "not mounted" in text or "notmounted" in text
