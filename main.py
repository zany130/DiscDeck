import os
import pwd

import decky

from discdeck.diagnostics import DiagnosticService
from discdeck.lifecycle import Lifecycle
from discdeck.models import envelope_error, envelope_ok


class Plugin:
    """Decky lifecycle and read-only diagnostic endpoints.

    Production optical actions are intentionally absent.
    """

    def __init__(self) -> None:
        self.lifecycle = Lifecycle()
        self.service = DiagnosticService(environ=dict(os.environ), os_module=os, pwd_module=pwd)

    async def _main(self) -> None:
        await self.lifecycle.main()
        self.service.lifecycle_phase = self.lifecycle.phase
        decky.logger.info(
            "DiscDeck phase 0 diagnostics loaded (effective uid %s). No disc operation was started.",
            os.geteuid(),
        )

    async def _unload(self) -> None:
        await self.lifecycle.unload()
        self.service.lifecycle_phase = self.lifecycle.phase
        decky.logger.info("DiscDeck unloaded without ejecting media or stopping foreign processes.")

    async def _uninstall(self) -> None:
        await self.lifecycle.uninstall()
        self.service.lifecycle_phase = self.lifecycle.phase
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
            {"pong": True, "phase": "0", "hardware_validated": False},
            self.service.revision,
            self.service.epoch,
        )

    async def emit_probe_event(self) -> dict:
        payload = self.service.probe_event()
        await decky.emit("discdeck:changed", payload)
        return envelope_ok(payload, payload["revision"], payload["epoch"])

    async def read_redumper_version(self, allow_untested_wrapper: bool = False) -> dict:
        return self.service.redumper_version_envelope(bool(allow_untested_wrapper))
