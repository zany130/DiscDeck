"""Compose diagnostic probes and explicit disc actions into one snapshot."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from discdeck.adapters.cdemu import probe_cdemu
from discdeck.adapters.devices import enumerate_optical
from discdeck.adapters.permissions import inspect_nodes
from discdeck.adapters.redumper import discover as discover_redumper
from discdeck.adapters.redumper import read_version as read_redumper_version
from discdeck.adapters.steam import probe_steam
from discdeck.adapters.udisks2 import probe_udisks
from discdeck.commands import CommandRunner
from discdeck.images import ImageLibrary
from discdeck.models import DEFAULT_MODULE_ENABLED, envelope_error, envelope_ok, module_status
from discdeck.physical import GenerationTracker, PhysicalOperations
from discdeck.runtime import probe_runtime, read_build_info
from discdeck.security import assert_physical_udisks_argv
from discdeck.settings import load_settings

LIMITATIONS = (
    "Mount, unmount, and eject run only after an explicit request. Tray close is not attempted.",
    "A filesystem image is mounted only after an ISO is picked. It is not a virtual disc, and CDEmu is not used.",
    "A readable inventory is not a passed hardware gate. hardware_validated stays false.",
    "Runtime-directory durability across Decky restarts was not measured.",
    "Redumper is not executed when the discovered file is a container wrapper.",
    "An inactive CDEmu daemon is not activated and its device methods are not called.",
    "Steam shortcuts and Proton prefixes are not read or modified.",
)


class DiagnosticService:
    def __init__(
        self,
        *,
        environ: dict[str, str],
        os_module: Any,
        pwd_module: Any,
        runner: Any | None = None,
        mutation_runner: Any | None = None,
        sysfs_root: Path | None = None,
        root: Path | None = None,
        dev_root: Path | None = None,
        home: Path | None = None,
        epoch: str | None = None,
        module_dir: Path | None = None,
        access: Any = None,
        getfacl: Any = None,
        stat_fn: Any = None,
    ) -> None:
        self.environ = environ
        self.os_module = os_module
        self.pwd_module = pwd_module
        self.runner = runner or CommandRunner()
        self.mutation_runner = mutation_runner or CommandRunner(policy=assert_physical_udisks_argv)
        self.generations = GenerationTracker()
        self.physical = PhysicalOperations(self)
        self.images = ImageLibrary(self)
        self.sysfs_root = sysfs_root or Path("/sys")
        self.root = root or Path("/")
        self.dev_root = dev_root or Path("/dev")
        self.home = home if home is not None else _home_from_env(environ)
        self.epoch = epoch or uuid.uuid4().hex
        self.revision = 0
        self.module_dir = module_dir or Path(__file__).resolve().parent
        self.lifecycle_phase = "created"
        self.access = access
        self.getfacl = getfacl
        self.stat_fn = stat_fn

    def snapshot(self) -> dict[str, Any]:
        checked_at = _now()
        runtime = probe_runtime(self.os_module, self.pwd_module, self.environ)
        settings_path = _settings_path(self.environ)
        settings_state = load_settings(settings_path)
        enabled = dict(DEFAULT_MODULE_ENABLED)
        enabled.update({key: bool(value) for key, value in settings_state["settings"]["modules"].items()})
        devices = enumerate_optical(self.sysfs_root, self.epoch)
        udisks = probe_udisks(self.runner)
        _merge_media(devices["drives"], udisks.get("drives", []))
        self.generations.observe(devices["drives"])
        permission_kwargs: dict[str, Any] = {}
        if self.access is not None:
            permission_kwargs["access"] = self.access
        if self.getfacl is not None:
            permission_kwargs["getfacl"] = self.getfacl
        if self.stat_fn is not None:
            permission_kwargs["stat_fn"] = self.stat_fn
        permissions = inspect_nodes(_permission_nodes(devices["drives"], self.dev_root), **permission_kwargs)
        redumper = discover_redumper(self.environ, settings_state["settings"].get("redumper_binary"))
        cdemu = probe_cdemu(self.runner, root=self.root, sysfs_root=self.sysfs_root, dev_root=self.dev_root)
        steam = probe_steam(self.home, self.environ, self.root)
        modules = _modules(
            enabled=enabled,
            checked_at=checked_at,
            devices=devices,
            udisks=udisks,
            permissions=permissions,
            redumper=redumper,
            cdemu=cdemu,
            steam=steam,
            settings_status=settings_state["status"],
        )
        self.revision += 1
        return {
            "epoch": self.epoch,
            "revision": self.revision,
            "phase": "2",
            "hardware_validated": False,
            "settings_revision": settings_state["settings_revision"],
            "settings": settings_state,
            "identity": runtime,
            "build": read_build_info(self.module_dir),
            "modules": modules,
            "drives": devices["drives"],
            "images": self.images.public_records(),
            "virtual_slots": [],
            "jobs": [],
            "probes": {
                "runtime": runtime,
                "devices": {key: value for key, value in devices.items() if key != "drives"},
                "udisks2": {key: value for key, value in udisks.items() if key != "drives"},
                "permissions": permissions,
                "redumper": redumper,
                "cdemu": cdemu,
                "steam": {key: value for key, value in steam.items() if key != "files_read"},
            },
            "limitations": list(LIMITATIONS),
        }

    def snapshot_envelope(self) -> dict[str, Any]:
        try:
            result = self.snapshot()
        except Exception as exc:  # noqa: BLE001 - boundary converts failures to envelopes
            return envelope_error("INTERNAL_ERROR", str(exc), retryable=True, revision=self.revision, epoch=self.epoch)
        return envelope_ok(result, result["revision"], self.epoch)

    def diagnostics_envelope(self, module_id: str | None = None) -> dict[str, Any]:
        envelope = self.snapshot_envelope()
        if not envelope["ok"] or not module_id:
            return envelope
        modules = [item for item in envelope["result"]["modules"] if item["id"] == module_id]
        if not modules:
            return envelope_error(
                "UNSUPPORTED",
                f"Unknown module {module_id}.",
                retryable=False,
                revision=self.revision,
                epoch=self.epoch,
            )
        return envelope_ok(
            {"module": modules[0], "hardware_validated": False, "phase": "2"},
            self.revision,
            self.epoch,
        )

    def probe_envelope(self, module_id: str) -> dict[str, Any]:
        return self.diagnostics_envelope(module_id)

    def probe_event(self) -> dict[str, Any]:
        if self.revision == 0:
            self.snapshot()
        return {"epoch": self.epoch, "revision": self.revision, "domain": "diagnostics"}

    def redumper_version_envelope(self, allow_untested_wrapper: bool = False) -> dict[str, Any]:
        settings_state = load_settings(_settings_path(self.environ))
        configured = settings_state["settings"].get("redumper_binary")
        current = discover_redumper(self.environ, configured if isinstance(configured, str) else None)
        path = current.get("path")
        if not path:
            self.revision += 1
            return envelope_ok(current, self.revision, self.epoch)
        try:
            result = read_redumper_version(path, self.runner, allow_untested_wrapper=allow_untested_wrapper)
        except Exception as exc:  # noqa: BLE001
            return envelope_error("INTERNAL_ERROR", str(exc), retryable=False, revision=self.revision, epoch=self.epoch)
        self.revision += 1
        return envelope_ok(result, self.revision, self.epoch)

    def mount_drive(self, drive_id: str, generation: int, media_generation: int) -> dict[str, Any]:
        return self.physical.mount(drive_id, generation, media_generation)

    def unmount_drive(self, drive_id: str, generation: int) -> dict[str, Any]:
        return self.physical.unmount(drive_id, generation)

    def eject_drive(self, drive_id: str, generation: int, confirmed: bool) -> dict[str, Any]:
        return self.physical.eject(drive_id, generation, confirmed)

    def close_tray(self, drive_id: str) -> dict[str, Any]:
        return self.physical.close_tray(drive_id)

    def mount_iso(self, path: str) -> dict[str, Any]:
        return self.images.mount(path)

    def unmount_iso(self, image_id: str) -> dict[str, Any]:
        return self.images.unmount(image_id)


def _modules(
    *,
    enabled: dict[str, bool],
    checked_at: str,
    devices: dict[str, Any],
    udisks: dict[str, Any],
    permissions: dict[str, Any],
    redumper: dict[str, Any],
    cdemu: dict[str, Any],
    steam: dict[str, Any],
    settings_status: str,
) -> list[dict[str, Any]]:
    physical_capability, physical_reason, physical_message = _physical_capability(devices, udisks)
    iso_capability, iso_reason, iso_message = _iso_capability(udisks)
    dump_capability, dump_reason, dump_message = _dump_capability(redumper, devices, permissions)
    return [
        module_status(
            "physical",
            enabled=enabled["physical"],
            capability=physical_capability,
            reason_code=physical_reason,
            message=physical_message,
            checked_at=checked_at,
            details={"drive_count": len(devices["drives"]), "udisks_status": udisks["status"], "settings_status": settings_status},
        ),
        module_status(
            "images.iso",
            enabled=enabled["images.iso"],
            capability=iso_capability,
            reason_code=iso_reason,
            message=iso_message,
            checked_at=checked_at,
            details={"loop_setup": "not_run"},
        ),
        module_status(
            "dump.redumper",
            enabled=enabled["dump.redumper"],
            capability=dump_capability,
            reason_code=dump_reason,
            message=dump_message,
            checked_at=checked_at,
            details={"version_status": redumper.get("version_status"), "launch_kind": redumper.get("launch_kind")},
        ),
        module_status(
            "virtual.cdemu",
            enabled=enabled["virtual.cdemu"],
            capability=_coerce_capability(cdemu["status"]),
            reason_code=cdemu["reason_code"],
            message=cdemu["message"],
            checked_at=checked_at,
            details={"active": cdemu["active"], "vhba_loaded": cdemu["vhba_loaded"], "image_load": "not_run"},
        ),
        module_status(
            "resources.pcgamingwiki",
            enabled=enabled["resources.pcgamingwiki"],
            capability="untested",
            reason_code="NOT_PROBED",
            message="No wiki request is made during Phase 0.",
            checked_at=checked_at,
        ),
        module_status(
            "launch.experimental",
            enabled=enabled["launch.experimental"],
            capability=_coerce_capability(steam["status"]),
            reason_code=steam["reason_code"],
            message=steam["message"],
            checked_at=checked_at,
            details={"shortcuts_read": False, "launched": False},
        ),
        module_status(
            "launch.autoplay",
            enabled=enabled["launch.autoplay"],
            capability="untested",
            reason_code="AUTOPLAY_OFF",
            message="Autoplay is off and was not exercised.",
            checked_at=checked_at,
        ),
    ]


def _physical_capability(devices: dict[str, Any], udisks: dict[str, Any]) -> tuple[str, str, str]:
    if devices["drives"] and udisks["status"] == "observed":
        return (
            "ready",
            "INVENTORY_OBSERVED",
            "UDisks2 inventory is readable. Mount and eject are available, but they are not hardware-validated.",
        )
    if devices["drives"] or udisks["status"] == "observed":
        return (
            "untested",
            "MEDIA_OPERATIONS_NOT_RUN",
            "Optical inventory was observed. Mount and eject stay unavailable until UDisks2 can be read.",
        )
    if udisks["status"] == "denied":
        return ("denied", "PERMISSION_DENIED", "UDisks2 refused the read-only object query.")
    if devices["status"] == "missing" and udisks["status"] == "missing":
        return ("missing", udisks.get("reason_code") or devices.get("reason_code"), "No optical inventory source is available.")
    return ("untested", devices.get("reason_code") or udisks.get("reason_code"), "Optical inventory could not be proven.")


def _iso_capability(udisks: dict[str, Any]) -> tuple[str, str, str]:
    if udisks["status"] == "observed":
        return (
            "ready",
            "UDISKS_OBSERVED",
            "UDisks2 can be read. A read-only ISO loop can be requested. It is not a virtual optical drive and it is not hardware-validated.",
        )
    if udisks["status"] == "missing":
        return ("missing", udisks["reason_code"], "ISO loop setup was not attempted because UDisks2 is unavailable.")
    if udisks["status"] == "denied":
        return ("denied", "PERMISSION_DENIED", "UDisks2 denied the read-only query, so loop setup was not attempted.")
    return ("untested", "LOOPSETUP_NOT_RUN", "Read-only ISO loop setup was not run.")


def _dump_capability(redumper: dict[str, Any], devices: dict[str, Any], permissions: dict[str, Any]) -> tuple[str, str, str]:
    if redumper["status"] == "missing":
        return ("missing", "REDUMPER_MISSING", redumper["message"])
    sg_nodes = [drive["generic_scsi_node"] for drive in devices["drives"] if drive.get("generic_scsi_node")]
    relevant = [node for node in permissions["nodes"] if node["node"] in sg_nodes]
    if sg_nodes and relevant and all(node["status"] == "denied" for node in relevant):
        return ("denied", "SG_ACCESS_DENIED", "The effective user cannot access the mapped generic SCSI nodes.")
    return ("untested", "DUMP_NOT_RUN", "Redumper discovery does not prove a dump, an SG_IO transfer, or a supported command line.")


def _coerce_capability(status: str) -> str:
    if status in {"missing", "denied", "unsupported", "untested", "degraded"}:
        return status
    return "untested"


def _permission_nodes(drives: list[dict[str, Any]], dev_root: Path) -> list[str]:
    nodes: list[str] = []
    for drive in drives:
        nodes.append(drive["block_node"])
        if drive.get("generic_scsi_node"):
            nodes.append(drive["generic_scsi_node"])
    vhba = dev_root / "vhba_ctl"
    if vhba.exists():
        nodes.append(str(vhba))
    return nodes


def _merge_media(drives: list[dict[str, Any]], udisks_drives: list[dict[str, Any]]) -> None:
    by_device = {item.get("device"): item for item in udisks_drives}
    for drive in drives:
        match = by_device.get(drive["block_node"])
        if not match:
            continue
        media = match.get("media_available")
        drive["media_present"] = media if isinstance(media, bool) else "unknown"
        drive["udisks_optical_property"] = match.get("udisks_optical_property")
        drive["udisks_block_path"] = match.get("udisks_block_path")
        drive["udisks_drive_path"] = match.get("udisks_drive_path")
        drive["filesystem"] = bool(match.get("filesystem"))
        drive["mount_points"] = list(match.get("mount_points") or [])
        evidence = list(drive["optical_evidence"])
        for item in match.get("optical_evidence", []):
            if item not in evidence:
                evidence.append(item)
        drive["optical_evidence"] = evidence
        drive["optical"] = True


def _settings_path(environ: dict[str, str]) -> Path | None:
    directory = environ.get("DECKY_PLUGIN_SETTINGS_DIR")
    if not directory:
        return None
    return Path(directory) / "settings.json"


def _home_from_env(environ: dict[str, str]) -> Path | None:
    raw = environ.get("DECKY_USER_HOME") or environ.get("HOME")
    if not raw:
        return None
    return Path(raw)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
