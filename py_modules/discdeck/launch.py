"""Ask Steam to start one shortcut that is already in the user's Steam config.

DiscDeck reads shortcut names and does not create shortcuts, edit them, or
open a Proton prefix. Autoplay stays off. hardware_validated stays false.
"""

from __future__ import annotations

import re
import zlib
from pathlib import Path
from typing import Any

from discdeck.adapters.steam import find_steam_binary, steam_directories
from discdeck.models import envelope_error, envelope_ok
from discdeck.security import assert_launch_argv

_RUNGAME = re.compile(r"[0-9]{1,20}")
_MAX_SHORTCUTS = 100
_MAX_BYTES = 1024 * 1024
_NON_STEAM = 0x02000000


def launch_argv(steam_binary: str, rungameid: str) -> list[str]:
    argv = [steam_binary, f"steam://rungameid/{rungameid}"]
    assert_launch_argv(argv)
    return argv


def app_id(exe: str, app_name: str) -> int:
    digest = zlib.crc32(f"{exe}{app_name}".encode("utf-8")) & 0xFFFFFFFF
    return digest | 0x80000000


def format_rungameid(appid: int) -> str:
    return str(((appid & 0xFFFFFFFF) << 32) | _NON_STEAM)


def list_shortcuts(home: Path | None) -> dict[str, Any]:
    shortcuts: list[dict[str, str]] = []
    seen: set[str] = set()
    opened = False
    reads: list[str] = []
    if home is None:
        return {"shortcuts": shortcuts, "opened": False, "files_read": reads}
    for root in steam_directories(home):
        userdata = root / "userdata"
        if not userdata.is_dir() or userdata.is_symlink():
            continue
        try:
            accounts = sorted(userdata.iterdir(), key=lambda item: item.name)
        except OSError:
            continue
        for account in accounts:
            if account.is_symlink() or not account.is_dir():
                continue
            config = account / "config"
            if config.is_symlink() or not config.is_dir():
                continue
            target = config / "shortcuts.vdf"
            if target.is_symlink() or not target.is_file():
                continue
            opened = True
            reads.append(str(target))
            for item in _read_file(target):
                if item["rungameid"] in seen:
                    continue
                seen.add(item["rungameid"])
                shortcuts.append(item)
                if len(shortcuts) >= _MAX_SHORTCUTS:
                    return {"shortcuts": shortcuts, "opened": True, "files_read": reads}
    return {"shortcuts": shortcuts, "opened": opened, "files_read": reads}


class ShortcutLaunch:
    def __init__(self, service: Any) -> None:
        self.service = service

    def launch(self, rungameid: str) -> dict[str, Any]:
        if not isinstance(rungameid, str) or _RUNGAME.fullmatch(rungameid) is None:
            return self._error("UNSUPPORTED", "The Steam shortcut id is missing. Nothing was launched.")
        listed = list_shortcuts(self.service.home)
        match = next((item for item in listed["shortcuts"] if item["rungameid"] == rungameid), None)
        if match is None:
            return self._error("UNSUPPORTED", "That Steam shortcut is not in the current list. Nothing was launched.")
        binary = find_steam_binary(self.service.environ, self.service.root)
        if binary is None:
            return self._error("NOT_READY", "Steam was not found. Nothing was launched.")
        try:
            argv = launch_argv(binary, rungameid)
        except Exception as exc:  # noqa: BLE001 - policy failures become a refusal
            return self._error("UNSUPPORTED", f"Steam was not started. {exc}")
        self._log(f"Steam launch requested for {match['app_name']} ({rungameid}).")
        result = self.service.launch_runner(argv, timeout=20)
        if getattr(result, "code", 1) != 0:
            detail = " ".join(f"{getattr(result, 'stderr', '')}\n{getattr(result, 'stdout', '')}".split())[:240]
            self._log(f"Steam launch failed ({getattr(result, 'code', None)}): {detail}")
            return self._error("UNSUPPORTED", f"Steam did not accept the shortcut. {detail}".strip())
        self._log(f"Steam was asked to launch {match['app_name']}.")
        return self._ok(
            {
                "action": "launch_shortcut",
                "app_name": match["app_name"],
                "rungameid": rungameid,
                "hardware_validated": False,
            }
        )

    def _ok(self, result: dict[str, Any]) -> dict[str, Any]:
        self.service.revision += 1
        return envelope_ok(result, self.service.revision, self.service.epoch)

    def _error(self, code: str, message: str) -> dict[str, Any]:
        return envelope_error(
            code,
            message,
            retryable=code == "NOT_READY",
            revision=self.service.revision,
            epoch=self.service.epoch,
        )

    def _log(self, message: str) -> None:
        logger = getattr(self.service, "log", None)
        if callable(logger):
            logger(message)


def _read_file(path: Path) -> list[dict[str, str]]:
    try:
        if path.stat().st_size > _MAX_BYTES:
            return []
        data = path.read_bytes()
    except OSError:
        return []
    return _shortcuts_from(data)


def _shortcuts_from(data: bytes) -> list[dict[str, str]]:
    if not data or data[0] != 0x00:
        return []
    cursor = _Cursor(data)
    kind = cursor.byte()
    name = cursor.cstring()
    if kind != 0x00 or name is None:
        return []
    root = cursor.object(depth=0)
    if root is None:
        return []
    found: list[dict[str, str]] = []
    _collect(root, found)
    return found


def _collect(node: dict[str, Any], found: list[dict[str, str]]) -> None:
    shortcut = _one_shortcut(node["fields"])
    if shortcut is not None:
        found.append(shortcut)
    for child in node["children"]:
        _collect(child, found)


def _one_shortcut(fields: dict[str, Any]) -> dict[str, str] | None:
    app_name = fields.get("AppName")
    exe = fields.get("Exe")
    stored = fields.get("appid")
    if isinstance(stored, int) and stored != 0:
        numeric = stored & 0xFFFFFFFF
    elif isinstance(app_name, str) and isinstance(exe, str) and app_name and exe:
        numeric = app_id(exe, app_name)
    else:
        return None
    name = _display_name(app_name if isinstance(app_name, str) else "")
    return {"app_name": name, "rungameid": format_rungameid(numeric)}


def _display_name(value: str) -> str:
    cleaned = " ".join(value.replace("\x00", " ").split())
    if not cleaned:
        return "Steam shortcut"
    return cleaned[:80]


class _Cursor:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.index = 0

    def byte(self) -> int | None:
        if self.index >= len(self.data):
            return None
        value = self.data[self.index]
        self.index += 1
        return value

    def cstring(self) -> str | None:
        end = self.data.find(b"\x00", self.index)
        if end < 0:
            return None
        raw = self.data[self.index : end]
        self.index = end + 1
        return raw.decode("utf-8", errors="replace")

    def u32(self) -> int | None:
        if self.index + 4 > len(self.data):
            return None
        value = int.from_bytes(self.data[self.index : self.index + 4], "little")
        self.index += 4
        return value

    def object(self, depth: int) -> dict[str, Any] | None:
        if depth > 6:
            return None
        fields: dict[str, Any] = {}
        children: list[dict[str, Any]] = []
        while True:
            kind = self.byte()
            if kind is None:
                return None
            if kind == 0x08:
                return {"fields": fields, "children": children}
            name = self.cstring()
            if name is None:
                return None
            if kind == 0x00:
                child = self.object(depth + 1)
                if child is None:
                    return None
                children.append(child)
            elif kind == 0x01:
                value = self.cstring()
                if value is None:
                    return None
                fields[name] = value
            elif kind == 0x02:
                value = self.u32()
                if value is None:
                    return None
                fields[name] = value
            else:
                return None
