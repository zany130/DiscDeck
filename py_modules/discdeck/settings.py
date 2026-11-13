"""Read DiscDeck settings without rewriting them.

Phase 0 does not persist module toggles. A missing file stays missing. An
invalid file is left untouched and reported as ``SETTINGS_INVALID`` while the
in-memory defaults keep the launcher and autoplay off.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from discdeck.models import default_settings


def load_settings(path: Path | None) -> dict[str, Any]:
    defaults = default_settings()
    if path is None:
        return {
            "settings": defaults,
            "persisted": False,
            "status": "not_configured",
            "rewritten": False,
            "settings_revision": 0,
        }
    if not path.exists():
        return {
            "settings": defaults,
            "persisted": False,
            "status": "absent",
            "rewritten": False,
            "settings_revision": 0,
        }
    original = path.read_bytes()
    try:
        parsed = json.loads(original.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        _ensure_unchanged(path, original)
        return {
            "settings": defaults,
            "persisted": True,
            "status": "SETTINGS_INVALID",
            "rewritten": False,
            "settings_revision": 0,
        }
    if not isinstance(parsed, dict) or parsed.get("schema_version") != 1:
        _ensure_unchanged(path, original)
        return {
            "settings": defaults,
            "persisted": True,
            "status": "SETTINGS_INVALID",
            "rewritten": False,
            "settings_revision": 0,
        }
    merged = default_settings()
    modules = parsed.get("modules")
    if isinstance(modules, dict):
        for key in merged["modules"]:
            if isinstance(modules.get(key), bool):
                merged["modules"][key] = modules[key]
    revision = parsed.get("settings_revision")
    if not isinstance(revision, int) or revision < 0:
        revision = 0
    merged["settings_revision"] = revision
    # Older files may name a host path. DiscDeck does not execute it.
    binary = parsed.get("redumper_binary")
    if isinstance(binary, str) and binary.startswith("/"):
        merged["redumper_binary"] = binary
    retries = parsed.get("redumper_retries")
    if isinstance(retries, int) and not isinstance(retries, bool) and 0 <= retries <= 5:
        merged["redumper_retries"] = retries
    _ensure_unchanged(path, original)
    return {
        "settings": merged,
        "persisted": True,
        "status": "loaded",
        "rewritten": False,
        "settings_revision": revision,
    }


def _ensure_unchanged(path: Path, original: bytes) -> None:
    if path.read_bytes() != original:
        raise RuntimeError("Settings load modified the file.")
