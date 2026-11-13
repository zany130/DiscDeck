"""Decky identity and directory probe.

Values come from the process environment and the password database. No
username, UID, home directory, or bus path is assumed.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

DECKY_CONSTANTS = (
    "HOME",
    "USER",
    "DECKY_VERSION",
    "DECKY_USER",
    "DECKY_USER_HOME",
    "DECKY_HOME",
    "DECKY_PLUGIN_SETTINGS_DIR",
    "DECKY_PLUGIN_RUNTIME_DIR",
    "DECKY_PLUGIN_LOG_DIR",
    "DECKY_PLUGIN_DIR",
    "DECKY_PLUGIN_NAME",
    "DECKY_PLUGIN_VERSION",
    "DECKY_PLUGIN_AUTHOR",
    "DECKY_PLUGIN_LOG",
)

DIRECTORY_CONSTANTS = {
    "settings": "DECKY_PLUGIN_SETTINGS_DIR",
    "runtime": "DECKY_PLUGIN_RUNTIME_DIR",
    "log": "DECKY_PLUGIN_LOG_DIR",
    "plugin": "DECKY_PLUGIN_DIR",
}


def drop_privileges(os_module: Any, pwd_module: Any, environ: dict[str, str]) -> dict[str, Any]:
    """Drop to ``DECKY_USER`` only when the process is unexpectedly root.

    The plugin metadata does not request root. If a host still starts the
    backend as UID 0, Phase 0 drops to the named Decky owner when that
    account resolves to a non-root UID. It never guesses UID 1000.
    """

    euid = os_module.geteuid()
    result: dict[str, Any] = {
        "effective_uid_before": euid,
        "dropped": False,
        "status": "already_unprivileged",
        "error": None,
    }
    if euid != 0:
        return result
    user = environ.get("DECKY_USER") or ""
    if not user or user == "root":
        result["status"] = "unverified"
        result["error"] = "PRIVILEGE_DROP_UNVERIFIED"
        return result
    try:
        account = pwd_module.getpwnam(user)
    except KeyError:
        result["status"] = "unverified"
        result["error"] = "PRIVILEGE_DROP_UNVERIFIED"
        return result
    if account.pw_uid == 0:
        result["status"] = "refused_root_target"
        result["error"] = "PRIVILEGE_DROP_UNVERIFIED"
        return result
    os_module.setgid(account.pw_gid)
    os_module.setuid(account.pw_uid)
    result["dropped"] = os_module.geteuid() == account.pw_uid and os_module.getegid() == account.pw_gid
    result["status"] = "dropped" if result["dropped"] else "failed"
    if not result["dropped"]:
        result["error"] = "PRIVILEGE_DROP_FAILED"
    return result


def read_plugin_flags(plugin_dir: str | None) -> dict[str, Any]:
    if not plugin_dir:
        return {"flags": [], "root_requested": False, "status": "plugin_dir_unset"}
    path = Path(plugin_dir) / "plugin.json"
    if not path.is_file():
        return {"flags": [], "root_requested": False, "status": "plugin_json_absent"}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {"flags": [], "root_requested": False, "status": "plugin_json_unreadable"}
    flags = parsed.get("flags") if isinstance(parsed, dict) else []
    if not isinstance(flags, list):
        flags = []
    flags = [flag for flag in flags if isinstance(flag, str)]
    return {
        "flags": flags,
        "root_requested": "root" in flags,
        "status": "observed",
    }


def probe_runtime(os_module: Any, pwd_module: Any, environ: dict[str, str]) -> dict[str, Any]:
    privilege = drop_privileges(os_module, pwd_module, environ)
    euid = os_module.geteuid()
    egid = os_module.getegid()
    effective_name = environ.get("USER") or None
    if not effective_name:
        try:
            effective_name = pwd_module.getpwuid(euid).pw_name
        except KeyError:
            effective_name = None
    owner_name = environ.get("DECKY_USER") or None
    owner_uid = None
    owner_gid = None
    owner_lookup = "unset" if not owner_name else "not_found"
    if owner_name:
        try:
            owner = pwd_module.getpwnam(owner_name)
        except KeyError:
            owner = None
        if owner is not None:
            owner_uid = owner.pw_uid
            owner_gid = owner.pw_gid
            owner_lookup = "resolved"
    constants = {}
    for name in DECKY_CONSTANTS:
        value = environ.get(name)
        constants[name] = {"present": value is not None, "empty": value is not None and value == ""}
    directories = {}
    for label, key in DIRECTORY_CONSTANTS.items():
        raw = environ.get(key)
        directories[label] = _directory_status(raw)
    plugin_flags = read_plugin_flags(environ.get("DECKY_PLUGIN_DIR"))
    decky_present = all(constants[name]["present"] and not constants[name]["empty"] for name in ("DECKY_USER", "DECKY_HOME", "DECKY_PLUGIN_DIR"))
    return {
        "status": "observed" if decky_present else "untested",
        "reason_code": None if decky_present else "DECKY_ENV_ABSENT",
        "message": "Decky environment constants were read." if decky_present else "Process is not running with Decky's plugin environment.",
        "effective_user": effective_name,
        "effective_uid": euid,
        "effective_gid": egid,
        "owner_user": owner_name,
        "owner_uid": owner_uid,
        "owner_gid": owner_gid,
        "owner_lookup": owner_lookup,
        "privilege": privilege,
        "root_requested": plugin_flags["root_requested"],
        "flags": plugin_flags["flags"],
        "flag_status": plugin_flags["status"],
        "constants": constants,
        "directories": directories,
        "home": resolved_directory(environ.get("DECKY_USER_HOME") or environ.get("HOME")),
        "loader_version": environ.get("DECKY_VERSION") or None,
        "plugin_name": environ.get("DECKY_PLUGIN_NAME") or None,
        "plugin_version": environ.get("DECKY_PLUGIN_VERSION") or None,
        "hardware_validated": False,
        "durability": "untested",
    }


def resolved_directory(raw: str | None) -> str | None:
    """Return an absolute directory with symlink components removed."""
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        return None
    try:
        resolved = path.resolve()
    except OSError:
        return None
    if not resolved.is_dir():
        return None
    return str(resolved)


def _directory_status(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {
            "path": None,
            "exists": False,
            "is_dir": False,
            "writable": False,
            "durability": "untested",
            "status": "unset",
        }
    path = Path(raw)
    exists = path.exists()
    is_dir = path.is_dir()
    writable = os.access(path, os.W_OK) if exists else False
    return {
        "path": raw,
        "exists": exists,
        "is_dir": is_dir,
        "writable": writable,
        "durability": "untested",
        "status": "observed" if exists else "absent",
    }


def read_build_info(module_dir: Path) -> dict[str, Any]:
    path = module_dir / "build_info.json"
    fallback = {"commit": None, "channel": "development", "phase": "3", "hardware_validated": False}
    if not path.is_file():
        return fallback
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return fallback
    if not isinstance(parsed, dict):
        return fallback
    parsed["hardware_validated"] = False
    parsed.setdefault("phase", "0")
    parsed.setdefault("channel", "development")
    return parsed
