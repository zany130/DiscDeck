import os
import pwd

import decky

from discdeck.diagnostics import DiagnosticService
from discdeck.lifecycle import Lifecycle
from discdeck.models import envelope_error, envelope_ok
from discdeck.redumper_bundle import remove_updated_copy
from discdeck.runtime import read_build_info


class Plugin:
    """Decky lifecycle, diagnostics, and explicit disc actions.

    Mount is read-only. Eject requires confirmation. A dump runs only after
    a request and is not verified by Redumper's exit code. A virtual disc
    loads only after a .cue or .iso is picked. Tray close and game launch
    are not implemented.
    """

    def __init__(self) -> None:
        self.lifecycle = Lifecycle()
        self.service = DiagnosticService(environ=dict(os.environ), os_module=os, pwd_module=pwd)
        self.service.log = lambda message: decky.logger.info("%s", message)

    async def _main(self) -> None:
        await self.lifecycle.main()
        self.service.lifecycle_phase = self.lifecycle.phase
        info = read_build_info(self.service.module_dir)
        decky.logger.info(
            "DiscDeck %s phase %s loaded (effective uid %s). No disc operation was started.",
            info.get("version") or "unversioned",
            info.get("phase"),
            os.geteuid(),
        )

    async def _unload(self) -> None:
        await self.lifecycle.unload()
        self.service.lifecycle_phase = self.lifecycle.phase
        decky.logger.info("DiscDeck unloaded without ejecting media or stopping foreign processes.")

    async def _uninstall(self) -> None:
        removed = remove_updated_copy(self.service.environ)
        await self.lifecycle.uninstall()
        self.service.lifecycle_phase = self.lifecycle.phase
        if removed:
            decky.logger.info("Removed the optional Redumper update. Other DiscDeck settings were left in place.")
        decky.logger.info("DiscDeck uninstalled. User data, mounts, shortcuts, and prefixes were left in place.")

    async def get_snapshot(self) -> dict:
        return self.service.snapshot_envelope()

    async def get_diagnostics(self, module_id: str | None = None) -> dict:
        return self.service.diagnostics_envelope(module_id)

    async def probe_module(self, module_id: str) -> dict:
        if not isinstance(module_id, str) or not module_id:
            return envelope_error("UNSUPPORTED", "module_id is required.", retryable=False, epoch=self.service.epoch)
        return self.service.probe_envelope(module_id)

    async def ping(self) -> dict:
        self.service.revision += 1
        return envelope_ok(
            {"pong": True, "phase": "4", "hardware_validated": False},
            self.service.revision,
            self.service.epoch,
        )

    async def emit_probe_event(self) -> dict:
        payload = self.service.probe_event()
        await decky.emit("discdeck:changed", payload)
        return envelope_ok(payload, payload["revision"], payload["epoch"])

    async def check_update(self) -> dict:
        return self.service.check_update()

    async def read_redumper_version(self, allow_untested_wrapper: bool = False) -> dict:
        del allow_untested_wrapper
        return self.service.redumper_version_envelope()

    async def update_redumper(self) -> dict:
        result = self.service.update_redumper()
        await decky.emit(
            "discdeck:changed",
            {"epoch": self.service.epoch, "revision": self.service.revision, "domain": "redumper"},
        )
        return result

    async def mount_filesystem(self, drive_id: str, generation: int, media_generation: int) -> dict:
        result = self.service.mount_drive(drive_id, int(generation), int(media_generation))
        await decky.emit("discdeck:changed", {"epoch": self.service.epoch, "revision": self.service.revision, "domain": "physical", "id": drive_id})
        return result

    async def unmount_filesystem(self, drive_id: str, generation: int) -> dict:
        result = self.service.unmount_drive(drive_id, int(generation))
        await decky.emit("discdeck:changed", {"epoch": self.service.epoch, "revision": self.service.revision, "domain": "physical", "id": drive_id})
        return result

    async def eject_drive(self, drive_id: str, generation: int, confirmed: bool = False) -> dict:
        result = self.service.eject_drive(drive_id, int(generation), bool(confirmed))
        await decky.emit("discdeck:changed", {"epoch": self.service.epoch, "revision": self.service.revision, "domain": "physical", "id": drive_id})
        return result

    async def mount_iso(self, path: str) -> dict:
        result = self.service.mount_iso(str(path))
        image_id = result.get("result", {}).get("image_id") if isinstance(result.get("result"), dict) else None
        await decky.emit("discdeck:changed", {"epoch": self.service.epoch, "revision": self.service.revision, "domain": "images", "id": image_id})
        return result

    async def unmount_iso(self, image_id: str) -> dict:
        result = self.service.unmount_iso(str(image_id))
        await decky.emit("discdeck:changed", {"epoch": self.service.epoch, "revision": self.service.revision, "domain": "images", "id": image_id})
        return result

    async def start_dump(self, drive_id: str, generation: int, image_name: str, output_root: str) -> dict:
        result = self.service.start_dump(str(drive_id), int(generation), str(image_name), str(output_root))
        job_id = result.get("result", {}).get("job_id") if isinstance(result.get("result"), dict) else None
        await decky.emit("discdeck:changed", {"epoch": self.service.epoch, "revision": self.service.revision, "domain": "dumps", "id": job_id})
        return result

    async def cancel_dump(self, job_id: str) -> dict:
        result = self.service.cancel_dump(str(job_id))
        await decky.emit("discdeck:changed", {"epoch": self.service.epoch, "revision": self.service.revision, "domain": "dumps", "id": job_id})
        return result

    async def force_stop_dump(self, job_id: str, confirmed: bool = False) -> dict:
        result = self.service.force_stop_dump(str(job_id), bool(confirmed))
        await decky.emit("discdeck:changed", {"epoch": self.service.epoch, "revision": self.service.revision, "domain": "dumps", "id": job_id})
        return result

    async def acknowledge_dump(self, job_id: str) -> dict:
        result = self.service.acknowledge_dump(str(job_id))
        await decky.emit("discdeck:changed", {"epoch": self.service.epoch, "revision": self.service.revision, "domain": "dumps", "id": job_id})
        return result

    async def load_virtual(self, path: str) -> dict:
        result = self.service.load_virtual(str(path))
        slot_id = result.get("result", {}).get("slot_id") if isinstance(result.get("result"), dict) else None
        await decky.emit("discdeck:changed", {"epoch": self.service.epoch, "revision": self.service.revision, "domain": "virtual", "id": slot_id})
        return result

    async def unload_virtual(self, slot_id: str) -> dict:
        result = self.service.unload_virtual(str(slot_id))
        await decky.emit("discdeck:changed", {"epoch": self.service.epoch, "revision": self.service.revision, "domain": "virtual", "id": slot_id})
        return result
