#!/usr/bin/env python3
"""Publish a ZIP that has already passed local verification.

The unique object is uploaded and checked before the channel pointer moves.
Stable and development prefixes are never mixed by this command.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

from publish_plan import assert_development_isolation, plan_publish, select_mode

Runner = Callable[[list[str]], int]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def metadata(plan: dict[str, Any], zip_sha256: str) -> dict[str, Any]:
    return {
        "channel": plan["channel"],
        "commit": plan["commit"],
        "object_key": plan["unique_key"],
        "canonical_key": plan["canonical_key"],
        "zip_sha256": zip_sha256,
        "phase": "0",
        "hardware_validated": False,
        "plugin": "DiscDeck",
    }


def execute(plan: dict[str, Any], zip_path: Path, *, dry_run: bool, env: dict[str, str], run: Runner) -> dict[str, Any]:
    assert_development_isolation(plan) if plan["channel"] == "development" else None
    if plan["mode"] in {"none", "skip-unconfigured"}:
        return {"published": False, "reason": plan["mode"], "steps": []}
    if plan["mode"] == "refuse-private":
        raise RuntimeError("GitHub Release assets are not anonymously downloadable from a private repository.")
    if plan["mode"] == "r2":
        commands = r2_commands(plan, zip_path, env)
    elif plan["mode"] == "github-release":
        commands = github_commands(plan, zip_path, env)
    else:
        raise RuntimeError(f"Unsupported mode {plan['mode']}")
    if dry_run:
        return {"published": False, "dry_run": True, "steps": plan["steps"], "commands": commands}
    for command in commands:
        code = run(command)
        if code != 0:
            raise RuntimeError(f"Publish command failed ({code}): {' '.join(command)}")
        if "download" in command:
            downloaded = Path(env["PUBLISH_WORK"]) / "downloaded.zip"
            unique = Path(env["PUBLISH_WORK"]) / Path(plan["unique_key"]).name
            if sha256_file(downloaded) != sha256_file(unique):
                raise RuntimeError("Downloaded asset does not match the ZIP that was uploaded.")
    return {"published": True, "steps": plan["steps"], "commands": commands}


def github_commands(plan: dict[str, Any], zip_path: Path, env: dict[str, str]) -> list[list[str]]:
    tag = plan["release_tag"]
    work = Path(env["PUBLISH_WORK"])
    unique = work / Path(plan["unique_key"]).name
    canonical = work / plan["canonical_name"]
    meta = work / "metadata.json"
    downloaded = work / "downloaded.zip"
    return [
        ["gh", "release", "view", tag, "--repo", env["GITHUB_REPOSITORY"]],
        ["gh", "release", "upload", tag, str(unique), "--clobber", "--repo", env["GITHUB_REPOSITORY"]],
        ["gh", "release", "download", tag, "--pattern", unique.name, "--output", str(downloaded), "--repo", env["GITHUB_REPOSITORY"]],
        ["gh", "release", "upload", tag, str(canonical), "--clobber", "--repo", env["GITHUB_REPOSITORY"]],
        ["gh", "release", "upload", tag, str(meta), "--clobber", "--repo", env["GITHUB_REPOSITORY"]],
    ]


def r2_commands(plan: dict[str, Any], zip_path: Path, env: dict[str, str]) -> list[list[str]]:
    endpoint = f"https://{env['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com"
    bucket = env["R2_BUCKET"]
    work = Path(env["PUBLISH_WORK"])
    unique_name = Path(plan["unique_key"]).name
    return [
        ["aws", "s3", "cp", str(work / unique_name), f"s3://{bucket}/{plan['unique_key']}", "--endpoint-url", endpoint],
        ["aws", "s3api", "head-object", "--bucket", bucket, "--key", plan["unique_key"], "--endpoint-url", endpoint],
        ["aws", "s3", "cp", str(work / "latest.json"), f"s3://{bucket}/{plan['pointer_key']}", "--endpoint-url", endpoint, "--content-type", "application/json"],
        ["aws", "s3", "cp", str(work / plan["canonical_name"]), f"s3://{bucket}/{plan['canonical_key']}", "--endpoint-url", endpoint, "--content-type", "application/zip"],
    ]


def prepare_work(plan: dict[str, Any], zip_path: Path, work: Path) -> None:
    work.mkdir(parents=True, exist_ok=True)
    unique = work / Path(plan["unique_key"]).name
    canonical = work / plan["canonical_name"]
    shutil.copy2(zip_path, unique)
    shutil.copy2(zip_path, canonical)
    body = metadata(plan, sha256_file(zip_path))
    (work / "latest.json").write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    (work / "metadata.json").write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")


def github_cli_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """Give gh the Actions token.

    Current GitHub CLI builds refuse to use GITHUB_TOKEN unless GH_TOKEN is set.
    """
    env = dict(os.environ if base is None else base)
    if not env.get("GH_TOKEN") and env.get("GITHUB_TOKEN"):
        env["GH_TOKEN"] = env["GITHUB_TOKEN"]
    return env


def default_runner(command: list[str]) -> int:
    env = github_cli_env()
    if command[:3] == ["gh", "release", "view"]:
        completed = subprocess.run(command, check=False, env=env)
        # Exit 1 is how gh reports a missing release. Exit 4 is authentication
        # and must not be turned into a release-create attempt.
        if completed.returncode == 0:
            return 0
        if completed.returncode != 1:
            return completed.returncode
        tag = command[3]
        repo = command[command.index("--repo") + 1]
        create = subprocess.run(
            [
                "gh",
                "release",
                "create",
                tag,
                "--repo",
                repo,
                "--prerelease",
                "--title",
                f"DiscDeck {tag}",
                "--notes",
                "Development or stable DiscDeck ZIP. CI success is not hardware validation.",
            ],
            check=False,
            env=env,
        )
        return create.returncode
    completed = subprocess.run(command, check=False, env=env)
    return completed.returncode


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", type=Path, required=True)
    parser.add_argument("--channel", choices=("development", "stable"), default="development")
    parser.add_argument("--commit", default=os.environ.get("GITHUB_SHA", "unknown"))
    parser.add_argument("--mode", default=os.environ.get("DISCDECK_PUBLISH_MODE", "auto"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    r2_ready = all(os.environ.get(name) for name in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET"))
    repo_public = os.environ.get("DISCDECK_REPO_PUBLIC", "true").lower() == "true"
    mode = select_mode(args.mode, r2_ready=r2_ready, repo_public=repo_public)
    plan = plan_publish(args.channel, mode if mode in {"r2", "github-release"} else "github-release", args.commit)
    plan["mode"] = mode
    if args.channel == "development":
        assert_development_isolation(plan) if mode in {"r2", "github-release"} else None
    with tempfile.TemporaryDirectory() as temporary:
        work = Path(temporary)
        if mode in {"r2", "github-release"}:
            prepare_work(plan, args.zip, work)
        env = dict(os.environ)
        env["PUBLISH_WORK"] = str(work)
        env.setdefault("GITHUB_REPOSITORY", "zany130/DiscDeck")
        result = execute(plan, args.zip, dry_run=args.dry_run, env=env, run=default_runner)
    print(json.dumps({"published": result["published"], "reason": result.get("reason", mode), "channel": args.channel}))


if __name__ == "__main__":
    main()
