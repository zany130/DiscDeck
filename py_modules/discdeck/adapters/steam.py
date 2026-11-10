"""Read-only Steam and Proton discovery.

Library folder paths and compatibility-tool directory names are listed.
Shortcut files, Proton prefixes, and Steam processes are not opened or changed.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

PATH_KEY = re.compile(r'"path"\s+"([^"]+)"')
TOOL_MARKERS = ("proton", "boxtron", "roberta", "luxtorpeda")
MAX_VDF_BYTES = 1024 * 1024


def probe_steam(home: Path | None, environ: dict[str, str], root: Path | None = None) -> dict[str, Any]:
    reads: list[str] = []
    root = root or Path("/")
    steam_bin = _find_steam(environ, reads, root)
    roots = _steam_roots(home, reads) if home is not None else []
    libraries = []
    tools: list[dict[str, str]] = []
    for root in roots:
        for library in _library_paths(root, reads):
            libraries.append(library)
            tools.extend(_tools(Path(library), reads))
    if steam_bin is None and not roots:
        status = "missing"
        reason = "STEAM_NOT_FOUND"
        message = "Steam was not found from PATH or the user's Steam directory."
    else:
        status = "untested"
        reason = "STEAM_LAUNCH_UNTESTED"
        message = "Steam files were listed. No shortcut was read and no game was launched."
    return {
        "status": status,
        "reason_code": reason,
        "message": message,
        "steam_binary": steam_bin,
        "steam_roots": [str(path) for path in roots],
        "library_paths": libraries,
        "compatibility_tools": tools,
        "shortcuts_read": False,
        "prefixes_read": False,
        "launched": False,
        "files_read": reads,
        "hardware_validated": False,
    }


def _find_steam(environ: dict[str, str], reads: list[str], root: Path) -> str | None:
    for directory in (environ.get("PATH") or "").split(os.pathsep):
        if not directory:
            continue
        candidate = Path(directory) / "steam"
        if candidate.is_file():
            return str(candidate)
    for relative in ("usr/bin/steam", "usr/bin/steam-runtime"):
        candidate = root / relative
        if candidate.is_file():
            return str(candidate)
    return None


def _steam_roots(home: Path, reads: list[str]) -> list[Path]:
    roots: list[Path] = []
    link = home / ".steam" / "steam"
    if link.exists():
        reads.append(str(link))
        roots.append(link.resolve())
    primary = home / ".local" / "share" / "Steam"
    if primary.is_dir():
        resolved = primary.resolve()
        if resolved not in roots:
            roots.append(resolved)
    return roots


def _library_paths(root: Path, reads: list[str]) -> list[str]:
    manifest = root / "steamapps" / "libraryfolders.vdf"
    if not manifest.is_file():
        return [str(root)]
    reads.append(str(manifest))
    try:
        if manifest.stat().st_size > MAX_VDF_BYTES:
            return [str(root)]
        text = manifest.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return [str(root)]
    found = PATH_KEY.findall(text)
    if not found:
        return [str(root)]
    return found


def _tools(library: Path, reads: list[str]) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    for relative in ("steamapps/common", "compatibilitytools.d"):
        directory = library / relative
        if not directory.is_dir():
            continue
        reads.append(str(directory))
        try:
            children = sorted(directory.iterdir(), key=lambda item: item.name)
        except OSError:
            continue
        for child in children:
            if not child.is_dir():
                continue
            lowered = child.name.lower()
            if any(marker in lowered for marker in TOOL_MARKERS):
                found.append({"name": child.name, "library": str(library), "location": relative})
    return found
