"""Read-only UDisks2 object enumeration.

``Drive.Optical=false`` does not override sysfs type 5 or an ``sr`` node.
Mount, unmount, eject, and loop setup are not called. An inactive service is
not activated.
"""

from __future__ import annotations

import json
from typing import Any

from discdeck.commands import CommandRunner


def probe_udisks(runner: CommandRunner | Any, injected: dict[str, Any] | None = None) -> dict[str, Any]:
    if injected is not None:
        objects = normalize_managed_objects(injected)
        return _summarize(objects, activated=False, source="injected")
    listing = runner(["busctl", "--system", "--no-pager", "list"], timeout=5)
    if listing.code == 127:
        return _unavailable("UDISKS2_CLIENT_MISSING", "busctl is not available; UDisks2 was not queried.")
    if listing.code != 0:
        return _unavailable("UDISKS2_BUS_UNAVAILABLE", "The system bus could not be listed.", error=listing.stderr.strip())
    if not _service_has_pid(listing.stdout, "org.freedesktop.UDisks2"):
        return {
            "status": "untested",
            "reason_code": "UDISKS2_INACTIVE",
            "message": "UDisks2 is not an active bus name. Phase 0 did not activate it.",
            "drives": [],
            "activated": False,
            "hardware_validated": False,
        }
    call = runner(
        [
            "busctl",
            "--system",
            "--json=short",
            "call",
            "org.freedesktop.UDisks2",
            "/org/freedesktop/UDisks2",
            "org.freedesktop.DBus.ObjectManager",
            "GetManagedObjects",
        ],
        timeout=8,
    )
    if call.code != 0:
        denied = "denied" in (call.stderr or "").lower() or "denied" in (call.stdout or "").lower()
        return {
            "status": "denied" if denied else "untested",
            "reason_code": "PERMISSION_DENIED" if denied else "UDISKS2_QUERY_FAILED",
            "message": "GetManagedObjects failed.",
            "drives": [],
            "activated": False,
            "hardware_validated": False,
        }
    try:
        payload = json.loads(call.stdout)
        objects = normalize_managed_objects(payload)
    except (json.JSONDecodeError, ValueError):
        return _unavailable("UNSUPPORTED", "UDisks2 returned an unrecognized object payload.")
    summary = _summarize(objects, activated=False, source="busctl")
    return summary


def normalize_managed_objects(payload: Any) -> dict[str, dict[str, dict[str, Any]]]:
    """Accept both busctl JSON shapes.

    Older busctl builds emit D-Bus dictionaries as arrays of pairs. systemd 257,
    which Bazzite 45 ships, emits them as JSON objects and wraps a method reply
    in a one-element list. Both are read-only object maps.
    """
    if isinstance(payload, dict) and "type" in payload and "data" in payload:
        return _from_envelope(payload["data"])
    if isinstance(payload, dict):
        return _from_object_map(payload)
    raise ValueError("Unrecognized UDisks2 payload.")


def classify_optical(drive_props: dict[str, Any], block_props: dict[str, Any], sysfs_type: str | None) -> tuple[bool, list[str]]:
    evidence: list[str] = []
    device = _device_node(block_props.get("Device"))
    if sysfs_type == "5":
        evidence.append("sysfs_type_5")
    if device.startswith("/dev/sr"):
        evidence.append("sr_node")
    optical_property = drive_props.get("Optical")
    if optical_property is True:
        evidence.append("udisks_optical_true")
    # A false Optical property is recorded but cannot cancel stronger evidence.
    if optical_property is False:
        evidence.append("udisks_optical_false_not_authoritative")
    return (any(item in evidence for item in ("sysfs_type_5", "sr_node", "udisks_optical_true")), evidence)


