"""Shared diagnostic records.

Phase 0 never marks a hardware capability ``ready``. Inventory observations
stay ``untested``, ``missing``, ``denied``, or ``unsupported``.
"""

from __future__ import annotations

from typing import Any

CapabilityState = str
EffectiveState = str

FORBIDDEN_READY = "PHASE0_READY_FORBIDDEN"

MODULE_IDS = (
    "physical",
    "images.iso",
    "dump.redumper",
    "virtual.cdemu",
    "resources.pcgamingwiki",
    "launch.experimental",
    "launch.autoplay",
)

# User policy defaults from the implementation contract. ``physical`` is not
# an editable flag and is always enabled.
DEFAULT_MODULE_ENABLED = {
    "physical": True,
    "images.iso": True,
    "dump.redumper": True,
    "virtual.cdemu": True,
    "resources.pcgamingwiki": True,
    "launch.experimental": False,
    "launch.autoplay": False,
}


def default_settings() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "settings_revision": 0,
        "modules": {
            "images.iso": True,
            "dump.redumper": True,
            "virtual.cdemu": True,
            "resources.pcgamingwiki": True,
            "launch.experimental": False,
            "launch.autoplay": False,
        },
        "launcher_consent_version": None,
        "autoplay_consent_version": None,
        "redumper_binary": None,
        "redumper_retries": 0,
        "output_root": None,
        "image_roots": [],
        "trusted_profiles": [],
    }


def module_status(
    module_id: str,
    *,
    enabled: bool,
    capability: str,
    reason_code: str | None,
    message: str,
    checked_at: str,
    details: dict[str, Any] | None = None,
    operation_active: bool = False,
) -> dict[str, Any]:
    if capability == "ready":
        raise ValueError(FORBIDDEN_READY)
    safe_details = dict(details or {})
    safe_details["hardware_validated"] = False
    effective = effective_state(enabled, capability, operation_active)
    status: dict[str, Any] = {
        "id": module_id,
        "enabled": enabled,
        "capability": capability,
        "effective": effective,
        "reason_code": reason_code,
        "message": message,
        "checked_at": checked_at,
        "details": safe_details,
        "hardware_validated": False,
    }
    if effective == "disable_pending":
        status["disable_pending"] = True
    return status


def effective_state(enabled: bool, capability: str, operation_active: bool) -> str:
    """Apply the capability/policy precedence table.

    ``ready`` is rejected by ``module_status`` in Phase 0. The table still
    describes the later states so the policy helper can be tested on its own.
    """

    if not enabled and operation_active:
        return "disable_pending"
    if not enabled:
        return "disabled"
    if capability in {"missing", "denied", "unsupported", "untested"}:
        return "unavailable"
    if capability == "degraded":
        return "unavailable"
    if capability == "ready" and operation_active:
        return "busy"
    if capability == "ready":
        return "active"
    return "unavailable"


def envelope_ok(result: dict[str, Any], revision: int, epoch: str) -> dict[str, Any]:
    return {"ok": True, "result": result, "revision": revision, "epoch": epoch}


def envelope_error(
    code: str,
    message: str,
    *,
    retryable: bool,
    revision: int | None = None,
    epoch: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "ok": False,
        "code": code,
        "message": message,
        "retryable": retryable,
    }
    if revision is not None:
        body["revision"] = revision
    if epoch is not None:
        body["epoch"] = epoch
    return body
