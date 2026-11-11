"""Compare this build with the published development release.

The check reads one metadata file. It does not download the ZIP and it does
not start an install. The artifact URL is built from the commit, not copied
from the metadata document.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any, Callable

METADATA_URL = "https://github.com/zany130/DiscDeck/releases/download/discdeck-dev/metadata.json"
DOWNLOAD_PREFIX = "https://github.com/zany130/DiscDeck/releases/download/discdeck-dev/"
_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_COMMIT = re.compile(r"^[0-9a-fA-F]{40}$")
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")

Opener = Callable[[str, float], Any]


class UpdateError(Exception):
    pass


def open_metadata(url: str, timeout: float) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": "DiscDeck"})
    return urllib.request.urlopen(request, timeout=timeout)


def check_development_update(
    local_version: str | None,
    local_commit: str | None,
    *,
    opener: Opener = open_metadata,
    timeout: float = 15,
) -> dict[str, Any]:
    try:
        with opener(METADATA_URL, timeout) as response:
            raw = response.read(65537)
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        raise UpdateError(f"The development release could not be read. {exc}") from exc
    if len(raw) > 65536:
        raise UpdateError("The development metadata was larger than expected.")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise UpdateError("The development metadata was not valid JSON.") from exc
    remote = _remote_release(payload)
    current_version = local_version if _VERSION.fullmatch(local_version or "") else None
    current_commit = local_commit.lower() if isinstance(local_commit, str) and _COMMIT.fullmatch(local_commit) else None
    same = current_commit is not None and current_commit == remote["commit"]
    return {
        "action": "check_update",
        "current_version": current_version,
        "current_commit": current_commit,
        "remote_version": remote["version"],
        "remote_commit": remote["commit"],
        "up_to_date": same,
        "artifact_url": None if same else remote["artifact_url"],
        "zip_sha256": None if same else remote["zip_sha256"],
        "hardware_validated": False,
    }


def _remote_release(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise UpdateError("The development metadata was not a record.")
    if payload.get("plugin") not in {None, "DiscDeck"} or payload.get("channel") != "development":
        raise UpdateError("The metadata was not the DiscDeck development release.")
    commit = payload.get("commit")
    digest = payload.get("zip_sha256")
    object_key = payload.get("object_key")
    if not isinstance(commit, str) or _COMMIT.fullmatch(commit) is None:
        raise UpdateError("The published commit was not a full revision.")
    if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
        raise UpdateError("The published ZIP hash was missing.")
    if not isinstance(object_key, str):
        raise UpdateError("The published object name was missing.")
    commit = commit.lower()
    name = f"DiscDeck-phase0-dev-{commit[:7]}.zip"
    if not object_key.endswith("/" + name):
        raise UpdateError("The published object name did not match the commit.")
    version = payload.get("version")
    if version is not None and (not isinstance(version, str) or _VERSION.fullmatch(version) is None):
        version = None
    return {
        "commit": commit,
        "version": version,
        "zip_sha256": digest.lower(),
        "artifact_url": DOWNLOAD_PREFIX + name,
    }
