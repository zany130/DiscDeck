"""Redumper discovery without disc access.

A distrobox export wrapper is identified and not executed. ``--version`` is
available only for a non-wrapper binary, and only when a caller explicitly
requests it. No ``disc`` command is ever constructed.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

from discdeck.commands import CommandRunner

MAX_HASH_BYTES = 32 * 1024 * 1024
WRAPPER_MARKERS = ("distrobox", "distrobox-host-exec")


def discover(environ: dict[str, str], configured_path: str | None = None) -> dict[str, Any]:
    candidate = _resolve(environ, configured_path)
    if candidate is None:
        return {
            "status": "missing",
            "reason_code": "REDUMPER_MISSING",
            "message": "No redumper executable was found on PATH or in the configured path.",
            "path": None,
            "executed": False,
            "version": None,
            "version_status": "not_executed",
            "hardware_validated": False,
        }
    info = _describe(candidate)
    info.update(
        {
            "status": "untested",
            "reason_code": "REDUMPER_VERSION_NOT_EXECUTED",
            "message": "Redumper was found. It was not executed, so its version and dump behavior are untested.",
            "executed": False,
            "version": None,
            "version_status": "not_executed",
            "hardware_validated": False,
        }
    )
    return info


def read_version(path: str, runner: CommandRunner | Any, *, allow_untested_wrapper: bool) -> dict[str, Any]:
    described = _describe(Path(path))
    if not described["exists"]:
        return {
            **described,
            "status": "missing",
            "reason_code": "REDUMPER_MISSING",
            "message": "The selected redumper path does not exist.",
            "executed": False,
            "version": None,
            "version_status": "not_executed",
            "hardware_validated": False,
        }
    if described["launch_kind"] == "distrobox_wrapper" and not allow_untested_wrapper:
        return {
            **described,
            "status": "untested",
            "reason_code": "DISTROBOX_WRAPPER_NOT_EXECUTED",
            "message": "The installed redumper path is a container wrapper. Phase 0 did not execute it.",
            "executed": False,
            "version": None,
            "version_status": "not_executed",
            "hardware_validated": False,
        }
    result = runner([path, "--version"], timeout=5)
    version = _first_line(result.stdout) or _first_line(result.stderr)
    if result.code != 0 or not version:
        return {
            **described,
            "status": "untested",
            "reason_code": "REDUMPER_VERSION_FAILED",
            "message": "redumper --version did not return a usable version line.",
            "executed": True,
            "version": version or None,
            "version_status": "failed",
            "exit_code": result.code,
            "hardware_validated": False,
        }
    return {
        **described,
        "status": "untested",
        "reason_code": "REDUMPER_VERSION_OBSERVED_DUMP_UNTESTED",
        "message": "Version text was read. No disc command was run, so preservation remains untested.",
        "executed": True,
        "version": version,
        "version_status": "observed",
        "exit_code": result.code,
        "hardware_validated": False,
    }


def _resolve(environ: dict[str, str], configured_path: str | None) -> Path | None:
    if configured_path:
        path = Path(configured_path)
        return path if path.is_file() else None
    for directory in (environ.get("PATH") or "").split(os.pathsep):
        if not directory:
            continue
        candidate = Path(directory) / "redumper"
        if candidate.is_file():
            return candidate
    # Decky does not inherit a login-shell PATH. The XDG user bin is the
    # location a per-user install uses, resolved from the owner home.
    seen: set[Path] = set()
    for key in ("DECKY_USER_HOME", "HOME"):
        raw = environ.get(key)
        if not raw:
            continue
        candidate = Path(raw) / ".local" / "bin" / "redumper"
        if candidate in seen:
            continue
        seen.add(candidate)
        if candidate.is_file():
            return candidate
    return None


def _describe(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"path": str(path), "exists": False, "launch_kind": "absent", "sha256": None, "size": None}
    size = path.stat().st_size
    text_sample = ""
    try:
        text_sample = path.read_text(encoding="utf-8", errors="replace")[:4096]
    except OSError:
        text_sample = ""
    launch_kind = "native_executable"
    if text_sample.startswith("#!") and any(marker in text_sample for marker in WRAPPER_MARKERS):
        launch_kind = "distrobox_wrapper"
    elif text_sample.startswith("#!"):
        launch_kind = "script"
    return {
        "path": str(path),
        "exists": True,
        "launch_kind": launch_kind,
        "sha256": _sha256(path, size),
        "size": size,
    }


def _sha256(path: Path, size: int) -> str | None:
    if size > MAX_HASH_BYTES:
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _first_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:200]
    return ""
