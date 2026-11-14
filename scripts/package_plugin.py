#!/usr/bin/env python3
"""Assemble a Decky ZIP using the official CLI's file layout.

The Decky CLI copies dist, py_modules, optional bin, flattens defaults into
the plugin root, and adds LICENSE, main.py, package.json, plugin.json, and
README.md. This script reproduces that layout without Docker. It does not
compile the template's example C backend; DiscDeck does not ship one.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "py_modules"))

from discdeck.redumper_bundle import RedumperInstallError, fetch_pinned_release  # noqa: E402

ROOT_FILES = ("LICENSE", "main.py", "package.json", "plugin.json", "README.md")
ZIP_MODE_FILE = 0o100644
ZIP_MODE_EXECUTABLE = 0o100755
ZIP_MODE_DIR = 0o040755


def git_commit(source: Path) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=source,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() or None


def short_commit(commit: str | None) -> str:
    if not commit:
        return "unknown"
    return commit[:7]


def stage_redumper(stage: Path, binary: bytes, manifest: dict[str, object]) -> None:
    destination = stage / "bin"
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "redumper").write_bytes(binary)
    (destination / "redumper.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def stage_plugin(source: Path, stage: Path, commit: str | None, redumper: tuple[bytes, dict[str, object]] | None = None) -> None:
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    for name in ROOT_FILES:
        shutil.copy2(source / name, stage / name)
    _copy_tree(source / "dist", stage / "dist")
    _copy_tree(source / "py_modules", stage / "py_modules")
    defaults = source / "defaults"
    if defaults.is_dir():
        for path in defaults.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                target = stage / path.relative_to(defaults)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
    package = json.loads((source / "package.json").read_text(encoding="utf-8"))
    version = package.get("version") if isinstance(package, dict) else None
    info_path = stage / "py_modules" / "discdeck" / "build_info.json"
    info = {
        "commit": commit,
        "channel": "development",
        "phase": "4",
        "version": version if isinstance(version, str) else None,
        "hardware_validated": False,
    }
    info_path.write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    if redumper is not None:
        stage_redumper(stage, redumper[0], redumper[1])


def write_zip(stage: Path, destination: Path, folder_name: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(stage.rglob("*")):
            relative = path.relative_to(stage).as_posix()
            arcname = f"{folder_name}/{relative}"
            if path.is_dir():
                _writedir(archive, arcname + "/")
            else:
                mode = ZIP_MODE_EXECUTABLE if relative == "bin/redumper" else ZIP_MODE_FILE
                _writefile(archive, arcname, path.read_bytes(), mode)
        _writedir(archive, f"{folder_name}/")


def _copy_tree(source: Path, destination: Path) -> None:
    if not source.is_dir():
        raise FileNotFoundError(source)
    destination.mkdir(parents=True)
    for path in source.rglob("*"):
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        target = destination / path.relative_to(source)
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


def _writefile(archive: zipfile.ZipFile, arcname: str, data: bytes, mode: int = ZIP_MODE_FILE) -> None:
    info = zipfile.ZipInfo(arcname)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = mode << 16
    archive.writestr(info, data)


def _writedir(archive: zipfile.ZipFile, arcname: str) -> None:
    info = zipfile.ZipInfo(arcname)
    info.external_attr = ZIP_MODE_DIR << 16
    archive.writestr(info, b"")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=Path("out"))
    args = parser.parse_args()
    source = args.source.resolve()
    commit = git_commit(source)
    plugin = json.loads((source / "plugin.json").read_text(encoding="utf-8"))
    folder_name = plugin["name"]
    stage = args.output / "stage" / folder_name
    try:
        redumper = fetch_pinned_release()
    except RedumperInstallError as exc:
        raise SystemExit(f"Could not bundle Redumper: {exc}") from exc
    stage_plugin(source, stage, commit, redumper)
    filename = f"{folder_name}-phase0-dev-{short_commit(commit)}.zip"
    destination = args.output / filename
    write_zip(stage, destination, folder_name)
    print(destination)


if __name__ == "__main__":
    main()
