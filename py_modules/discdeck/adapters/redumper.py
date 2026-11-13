"""Redumper selection.

Only the executable shipped with DiscDeck, or a newer official build saved by
Update Redumper, is visible here. PATH, a user-bin install, and a container
wrapper are ignored.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from discdeck.commands import CommandRunner
from discdeck.redumper_bundle import is_linux_x64_elf, select_redumper

MAX_HASH_BYTES = 16 * 1024 * 1024


def discover(environ: dict[str, str]) -> dict[str, Any]:
    selected = select_redumper(environ)
    if not selected["path"]:
        return {
            "status": "missing",
            "reason_code": "REDUMPER_MISSING",
            "message": "The Redumper build shipped with DiscDeck is not available. A system or container copy is not used.",
            "path": None,
            "origin": None,
            "build": None,
            "bundled_build": selected["bundled_build"],
            "updated_build": selected["updated_build"],
            "executed": False,
            "version": None,
            "version_status": "not_executed",
            "launch_kind": "absent",
            "exists": False,
            "sha256": None,
            "size": None,
            "hardware_validated": False,
        }
    where = "the copy shipped with DiscDeck" if selected["origin"] == "bundled" else "the newer official build saved by Update Redumper"
    return {
        "status": "untested",
        "reason_code": "REDUMPER_VERSION_NOT_EXECUTED",
        "message": f"Redumper build {selected['build']} from {where} is selected. It has not been executed.",
        "path": selected["path"],
        "origin": selected["origin"],
        "build": selected["build"],
        "bundled_build": selected["bundled_build"],
        "updated_build": selected["updated_build"],
        "executed": False,
        "version": None,
        "version_status": "not_executed",
        "launch_kind": "native_executable",
        "exists": True,
        "sha256": selected["sha256"],
        "size": selected["size"],
        "hardware_validated": False,
    }


def read_version(path: str, runner: CommandRunner | Any, *, allow_untested_wrapper: bool = False) -> dict[str, Any]:
    del allow_untested_wrapper
    described = _describe(Path(path))
    if described["launch_kind"] != "native_executable" or not _managed_manifest(Path(path), described.get("sha256")):
        return {
            **described,
            "status": "missing",
            "reason_code": "REDUMPER_NOT_MANAGED",
            "message": "Only the Redumper executable shipped with DiscDeck, or installed by Update Redumper, can be run.",
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


def _describe(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        return {"path": str(path), "exists": False, "launch_kind": "absent", "sha256": None, "size": None}
    size = path.stat().st_size
    try:
        prefix = path.read_bytes()[:4096]
    except OSError:
        prefix = b""
    launch_kind = "native_executable" if is_linux_x64_elf(prefix) else "script"
    return {
        "path": str(path),
        "exists": True,
        "launch_kind": launch_kind,
        "sha256": _sha256(path, size),
        "size": size,
    }


def _managed_manifest(path: Path, digest: str | None) -> bool:
    if path.name != "redumper" or not isinstance(digest, str):
        return False
    manifest = path.with_name("redumper.json")
    if not manifest.is_file() or manifest.is_symlink():
        return False
    try:
        import json

        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    recorded = payload.get("binary_sha256") if isinstance(payload, dict) else None
    origin = payload.get("origin") if isinstance(payload, dict) else None
    return origin in {"bundled", "updated"} and isinstance(recorded, str) and recorded.lower() == digest


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
