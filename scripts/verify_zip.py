#!/usr/bin/env python3
"""Check a DiscDeck development ZIP against the Decky install layout."""

from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path

REQUIRED = (
    "dist/index.js",
    "package.json",
    "plugin.json",
    "main.py",
    "LICENSE",
    "README.md",
    "py_modules/discdeck/__init__.py",
    "py_modules/discdeck/build_info.json",
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
            if info.get("phase") != "2":
                errors.append("build_info.json is not phase 2.")
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
