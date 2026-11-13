"""Load and unload one disc image in the installed CDEmu daemon.

A refresh does not start the daemon. Load starts the cdemu-daemon user
service only after an explicit request, and only when VHBA is already
loaded. DiscDeck unloads a device only when that device still shows the
image this plugin loaded. hardware_validated stays false.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path, PurePosixPath
from typing import Any

from discdeck.adapters.cdemu import probe_cdemu
from discdeck.images import file_identity
from discdeck.models import envelope_error, envelope_ok
from discdeck.physical import session_environment
from discdeck.security import assert_virtual_argv
from discdeck.settings import load_settings

_BUS = "net.sf.cdemu.CDEmuDaemon"
_OBJECT = "/Daemon"
_WRAP = ["systemd-run", "--user", "--pipe", "--wait", "--collect", "--quiet"]
_JSON = ["busctl", "--user", "--no-pager", "--json=short", "call", _BUS, _OBJECT, _BUS]
_CALL = ["busctl", "--user", "--no-pager", "call", _BUS, _OBJECT, _BUS]
_CUE_FILE = re.compile(r'^\s*FILE\s+(?:"([^"\r\n]+)"|([^\s"\r\n]+))\s+\S+', re.IGNORECASE)
_SR = re.compile(r"^/dev/sr[0-9]+$")
_SG = re.compile(r"^/dev/sg[0-9]+$")


def start_daemon_argv() -> list[str]:
    return _checked(["systemctl", "--user", "start", "cdemu-daemon.service"])


def number_argv() -> list[str]:
    return _checked([*_JSON, "GetNumberOfDevices"])


def status_argv(device: int) -> list[str]:
    return _checked([*_JSON, "DeviceGetStatus", "i", str(device)])


def mapping_argv(device: int) -> list[str]:
    return _checked([*_JSON, "DeviceGetMapping", "i", str(device)])


def load_argv(device: int, image: str) -> list[str]:
    return _checked([*_CALL, "DeviceLoad", "isa{sv}", str(device), "1", image, "0"])


def unload_argv(device: int) -> list[str]:
    return _checked([*_CALL, "DeviceUnload", "i", str(device)])


def _checked(argv: list[str]) -> list[str]:
    assert_virtual_argv(argv)
    return argv


def _session_wrap(argv: list[str]) -> list[str]:
    return _checked([*_WRAP, *argv])


def validate_disc_image(raw: str) -> Path:
    path = _existing_file(raw, "The disc image")
    if path.suffix.lower() not in {".iso", ".cue"}:
        raise ValueError("Choose a .cue or a .iso disc image. Other files are not loaded.")
    if path.suffix.lower() == ".cue":
        _cue_targets(path)
    return path


class VirtualDiscs:
    def __init__(self, service: Any) -> None:
        self.service = service
        self._busy = False

    def journal_path(self) -> Path | None:
        raw = self.service.environ.get("DECKY_PLUGIN_SETTINGS_DIR")
        if not raw:
            return None
        return Path(raw) / "state" / "cdemu-slots.json"

    def public_records(self) -> list[dict[str, Any]]:
        records, error = self._load_journal()
        if error or not records:
            return []
        visible: list[dict[str, Any]] = []
        for record in records:
            device = record.get("device_number")
            image = record.get("image_path")
            slot_id = record.get("slot_id")
            if not isinstance(device, int) or not isinstance(image, str) or not isinstance(slot_id, str):
                continue
            state = "not_confirmed"
            sr_device = record.get("sr_device") if isinstance(record.get("sr_device"), str) else None
            sg_device = record.get("sg_device") if isinstance(record.get("sg_device"), str) else None
            status, files = self._status(device)
            if status == "empty":
                state = "unloaded"
                sr_device = None
                sg_device = None
            elif status == "loaded":
                state = "loaded" if image in files else "foreign"
                if state == "loaded":
                    sr_device, sg_device = self._mapping(device)
            visible.append(
                {
                    "slot_id": slot_id,
                    "device_number": device,
                    "image_path": image,
                    "sr_device": sr_device,
                    "sg_device": sg_device,
                    "state": state,
                    "hardware_validated": False,
                }
            )
        return visible

    def load(self, raw_path: str) -> dict[str, Any]:
        if self._busy:
            return self._error("DRIVE_BUSY", "Another virtual disc request is still running.")
        self._busy = True
        try:
            return self._load(raw_path)
        finally:
            self._busy = False

    def unload(self, slot_id: str) -> dict[str, Any]:
        if self._busy:
            return self._error("DRIVE_BUSY", "Another virtual disc request is still running.")
        self._busy = True
        try:
            return self._unload(slot_id)
        finally:
            self._busy = False

    def _load(self, raw_path: str) -> dict[str, Any]:
        if self.journal_path() is None:
            return self._error("NOT_READY", "The plugin settings directory is not set, so a virtual disc cannot be recorded.")
        if not self._enabled():
            return self._error("DEPENDENCY_MISSING", "The virtual disc module is turned off. Nothing was loaded.")
        records, error = self._load_journal()
        if error or records is None:
            return self._error("UNSUPPORTED", error or "The virtual disc journal could not be read.")
        try:
            path = validate_disc_image(raw_path)
        except ValueError as exc:
            return self._error("UNSUPPORTED", str(exc))
        probe = probe_cdemu(
            self.service.runner,
            root=self.service.root,
            sysfs_root=self.service.sysfs_root,
            dev_root=self.service.dev_root,
        )
        if probe["reason_code"] == "CDEMU_MISSING":
            return self._error("DEPENDENCY_MISSING", "CDEmu is not installed. Nothing was loaded.")
        if not probe.get("vhba_loaded"):
            return self._error("DEPENDENCY_MISSING", "VHBA is not loaded. DiscDeck does not load kernel modules.")
        started = False
        if not probe.get("active"):
            result = self._run(start_daemon_argv(), 20)
            if result.code != 0:
                detail = _detail(result)
                return self._error("NOT_READY", f"The CDEmu user service did not start. {detail}".strip())
            started = True
        count, number_result = self._device_count()
        if count is None:
            detail = _detail(number_result) or f"exit {getattr(number_result, 'code', 'unknown')}"
            self._log(f"CDEmu device count failed ({getattr(number_result, 'code', None)}): {detail}")
            return self._error("NOT_READY", f"CDEmu did not report its devices. {detail}".strip())
        if count < 1:
            return self._error("NOT_READY", "CDEmu reported no virtual devices. Nothing was loaded.")
        statuses: list[tuple[str, list[str]]] = []
        for device in range(count):
            statuses.append(self._status(device))
        if any(status == "unavailable" for status, _files in statuses):
            return self._error("NOT_READY", "CDEmu did not report device status. Nothing was loaded.")
        image = str(path)
        for device, (status, files) in enumerate(statuses):
            if status == "loaded" and image in files:
                owned = next((item for item in records if item.get("device_number") == device and item.get("image_path") == image), None)
                if owned is None:
                    return self._error(
                        "DRIVE_BUSY",
                        "That image is already in a CDEmu device DiscDeck did not load. Nothing was changed.",
                    )
                return self._ok(
                    {
                        "action": "load_virtual",
                        "slot_id": owned.get("slot_id"),
                        "device_number": device,
                        "image_path": image,
                        "sr_device": owned.get("sr_device"),
                        "via": "already-loaded",
                        "hardware_validated": False,
                    }
                )
        empty = next((device for device, (status, _files) in enumerate(statuses) if status == "empty"), None)
        if empty is None:
            return self._error("DRIVE_BUSY", "Every CDEmu device already has a disc. Nothing was replaced.")
        loaded = self._run(load_argv(empty, image), 30)
        if loaded.code != 0:
            return self._error("UNSUPPORTED", f"CDEmu did not load the image. {_detail(loaded)}".strip())
        status, files = self._status(empty)
        if status != "loaded" or image not in files:
            return self._error("UNSUPPORTED", "CDEmu did not report that image as loaded. The device was left as CDEmu reported it.")
        sr_device, sg_device = self._mapping(empty)
        record = {
            "slot_id": f"cdemu-{empty}",
            "device_number": empty,
            "image_path": image,
            "identity": file_identity(path),
            "sr_device": sr_device,
            "sg_device": sg_device,
        }
        kept = [
            item
            for item in records
            if item.get("image_path") != image and item.get("device_number") != empty
        ]
        try:
            self._store([*kept, record])
        except OSError as exc:
            return self._error(
                "UNSUPPORTED",
                f"CDEmu loaded the image on device {empty}, but the ownership record could not be saved. {exc}",
            )
        self._log(f"CDEmu device {empty} loaded {image}")
        return self._ok(
            {
                "action": "load_virtual",
                "slot_id": record["slot_id"],
                "device_number": empty,
                "image_path": image,
                "sr_device": sr_device,
                "sg_device": sg_device,
                "via": "started" if started else "already-active",
                "hardware_validated": False,
            }
        )

    def _unload(self, slot_id: str) -> dict[str, Any]:
        if not isinstance(slot_id, str) or slot_id == "":
            return self._error("UNSUPPORTED", "The virtual disc id is missing. Nothing was unloaded.")
        if self.journal_path() is None:
            return self._error("NOT_READY", "The plugin settings directory is not set, so no virtual disc record can be checked.")
        records, error = self._load_journal()
        if error or records is None:
            return self._error("UNSUPPORTED", error or "The virtual disc journal could not be read.")
        record = next((item for item in records if item.get("slot_id") == slot_id), None)
        if record is None:
            return self._error("UNSUPPORTED", "DiscDeck does not own that virtual disc. Nothing was unloaded.")
        device = record.get("device_number")
        image = record.get("image_path")
        if not isinstance(device, int) or not isinstance(image, str):
            return self._error("UNSUPPORTED", "The virtual disc record is incomplete. Nothing was unloaded.")
        status, files = self._status(device)
        if status == "unavailable":
            return self._error("NOT_READY", "CDEmu did not answer, so the device was not unloaded.")
        remaining = [item for item in records if item.get("slot_id") != slot_id]
        if status == "empty":
            self._store(remaining)
            return self._ok({"action": "unload_virtual", "slot_id": slot_id, "via": "already-gone", "hardware_validated": False})
        if image not in files:
            return self._error("UNSUPPORTED", "The disc in that device does not match the DiscDeck record. It was not unloaded.")
        path = Path(image)
        if path.exists() and not path.is_symlink() and file_identity(path) != record.get("identity"):
            return self._error("UNSUPPORTED", "The image file changed since DiscDeck loaded it. It was not unloaded.")
        result = self._run(unload_argv(device), 20)
        if result.code != 0:
            return self._error("UNSUPPORTED", f"CDEmu did not unload the device. {_detail(result)}".strip())
        self._store(remaining)
        self._log(f"CDEmu device {device} unloaded")
        return self._ok({"action": "unload_virtual", "slot_id": slot_id, "device_number": device, "hardware_validated": False})

    def _device_count(self) -> tuple[int | None, Any]:
        last = None
        for attempt in range(8):
            last = self._run(number_argv(), 10, expect_body=True)
            count = _number(last)
            if count is not None:
                return count, last
            if attempt == 7 or not _daemon_not_ready(last):
                return None, last
            time.sleep(0.5)
        return None, last

    def _status(self, device: int) -> tuple[str, list[str]]:
        result = self._run(status_argv(device), 10, expect_body=True)
        parsed = _json_data(result)
        if result.code != 0 or not isinstance(parsed, list) or len(parsed) < 2 or not isinstance(parsed[0], bool):
            return "unavailable", []
        files = [item for item in parsed[1] if isinstance(item, str)] if isinstance(parsed[1], list) else []
        if parsed[0]:
            return "loaded", files
        return "empty", files

    def _mapping(self, device: int) -> tuple[str | None, str | None]:
        result = self._run(mapping_argv(device), 10, expect_body=True)
        parsed = _json_data(result)
        if result.code != 0 or not isinstance(parsed, list) or len(parsed) < 2:
            return None, None
        sr_device = parsed[0] if isinstance(parsed[0], str) and _SR.fullmatch(parsed[0]) else None
        sg_device = parsed[1] if isinstance(parsed[1], str) and _SG.fullmatch(parsed[1]) else None
        return sr_device, sg_device

    def _enabled(self) -> bool:
        directory = self.service.environ.get("DECKY_PLUGIN_SETTINGS_DIR")
        path = Path(directory) / "settings.json" if directory else None
        modules = load_settings(path)["settings"]["modules"]
        return modules.get("virtual.cdemu") is not False

    def _run(self, argv: list[str], timeout: float, *, expect_body: bool = False) -> Any:
        """Call the user bus directly. A session unit is only the fallback when that bus is unreachable."""
        env = session_environment(self.service.environ, self._euid())
        direct = argv[len(_WRAP) :] if argv[: len(_WRAP)] == _WRAP else list(argv)
        first = self.service.virtual_runner(direct, timeout=timeout, env=env)
        if _good(first, expect_body=expect_body):
            return first
        if not _worth_session_retry(first, expect_body=expect_body):
            return first
        second = self.service.virtual_runner(_session_wrap(direct), timeout=timeout, env=env)
        if _good(second, expect_body=expect_body):
            return second
        return first if _detail(first) else second

    def _euid(self) -> int:
        getter = getattr(self.service.os_module, "geteuid", None)
        if callable(getter):
            return int(getter())
        return os.geteuid()

    def _load_journal(self) -> tuple[list[dict[str, Any]] | None, str | None]:
        path = self.journal_path()
        if path is None or not path.is_file():
            return [], None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None, "The virtual disc journal could not be read. It was not replaced."
        if not isinstance(payload, dict) or payload.get("schema_version") != 1 or not isinstance(payload.get("records"), list):
            return None, "The virtual disc journal has an unknown shape. It was not replaced."
        records: list[dict[str, Any]] = []
        for item in payload["records"]:
            if not isinstance(item, dict):
                return None, "The virtual disc journal has an unknown shape. It was not replaced."
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


def _existing_file(raw: str, label: str) -> Path:
    if not isinstance(raw, str) or raw == "" or "\x00" in raw or "\n" in raw:
        raise ValueError(f"{label} path is empty or contains unsupported characters.")
    path = Path(raw)
    if not path.is_absolute():
        raise ValueError(f"{label} path must be absolute.")
    current = Path(path.anchor)
    for part in path.parts[1:]:
        if part in {"", ".", ".."}:
            raise ValueError(f"{label} path contains a parent segment.")
        current = current / part
        if current.is_symlink():
            raise ValueError(f"{label} path contains a symlink. DiscDeck will not follow it.")
    if not current.is_file():
        raise ValueError(f"{label} path is not a regular file.")
    return current


def _cue_targets(cue: Path) -> list[Path]:
    try:
        text = cue.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise ValueError(f"The cue sheet could not be read. {exc}") from exc
    targets: list[Path] = []
    for line in text[:1_048_576].splitlines():
        match = _CUE_FILE.match(line)
        if match is None:
            continue
        raw = match.group(1) if match.group(1) is not None else match.group(2)
        if raw.startswith("/"):
            target = _existing_file(raw, "A cue sheet")
        else:
            if any(part in {"", ".", ".."} for part in PurePosixPath(raw).parts):
                raise ValueError("The cue sheet names a parent path. DiscDeck will not follow it.")
            target = _existing_file(str(cue.parent.joinpath(*PurePosixPath(raw).parts)), "A cue sheet")
        if target not in targets:
            targets.append(target)
    return targets


def _json_data(result: Any) -> Any:
    try:
        payload = json.loads(result.stdout)
    except (json.JSONDecodeError, AttributeError):
        return None
    if isinstance(payload, dict):
        return payload.get("data")
    return None


def _number(result: Any) -> int | None:
    if getattr(result, "code", 1) != 0:
        return None
    data = _json_data(result)
    if isinstance(data, bool):
        return None
    if isinstance(data, int) and data >= 0:
        return data
    if isinstance(data, list) and len(data) == 1 and isinstance(data[0], int) and not isinstance(data[0], bool) and data[0] >= 0:
        return data[0]
    text = str(getattr(result, "stdout", "")).strip()
    match = re.fullmatch(r"(?:i\s+)?([0-9]+)", text)
    if match:
        return int(match.group(1))
    return None


def _good(result: Any, *, expect_body: bool) -> bool:
    if getattr(result, "code", 1) != 0:
        return False
    if expect_body and not str(getattr(result, "stdout", "")).strip():
        return False
    return True


def _worth_session_retry(result: Any, *, expect_body: bool) -> bool:
    if getattr(result, "code", 1) == 127:
        return True
    if expect_body and getattr(result, "code", 1) == 0 and not str(getattr(result, "stdout", "")).strip():
        return True
    text = _detail(result).lower()
    return "failed to connect to bus" in text or "no medium found" in text or "no such file or directory" in text


def _daemon_not_ready(result: Any) -> bool:
    if getattr(result, "code", 1) == 0 and not str(getattr(result, "stdout", "")).strip():
        return True
    text = _detail(result).lower()
    return any(phrase in text for phrase in ("no such name", "not provided", "not activatable", "no owner", "service unknown", "was not provided"))


def _detail(result: Any) -> str:
    text = f"{getattr(result, 'stderr', '')}\n{getattr(result, 'stdout', '')}"
    return " ".join(text.split())[:240]
