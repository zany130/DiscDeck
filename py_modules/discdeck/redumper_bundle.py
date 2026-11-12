"""The Redumper executable that ships with DiscDeck.

Dumps use this file, or a newer official Linux x64 build saved by the update
action. A copy on PATH, in the user bin, or behind a container wrapper is not
considered.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Callable

from discdeck.updates import host_cafile

PIN_PATH = Path(__file__).with_name("redumper_pin.json")
LATEST_URL = "https://api.github.com/repos/superg/redumper/releases/latest"
REPOSITORY = "superg/redumper"
MAX_ZIP_BYTES = 16 * 1024 * 1024
MAX_BINARY_BYTES = 16 * 1024 * 1024
MAX_METADATA_BYTES = 1024 * 1024
_TAG = re.compile(r"^b[1-9][0-9]{0,6}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_HOSTS = frozenset(
    {
        "api.github.com",
        "github.com",
        "objects.githubusercontent.com",
        "release-assets.githubusercontent.com",
        "github-releases.githubusercontent.com",
    }
)

Opener = Callable[[str, float], Any]
UrlOpen = Callable[..., Any]


class RedumperInstallError(Exception):
    pass


class _GuardedRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
        if not allowed_download_url(newurl):
            raise RedumperInstallError("The Redumper download redirected to an unexpected address.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def allowed_download_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    return parsed.scheme == "https" and parsed.hostname in _ALLOWED_HOSTS and parsed.username is None


def load_pin(path: Path = PIN_PATH) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RedumperInstallError("The bundled Redumper pin could not be read.") from exc
    return _validated_pin(payload)


def is_linux_x64_elf(data: bytes) -> bool:
    if len(data) < 64 or data[:4] != b"\x7fELF":
        return False
    if data[4] != 2 or data[5] != 1 or data[6] != 1:
        return False
    return int.from_bytes(data[18:20], "little") == 62


def extract_release_binary(blob: bytes, tag: str) -> bytes:
    if not isinstance(tag, str) or _TAG.fullmatch(tag) is None:
        raise RedumperInstallError("The Redumper release tag was not a build number.")
    member = f"redumper-{tag}-linux-x64/bin/redumper"
    try:
        archive = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile as exc:
        raise RedumperInstallError("The Redumper download was not a zip archive.") from exc
    with archive:
        matches = [info for info in archive.infolist() if info.filename == member]
        if len(matches) != 1:
            raise RedumperInstallError("The Redumper zip did not contain the Linux x64 executable.")
        info = matches[0]
        if info.is_dir() or info.file_size <= 64 or info.file_size > MAX_BINARY_BYTES:
            raise RedumperInstallError("The Redumper executable had an unexpected size.")
        binary = archive.read(info)
    if len(binary) != info.file_size or not is_linux_x64_elf(binary):
        raise RedumperInstallError("The Redumper zip did not contain a Linux x64 executable.")
    return binary


def fetch_pinned_release(*, opener: Opener | None = None, timeout: float = 60) -> tuple[bytes, dict[str, Any]]:
    pin = load_pin()
    blob = _download(pin["url"], pin["sha256"], opener=opener, timeout=timeout, limit=MAX_ZIP_BYTES)
    binary = extract_release_binary(blob, pin["tag"])
    digest = hashlib.sha256(binary).hexdigest()
    if digest != pin["binary_sha256"]:
        raise RedumperInstallError("The extracted Redumper executable did not match the pinned hash.")
    return binary, _manifest(pin, binary, origin="bundled")


def select_redumper(environ: dict[str, str]) -> dict[str, Any]:
    bundled = _load_candidate(_bundled_dir(environ), "bundled")
    updated = _load_candidate(_updated_dir(environ), "updated")
    bundled_build = bundled["build"] if bundled else None
    updated_build = updated["build"] if updated else None
    candidates = [item for item in (bundled, updated) if item is not None]
    if not candidates:
        return {
            "path": None,
            "origin": None,
            "build": None,
            "bundled_build": bundled_build,
            "updated_build": updated_build,
            "sha256": None,
            "size": None,
        }
    chosen = max(candidates, key=lambda item: (item["build"], 1 if item["origin"] == "bundled" else 0))
    _ensure_executable(Path(chosen["path"]))
    return {
        "path": chosen["path"],
        "origin": chosen["origin"],
        "build": chosen["build"],
        "bundled_build": bundled_build,
        "updated_build": updated_build,
        "sha256": chosen["sha256"],
        "size": chosen["size"],
    }


def install_latest_redumper(
    environ: dict[str, str],
    *,
    opener: Opener | None = None,
    timeout: float = 60,
) -> dict[str, Any]:
    current = select_redumper(environ)
    release = fetch_latest_release(opener=opener, timeout=timeout)
    active = current["build"] if isinstance(current["build"], int) else 0
    if release["build"] <= active:
        if release["build"] == active:
            message = f"Redumper build {active} is already the latest official release."
        else:
            message = (
                f"Redumper build {active} is newer than official build {release['build']}. "
                "The installed copy was left in place."
            )
        return {
            "action": "update_redumper",
            "updated": False,
            "active_build": current["build"],
            "active_origin": current["origin"],
            "remote_build": release["build"],
            "bundled_build": current["bundled_build"],
            "message": message,
            "hardware_validated": False,
        }
    directory = _updated_dir(environ)
    if directory is None:
        raise RedumperInstallError("The plugin settings directory is unset, so the newer Redumper build was not saved.")
    blob = _download(release["url"], release["sha256"], opener=opener, timeout=timeout, limit=MAX_ZIP_BYTES)
    binary = extract_release_binary(blob, release["tag"])
    _write_install(directory, binary, _manifest(release, binary, origin="updated"))
    bundled = current["bundled_build"]
    shipped = f" DiscDeck still ships build {bundled}." if isinstance(bundled, int) else ""
    return {
        "action": "update_redumper",
        "updated": True,
        "active_build": release["build"],
        "active_origin": "updated",
        "remote_build": release["build"],
        "bundled_build": bundled,
        "message": f"Redumper build {release['build']} is installed. Dumps use this copy.{shipped}",
        "hardware_validated": False,
    }


def remove_updated_copy(environ: dict[str, str]) -> bool:
    directory = _updated_dir(environ)
    if directory is None or not directory.exists():
        return False
    removed = False
    for name in ("redumper", "redumper.json", "redumper.tmp", "redumper.json.tmp"):
        path = directory / name
        if path.is_file() or path.is_symlink():
            path.unlink()
            removed = True
    try:
        directory.rmdir()
    except OSError:
        pass
    return removed


def fetch_latest_release(*, opener: Opener | None = None, timeout: float = 60) -> dict[str, Any]:
    raw = _download_unchecked(LATEST_URL, opener=opener, timeout=timeout, limit=MAX_METADATA_BYTES)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RedumperInstallError("The Redumper release list was not valid JSON.") from exc
    return parse_latest_release(payload)


def parse_latest_release(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise RedumperInstallError("The Redumper release list was not a record.")
    tag = payload.get("tag_name")
    if not isinstance(tag, str) or _TAG.fullmatch(tag) is None:
        raise RedumperInstallError("The latest Redumper tag was not a build number.")
    build = int(tag[1:])
    asset_name = f"redumper-{tag}-linux-x64.zip"
    expected_url = f"https://github.com/{REPOSITORY}/releases/download/{tag}/{asset_name}"
    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise RedumperInstallError("The latest Redumper release did not list its files.")
    asset = next((item for item in assets if isinstance(item, dict) and item.get("name") == asset_name), None)
    if asset is None:
        raise RedumperInstallError("The latest Redumper release has no Linux x64 zip.")
    if asset.get("browser_download_url") != expected_url:
        raise RedumperInstallError("The Redumper download address did not match the official release.")
    digest = asset.get("digest")
    if not isinstance(digest, str) or not digest.startswith("sha256:"):
        raise RedumperInstallError("The Redumper release did not publish a SHA-256 digest.")
    sha = digest.removeprefix("sha256:").lower()
    if _SHA256.fullmatch(sha) is None:
        raise RedumperInstallError("The Redumper release digest was not a SHA-256.")
    return {
        "repository": REPOSITORY,
        "tag": tag,
        "build": build,
        "asset": asset_name,
        "url": expected_url,
        "sha256": sha,
        "member": f"redumper-{tag}-linux-x64/bin/redumper",
    }


def _validated_pin(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise RedumperInstallError("The bundled Redumper pin was not a record.")
    release = {
        "tag_name": payload.get("tag"),
        "assets": [
            {
                "name": payload.get("asset"),
                "browser_download_url": payload.get("url"),
                "digest": f"sha256:{payload.get('sha256')}",
            }
        ],
    }
    try:
        parsed = parse_latest_release(release)
    except RedumperInstallError as exc:
        raise RedumperInstallError("The bundled Redumper pin does not name the official Linux x64 release.") from exc
    binary_sha = payload.get("binary_sha256")
    member = payload.get("member")
    if not isinstance(binary_sha, str) or _SHA256.fullmatch(binary_sha.lower()) is None:
        raise RedumperInstallError("The bundled Redumper pin has no executable hash.")
    if member != parsed["member"] or payload.get("build") != parsed["build"] or payload.get("repository") != REPOSITORY:
        raise RedumperInstallError("The bundled Redumper pin does not match its release.")
    parsed["binary_sha256"] = binary_sha.lower()
    return parsed


def _manifest(release: dict[str, Any], binary: bytes, *, origin: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "repository": REPOSITORY,
        "tag": release["tag"],
        "build": release["build"],
        "origin": origin,
        "asset": release["asset"],
        "zip_sha256": release["sha256"],
        "binary_sha256": hashlib.sha256(binary).hexdigest(),
    }


def _download(url: str, expected_sha: str, *, opener: Opener | None, timeout: float, limit: int) -> bytes:
    blob = _download_unchecked(url, opener=opener, timeout=timeout, limit=limit)
    if hashlib.sha256(blob).hexdigest() != expected_sha:
        raise RedumperInstallError("The Redumper download did not match the published SHA-256.")
    return blob


def _download_unchecked(url: str, *, opener: Opener | None, timeout: float, limit: int) -> bytes:
    if not allowed_download_url(url):
        raise RedumperInstallError("Refusing an unexpected Redumper address.")
    open_url = opener or _urlopen
    try:
        with open_url(url, timeout) as response:
            return _read_limited(response, limit)
    except RedumperInstallError:
        raise
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        raise RedumperInstallError(f"The Redumper download failed. {exc}") from exc


def _urlopen(url: str, timeout: float) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": "DiscDeck", "Accept": "application/vnd.github+json"})
    cafile = host_cafile()
    context = ssl.create_default_context(cafile=cafile) if cafile else ssl.create_default_context()
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=context), _GuardedRedirect)
    return opener.open(request, timeout=timeout)


def _read_limited(response: Any, limit: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = response.read(64 * 1024)
        if not chunk:
            break
        if not isinstance(chunk, bytes):
            raise RedumperInstallError("The Redumper download was not binary data.")
        total += len(chunk)
        if total > limit:
            raise RedumperInstallError("The Redumper download was larger than expected.")
        chunks.append(chunk)
    return b"".join(chunks)


def _bundled_dir(environ: dict[str, str]) -> Path | None:
    raw = environ.get("DECKY_PLUGIN_DIR")
    if not raw:
        return None
    return Path(raw) / "bin"


def _updated_dir(environ: dict[str, str]) -> Path | None:
    raw = environ.get("DECKY_PLUGIN_SETTINGS_DIR")
    if not raw:
        return None
    return Path(raw) / "redumper"


def _load_candidate(directory: Path | None, origin: str) -> dict[str, Any] | None:
    if directory is None:
        return None
    binary_path = directory / "redumper"
    manifest_path = directory / "redumper.json"
    if not binary_path.is_file() or binary_path.is_symlink() or not manifest_path.is_file() or manifest_path.is_symlink():
        return None
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        binary = binary_path.read_bytes()
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if len(binary) > MAX_BINARY_BYTES or not is_linux_x64_elf(binary):
        return None
    if not isinstance(payload, dict) or payload.get("origin") != origin or payload.get("repository") != REPOSITORY:
        return None
    build = payload.get("build")
    tag = payload.get("tag")
    digest = payload.get("binary_sha256")
    if isinstance(digest, str):
        digest = digest.lower()
    if not isinstance(build, int) or isinstance(build, bool) or build < 1 or build > 9_999_999:
        return None
    if tag != f"b{build}" or not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
        return None
    if hashlib.sha256(binary).hexdigest() != digest:
        return None
    return {
        "path": str(binary_path),
        "origin": origin,
        "build": build,
        "sha256": digest,
        "size": len(binary),
    }


def _write_install(directory: Path, binary: bytes, manifest: dict[str, Any]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    temporary = directory / "redumper.tmp"
    meta_temporary = directory / "redumper.json.tmp"
    temporary.write_bytes(binary)
    temporary.chmod(0o755)
    meta_temporary.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, directory / "redumper")
    os.replace(meta_temporary, directory / "redumper.json")
    (directory / "redumper").chmod(0o755)


def _ensure_executable(path: Path) -> None:
    try:
        mode = path.stat().st_mode
        if mode & 0o111:
            return
        path.chmod(mode | 0o755)
    except OSError:
        return
