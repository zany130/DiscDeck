"""VHBA and CDEmu presence checks that do not activate the daemon.

An installed but inactive user service is neither missing nor ready. This
probe does not start the daemon or load an image. An explicit virtual-disc
request is the only path that does.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from discdeck.commands import CommandRunner


def probe_cdemu(
    runner: CommandRunner | Any,
    *,
    root: Path,
    sysfs_root: Path,
    dev_root: Path,
) -> dict[str, Any]:
    client = root / "usr" / "bin" / "cdemu"
    daemon = root / "usr" / "bin" / "cdemu-daemon"
    unit = root / "usr" / "lib" / "systemd" / "user" / "cdemu-daemon.service"
    service_file = root / "usr" / "share" / "dbus-1" / "services" / "net.sf.cdemu.CDEmuDaemon.service"
    vhba_dir = sysfs_root / "module" / "vhba"
    vhba_ctl = dev_root / "vhba_ctl"
    installed = client.is_file() or daemon.is_file() or unit.is_file() or service_file.is_file()
    listing = runner(["busctl", "--user", "--no-pager", "list"], timeout=5)
    bus_state = "client_missing" if listing.code == 127 else "listed" if listing.code == 0 else "unavailable"
    active = listing.code == 0 and _has_pid(listing.stdout, "net.sf.cdemu.CDEmuDaemon")
    activatable = service_file.is_file() or (listing.code == 0 and "net.sf.cdemu.CDEmuDaemon" in listing.stdout)
    activity = None
    if unit.is_file() and bus_state != "client_missing":
        systemctl = runner(["systemctl", "--user", "is-active", "cdemu-daemon.service"], timeout=3)
        if systemctl.code != 127:
            activity = _first(systemctl.stdout) or _first(systemctl.stderr)
            if activity in {"active", "running"}:
                active = True
            elif activity in {"inactive", "dead", "failed"}:
                active = False
    if not installed and not vhba_dir.is_dir() and not vhba_ctl.exists():
        status = "missing"
        reason = "CDEMU_MISSING"
        message = "CDEmu and VHBA were not found."
    elif installed and not active:
        status = "untested"
        reason = "DAEMON_INACTIVE"
        message = "CDEmu files are installed, but the daemon was not running. A refresh does not start it or load an image."
    elif active:
        status = "untested"
        reason = "DAEMON_INTERFACE_NOT_VALIDATED"
        message = "A CDEmu bus owner was visible. A refresh does not load an image."
    else:
        status = "untested"
        reason = "CDEMU_UNVERIFIED"
        message = "CDEmu readiness could not be established."
    return {
        "status": status,
        "reason_code": reason,
        "message": message,
        "client_present": client.is_file(),
        "daemon_bin_present": daemon.is_file(),
        "unit_present": unit.is_file(),
        "dbus_service_file_present": service_file.is_file(),
        "vhba_loaded": vhba_dir.is_dir(),
        "vhba_ctl_present": vhba_ctl.exists(),
        "activatable": activatable,
        "active": active,
        "service_activity": activity,
        "bus_state": bus_state,
        "interface_queried": False,
        "slots_queried": False,
        "image_load": "not_run",
        "hardware_validated": False,
    }


def _has_pid(listing: str, name: str) -> bool:
    for line in listing.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == name and parts[1].isdigit():
            return True
    return False


def _first(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""
