"""Map optical block devices to their generic SCSI nodes.

The mapping follows ``/sys/class/block/sr*/device/scsi_generic``. Numeric
suffixes are not paired, and an unrelated ``/dev/sg*`` node is never selected.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

SCSI_ADDRESS = re.compile(r"\d+:\d+:\d+:\d+")


def enumerate_optical(sysfs_root: Path, epoch: str) -> dict[str, Any]:
    block_root = sysfs_root / "class" / "block"
    if not block_root.is_dir():
        return {
            "status": "missing",
            "reason_code": "SYSFS_BLOCK_UNAVAILABLE",
            "message": "sysfs block class is not available in this environment.",
            "drives": [],
            "ignored_generic_nodes": _unlinked_generic_nodes(sysfs_root, set()),
            "hardware_validated": False,
        }
    drives: list[dict[str, Any]] = []
    linked_generic: set[str] = set()
    for entry in sorted(block_root.iterdir(), key=lambda item: item.name):
        if not entry.name.startswith("sr"):
            continue
        drive = _read_sr(entry, epoch)
        if drive is None:
            continue
        if drive.get("generic_scsi_name"):
            linked_generic.add(str(drive["generic_scsi_name"]))
        drives.append(drive)
    _mark_shared_bridges(drives)
    return {
        "status": "observed" if drives else "untested",
        "reason_code": None if drives else "NO_OPTICAL_NODES",
        "message": "Optical block devices were enumerated from sysfs." if drives else "No sr block devices were present.",
        "drives": drives,
        "ignored_generic_nodes": _unlinked_generic_nodes(sysfs_root, linked_generic),
        "hardware_validated": False,
    }


def _read_sr(entry: Path, epoch: str) -> dict[str, Any] | None:
    device = entry / "device"
    if not device.exists():
        return None
    try:
        device_path = device.resolve()
    except OSError:
        return None
    vendor = _sysfs_text(device_path / "vendor")
    model = _sysfs_text(device_path / "model")
    revision = _sysfs_text(device_path / "rev")
    device_type = _sysfs_text(device_path / "type")
    generic_name = _generic_name(device_path)
    scsi_address = _scsi_address(device_path)
    usb_vendor, usb_product, usb_port = _usb_identity(device_path)
    identity_source = "|".join(
        [
            epoch,
            str(device_path),
            vendor,
            model,
            revision,
            scsi_address or "",
            usb_port or "",
            usb_vendor or "",
            usb_product or "",
        ]
    )
    digest = hashlib.sha256(identity_source.encode("utf-8")).hexdigest()[:16]
    optical = device_type == "5" or entry.name.startswith("sr")
    return {
        "drive_id": f"drv_{digest}",
        "generation": 1,
        "generation_tracking": "not_implemented",
        "block_name": entry.name,
        "block_node": f"/dev/{entry.name}",
        "generic_scsi_name": generic_name,
        "generic_scsi_node": f"/dev/{generic_name}" if generic_name else None,
        "vendor": vendor,
        "model": model,
        "revision": revision,
        "serial": None,
        "scsi_address": scsi_address,
        "lun": _lun(scsi_address),
        "usb_port": usb_port,
        "usb_vendor_id": usb_vendor,
        "usb_product_id": usb_product,
        "usb_id": f"{usb_vendor}:{usb_product}" if usb_vendor and usb_product else None,
        "sysfs_device": str(device_path),
        "device_type": device_type,
        "optical": optical,
        "optical_evidence": ["sysfs_type_5"] if device_type == "5" else ["sr_node_name"],
        "shared_bridge": False,
        "media_present": "unknown",
        "operations": {
            "mount": "not_run",
            "unmount": "not_run",
            "eject": "not_run",
            "tray_close": "not_run",
            "dump": "not_run",
            "sg_io": "not_run",
        },
        "hardware_validated": False,
    }


def _generic_name(device_path: Path) -> str | None:
    generic_dir = device_path / "scsi_generic"
    if not generic_dir.is_dir():
        return None
    names = sorted(path.name for path in generic_dir.iterdir() if path.name.startswith("sg"))
    return names[0] if names else None


def _scsi_address(device_path: Path) -> str | None:
    match = SCSI_ADDRESS.search(device_path.name)
    if match:
        return match.group(0)
    for parent in device_path.parents:
        match = SCSI_ADDRESS.search(parent.name)
        if match:
            return match.group(0)
    return None


def _lun(scsi_address: str | None) -> int | None:
    if not scsi_address:
        return None
    return int(scsi_address.rsplit(":", 1)[1])


def _usb_identity(device_path: Path) -> tuple[str | None, str | None, str | None]:
    for parent in [device_path, *device_path.parents]:
        vendor = parent / "idVendor"
        product = parent / "idProduct"
        if vendor.is_file() and product.is_file():
            return _sysfs_text(vendor).lower(), _sysfs_text(product).lower(), parent.name
    return None, None, None


def _mark_shared_bridges(drives: list[dict[str, Any]]) -> None:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for drive in drives:
        if drive["usb_port"] and drive["usb_vendor_id"] and drive["usb_product_id"]:
            key = (drive["usb_port"], drive["usb_vendor_id"], drive["usb_product_id"])
            groups.setdefault(key, []).append(drive)
    for grouped in groups.values():
        if len(grouped) > 1:
            for drive in grouped:
                drive["shared_bridge"] = True


def _unlinked_generic_nodes(sysfs_root: Path, linked: set[str]) -> list[str]:
    root = sysfs_root / "class" / "scsi_generic"
    if not root.is_dir():
        return []
    names = []
    for entry in sorted(root.iterdir(), key=lambda item: item.name):
        if entry.name.startswith("sg") and entry.name not in linked:
            names.append(f"/dev/{entry.name}")
    return names


def _sysfs_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
