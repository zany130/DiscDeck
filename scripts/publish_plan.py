"""Decide how a successful build is published.

Development and stable channels use different object prefixes and release
tags. A failed build never reaches this planner. The planner itself does not
upload anything.
"""

from __future__ import annotations

from typing import Any


def select_mode(requested: str, *, r2_ready: bool, repo_public: bool) -> str:
    if requested in {"", "auto"}:
        if r2_ready:
            return "r2"
        if repo_public:
            return "github-release"
        return "skip-unconfigured"
    if requested == "none":
        return "none"
    if requested == "r2":
        return "r2" if r2_ready else "skip-unconfigured"
    if requested == "github-release":
        return "github-release" if repo_public else "refuse-private"
    raise ValueError(f"Unknown publish mode {requested}")


def plan_publish(channel: str, mode: str, commit: str) -> dict[str, Any]:
    if channel == "development":
        prefix = "dev"
        tag = "discdeck-dev"
        canonical = "DiscDeck.zip"
    elif channel == "stable":
        prefix = "stable"
        tag = "discdeck-stable"
        canonical = "DiscDeck.zip"
    else:
        raise ValueError(f"Unknown channel {channel}")
    short = commit[:7]
    unique = f"{prefix}/builds/{commit}/DiscDeck-phase0-dev-{short}.zip" if channel == "development" else f"{prefix}/builds/{commit}/DiscDeck-{short}.zip"
    steps = [
        "verify-local-zip",
        "upload-unique-object",
        "verify-unique-object",
        "write-channel-pointer",
        "copy-canonical-object",
    ]
    if mode == "github-release":
        steps = [
            "verify-local-zip",
            "ensure-prerelease",
            "upload-unique-asset",
            "verify-unique-asset",
            "upload-canonical-asset",
            "upload-metadata",
        ]
    return {
        "channel": channel,
        "mode": mode,
        "commit": commit,
        "prefix": prefix,
        "release_tag": tag,
        "unique_key": unique,
        "canonical_key": f"{prefix}/{canonical}",
        "pointer_key": f"{prefix}/latest.json",
        "canonical_name": canonical,
        "steps": steps,
        "hardware_validated": False,
    }


def assert_development_isolation(plan: dict[str, Any]) -> None:
    if plan["channel"] != "development":
        return
    if not plan["unique_key"].startswith("dev/"):
        raise ValueError("Development objects must stay under dev/.")
    if plan["canonical_key"].startswith("stable/") or plan["pointer_key"].startswith("stable/"):
        raise ValueError("Development publish must not write the stable channel.")
    if plan["release_tag"] != "discdeck-dev":
        raise ValueError("Development GitHub releases use the discdeck-dev tag.")
    if plan["steps"][-1] not in {"copy-canonical-object", "upload-metadata"}:
        raise ValueError("The channel pointer or metadata is not the publish commit point.")