def _summarize(objects: dict[str, dict[str, dict[str, Any]]], *, activated: bool, source: str) -> dict[str, Any]:
    drives = []
    blocks = []
    for path, interfaces in objects.items():
        if "org.freedesktop.UDisks2.Drive" in interfaces:
            drives.append((path, interfaces["org.freedesktop.UDisks2.Drive"]))
        if "org.freedesktop.UDisks2.Block" in interfaces:
            blocks.append((path, interfaces))
    optical = []
    for block_path, interfaces in blocks:
        block_props = interfaces.get("org.freedesktop.UDisks2.Block", {})
        drive_path = block_props.get("Drive")
        drive_props = {}
        if isinstance(drive_path, str):
            drive_props = objects.get(drive_path, {}).get("org.freedesktop.UDisks2.Drive", {})
        device = _device_node(block_props.get("Device"))
        is_optical, evidence = classify_optical(drive_props, block_props, None)
        if not is_optical:
            continue
        media = drive_props.get("MediaAvailable")
        optical.append(
            {
                "udisks_block_path": block_path,
                "udisks_drive_path": drive_path if isinstance(drive_path, str) else None,
                "device": device,
                "optical": True,
                "optical_evidence": evidence,
                "udisks_optical_property": drive_props.get("Optical"),
                "media_available": media if isinstance(media, bool) else "unknown",
                "connection_bus": drive_props.get("ConnectionBus"),
                "ejectable": drive_props.get("Ejectable"),
                "vendor": drive_props.get("Vendor"),
                "model": drive_props.get("Model"),
                "size": block_props.get("Size"),
                "operations": {"mount": "not_run", "unmount": "not_run", "eject": "not_run", "loop_setup": "not_run"},
                "hardware_validated": False,
            }
        )
    return {
        "status": "observed",
        "reason_code": None,
        "message": "UDisks2 objects were read. No mount or eject method was called.",
        "source": source,
        "activated": activated,
        "drive_object_count": len(drives),
        "drives": optical,
        "hardware_validated": False,
    }


def _from_envelope(data: Any) -> dict[str, dict[str, dict[str, Any]]]:
    if isinstance(data, dict):
        return _from_object_map(data)
    if isinstance(data, list) and data and all(isinstance(item, dict) for item in data):
        merged: dict[str, Any] = {}
        for item in data:
            merged.update(item)
        return _from_object_map(merged)
    if isinstance(data, list):
        return _from_busctl(data)
    raise ValueError("Unrecognized UDisks2 payload.")


def _from_object_map(objects: dict[Any, Any]) -> dict[str, dict[str, dict[str, Any]]]:
    normalized: dict[str, dict[str, dict[str, Any]]] = {}
    for path, interfaces in objects.items():
        if not isinstance(interfaces, dict):
            continue
        parsed: dict[str, dict[str, Any]] = {}
        for name, properties in interfaces.items():
            if isinstance(properties, dict):
                parsed[str(name)] = {str(key): _unwrap(value) for key, value in properties.items()}
            elif isinstance(properties, list):
                parsed[str(name)] = _pairs(properties)
        normalized[str(path)] = parsed
    return normalized


def _from_busctl(data: list[Any]) -> dict[str, dict[str, dict[str, Any]]]:
    objects: dict[str, dict[str, dict[str, Any]]] = {}
    for entry in data:
        path, interfaces = entry
        parsed_interfaces: dict[str, dict[str, Any]] = {}
        for interface_name, properties in interfaces:
            parsed_interfaces[str(interface_name)] = _pairs(properties)
        objects[str(path)] = parsed_interfaces
    return objects


def _pairs(properties: list[Any]) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    for item in properties:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            parsed[str(item[0])] = _unwrap(item[1])
    return parsed


def _unwrap(value: Any) -> Any:
    if isinstance(value, dict) and "data" in value and "type" in value:
        return _unwrap(value["data"])
    return value


def _device_node(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        characters = []
        for item in value:
            if isinstance(item, int):
                if item == 0:
                    break
                characters.append(chr(item))
        return "".join(characters)
    return ""


def _service_has_pid(listing: str, name: str) -> bool:
    for line in listing.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == name and parts[1].isdigit():
            return True
    return False


def _unavailable(code: str, message: str, error: str | None = None) -> dict[str, Any]:
    status = "unsupported" if code == "UNSUPPORTED" else "missing"
    body: dict[str, Any] = {
        "status": status,
        "reason_code": code,
        "message": message,
        "drives": [],
        "activated": False,
        "hardware_validated": False,
    }
    if error:
        body["error"] = error[:300]
    return body
