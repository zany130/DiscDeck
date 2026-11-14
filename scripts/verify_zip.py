#!/usr/bin/env python3
"""Check a DiscDeck development ZIP against the Decky install layout."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path

_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")

REQUIRED = (
    "dist/index.js",
    "package.json",
    "plugin.json",
    "main.py",
    "LICENSE",
    "README.md",
    "py_modules/discdeck/__init__.py",
    "py_modules/discdeck/build_info.json",
    "bin/redumper",
    "bin/redumper.json",
)
FORBIDDEN_PARTS = ("node_modules/", "tests/", ".env", "HOST_DIAGNOSTICS", "__pycache__/")
SECRET_MARKERS = (b"BEGIN PRIVATE KEY", b"BEGIN OPENSSH PRIVATE KEY", b"AKIA")


def verify_zip(path: Path) -> list[str]:
    errors: list[str] = []
    if not zipfile.is_zipfile(path):
        return ["File is not a ZIP archive."]
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        folders = {name.split("/", 1)[0] for name in names if "/" in name}
        if folders != {"DiscDeck"}:
            errors.append(f"ZIP root must be DiscDeck/, found {sorted(folders)}.")
        for required in REQUIRED:
            full = f"DiscDeck/{required}"
            if full not in names:
                errors.append(f"Missing {full}.")
        for name in names:
            for part in FORBIDDEN_PARTS:
                if part in name:
                    errors.append(f"Forbidden path {name}.")
            data = archive.read(name)
            for marker in SECRET_MARKERS:
                if marker in data:
                    errors.append(f"Secret-like marker in {name}.")
        plugin_name = "DiscDeck/plugin.json"
        if plugin_name in names:
            plugin = json.loads(archive.read(plugin_name))
            if plugin.get("name") != "DiscDeck":
                errors.append("plugin.json name is not DiscDeck.")
            flags = plugin.get("flags") or []
            if "root" in flags:
                errors.append("plugin.json requests root.")
        info_name = "DiscDeck/py_modules/discdeck/build_info.json"
        if info_name in names:
            info = json.loads(archive.read(info_name))
            if info.get("hardware_validated") is not False:
                errors.append("build_info.json claims hardware validation.")
            if info.get("phase") != "4":
                errors.append("build_info.json is not phase 4.")
            if _VERSION.fullmatch(str(info.get("version") or "")) is None:
                errors.append("build_info.json has no plugin version.")
        package_name = "DiscDeck/package.json"
        if package_name in names and info_name in names:
            package = json.loads(archive.read(package_name))
            info = json.loads(archive.read(info_name))
            if package.get("version") != info.get("version"):
                errors.append("package.json version does not match build_info.json.")
        binary_name = "DiscDeck/bin/redumper"
        manifest_name = "DiscDeck/bin/redumper.json"
        if binary_name in names and manifest_name in names:
            info = archive.getinfo(binary_name)
            if (info.external_attr >> 16) & 0o111 == 0:
                errors.append("bin/redumper is not marked executable.")
            binary = archive.read(binary_name)
            if not binary.startswith(b"\x7fELF"):
                errors.append("bin/redumper is not an ELF executable.")
            manifest = json.loads(archive.read(manifest_name))
            if manifest.get("origin") != "bundled" or manifest.get("repository") != "superg/redumper":
                errors.append("bin/redumper.json is not the bundled official Redumper.")
            if manifest.get("binary_sha256") != hashlib.sha256(binary).hexdigest():
                errors.append("bin/redumper does not match its manifest.")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("zip", type=Path)
    args = parser.parse_args()
    errors = verify_zip(args.zip)
    if errors:
        for error in errors:
            print(error)
        raise SystemExit(1)
    print(f"Verified {args.zip}")


if __name__ == "__main__":
    main()
