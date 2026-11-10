"""Plugin lifecycle flags.

Unload and uninstall do not eject media, cancel unrelated processes, or delete
user files. Phase 0 has no dump worker to reconcile.
"""

from __future__ import annotations

from typing import Any


class Lifecycle:
    def __init__(self) -> None:
        self.phase = "created"
        self.tasks: list[Any] = []
        self.eject_called = False
        self.user_data_deleted = False

    async def main(self) -> None:
        self.phase = "main"

    async def unload(self) -> None:
        self.tasks.clear()
        self.phase = "unloaded"

    async def uninstall(self) -> None:
        self.phase = "uninstalled"
