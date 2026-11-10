"""Synthetic host fixtures derived from the redacted Phase 0 inventory.

The shapes match the measured shared USB bridge, named ACLs, and installed but
inactive services. They do not claim those operations succeeded.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from discdeck.commands import CommandResult


def write_host_sysfs(root: Path) -> Path:
    sysfs = root / "sys"
    _optical_device(
        sysfs,
        name="sr0",
        generic="sg1",
        usb_port="4-2.3",
        usb_parent="usb4",
        vendor_id="13fd",
        product_id="5912",
        scsi="4:0:0:0",
        vendor="Generic",
        model="External",
        revision="AL32",
    )
    _optical_device(
        sysfs,
        name="sr1",
        generic="sg2",
        usb_port="3-2.4.1",
        usb_parent="usb3",
        vendor_id="152d",
        product_id="2338",
        scsi="7:0:0:0",
        vendor="TSSTcorp",
        model="DVD-ROM SH-D163B",
        revision="SB01",
    )
    _optical_device(
        sysfs,
        name="sr2",
        generic="sg3",
        usb_port="3-2.4.1",
        usb_parent="usb3",
        vendor_id="152d",
        product_id="2338",
        scsi="7:0:0:1",
        vendor="PLEXTOR",
        model="CD-R PX-W4012A",
        revision="1.07",
    )
    (sysfs / "class" / "scsi_generic" / "sg0").mkdir(parents=True)
    return sysfs


def write_cdemu_installation(root: Path, sysfs: Path, dev: Path, *, active_unit: bool = False) -> None:
    for relative in (
        "usr/bin/cdemu",
        "usr/bin/cdemu-daemon",
        "usr/lib/systemd/user/cdemu-daemon.service",
        "usr/share/dbus-1/services/net.sf.cdemu.CDEmuDaemon.service",
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture\n", encoding="utf-8")
    (sysfs / "module" / "vhba").mkdir(parents=True)
    (sysfs / "module" / "vhba" / "version").write_text("20260313\n", encoding="utf-8")
    dev.mkdir(parents=True, exist_ok=True)
    (dev / "vhba_ctl").write_text("", encoding="utf-8")
    if active_unit:
        (root / "usr/lib/systemd/user/cdemu-daemon.service").write_text("active-fixture\n", encoding="utf-8")


def write_redumper_wrapper(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "redumper"
    path.write_text(
        "#!/bin/sh\n# distrobox-export wrapper\nexec distrobox enter arch -- /usr/bin/redumper \"$@\"\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def write_native_redumper(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "redumper"
    path.write_bytes(b"\x7fELF-fixture-not-a-real-binary")
    path.chmod(0o755)
    return path


def write_steam_home(home: Path) -> Path:
    steam = home / ".local" / "share" / "Steam"
    link_parent = home / ".steam"
    link_parent.mkdir(parents=True)
    (link_parent / "steam").symlink_to(os.path.relpath(steam, link_parent), target_is_directory=True)
    steamapps = steam / "steamapps"
    steamapps.mkdir(parents=True)
    (steamapps / "libraryfolders.vdf").write_text(
        '"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"' + str(steam) + '"\n\t}\n}\n',
        encoding="utf-8",
    )
    (steam / "compatibilitytools.d" / "GE-Proton10-34").mkdir(parents=True)
    (steamapps / "common" / "Proton 10.0").mkdir(parents=True)
    shortcuts = steam / "userdata" / "1" / "config"
    shortcuts.mkdir(parents=True)
    (shortcuts / "shortcuts.vdf").write_bytes(b"do-not-read")
    prefix = steamapps / "compatdata" / "123" / "pfx"
    prefix.mkdir(parents=True)
    (prefix / "user.reg").write_text("do-not-read\n", encoding="utf-8")
    return steam


def udisks_busctl_payload() -> str:
    payload = {
        "type": "a{oa{sa{sv}}}",
        "data": [
            [
                "/org/freedesktop/UDisks2/block_devices/sr1",
                [
                    [
                        "org.freedesktop.UDisks2.Block",
                        [
                            ["Device", {"type": "ay", "data": [ord(char) for char in "/dev/sr1"] + [0]}],
                            ["Drive", {"type": "o", "data": "/org/freedesktop/UDisks2/drives/bridge_lun0"}],
                            ["Size", {"type": "t", "data": 0}],
                        ],
                    ]
                ],
            ],
            [
                "/org/freedesktop/UDisks2/drives/bridge_lun0",
                [
                    [
                        "org.freedesktop.UDisks2.Drive",
                        [
                            ["Optical", {"type": "b", "data": False}],
                            ["MediaAvailable", {"type": "b", "data": False}],
                            ["ConnectionBus", {"type": "s", "data": "usb"}],
                            ["Ejectable", {"type": "b", "data": True}],
                            ["Vendor", {"type": "s", "data": "TSSTcorp"}],
                            ["Model", {"type": "s", "data": "DVD-ROM SH-D163B"}],
                        ],
                    ]
                ],
            ],
        ],
    }
    return json.dumps(payload)


def scripted_bus_responses(udisks_json: str, *, cdemu_active: bool = False) -> dict[tuple[str, ...], CommandResult]:
    cdemu_line = "net.sf.cdemu.CDEmuDaemon 99 cdemu-daemon hostuser\n" if cdemu_active else "net.sf.cdemu.CDEmuDaemon - - -\n"
    activity = "active\n" if cdemu_active else "inactive\n"
    return {
        ("busctl", "--system", "--no-pager", "list"): CommandResult(
            ["busctl", "--system", "--no-pager", "list"],
            0,
            "org.freedesktop.UDisks2 4242 udisksd root\n",
            "",
        ),
        (
            "busctl",
            "--system",
            "--json=short",
            "call",
            "org.freedesktop.UDisks2",
            "/org/freedesktop/UDisks2",
            "org.freedesktop.DBus.ObjectManager",
            "GetManagedObjects",
        ): CommandResult(["busctl"], 0, udisks_json, ""),
        ("busctl", "--user", "--no-pager", "list"): CommandResult(["busctl", "--user", "--no-pager", "list"], 0, cdemu_line, ""),
        ("systemctl", "--user", "is-active", "cdemu-daemon.service"): CommandResult(
            ["systemctl", "--user", "is-active", "cdemu-daemon.service"],
            0 if cdemu_active else 3,
            activity,
            "",
        ),
    }


def named_acl(node: str) -> str:
    return f"# file: {node}\nuser::rw-\nuser:hostuser:rw-\ngroup::rw-\nmask::rw-\nother::---\n"


def _optical_device(
    sysfs: Path,
    *,
    name: str,
    generic: str,
    usb_port: str,
    usb_parent: str,
    vendor_id: str,
    product_id: str,
    scsi: str,
    vendor: str,
    model: str,
    revision: str,
) -> None:
    host = scsi.split(":", 1)[0]
    usb_dir = sysfs / "devices" / usb_parent / usb_port
    device = usb_dir / f"{usb_port}:1.0" / f"host{host}" / f"target{scsi.rsplit(':', 1)[0]}" / scsi
    device.mkdir(parents=True, exist_ok=True)
    (usb_dir / "idVendor").write_text(vendor_id + "\n", encoding="utf-8")
    (usb_dir / "idProduct").write_text(product_id + "\n", encoding="utf-8")
    (device / "vendor").write_text(vendor + "\n", encoding="utf-8")
    (device / "model").write_text(model + "\n", encoding="utf-8")
    (device / "rev").write_text(revision + "\n", encoding="utf-8")
    (device / "type").write_text("5\n", encoding="utf-8")
    (device / "scsi_generic" / generic).mkdir(parents=True)
    link = sysfs / "class" / "block" / name / "device"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(os.path.relpath(device, link.parent), target_is_directory=True)
