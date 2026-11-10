import asyncio
import importlib
import logging
import sys
import types
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from discdeck.commands import ScriptedRunner
from discdeck.diagnostics import DiagnosticService


class FakeOs:
    def geteuid(self) -> int:
        return 1000

    def getegid(self) -> int:
        return 1000


class FakePwd:
    def getpwnam(self, name: str):
        raise KeyError(name)

    def getpwuid(self, uid: int):
        raise KeyError(uid)


class PluginRpcTests(unittest.TestCase):
    def test_endpoints_emit_events_and_clean_up(self) -> None:
        events: list[tuple[str, tuple[object, ...]]] = []
        decky = types.ModuleType("decky")
        decky.logger = logging.getLogger("discdeck-test")

        async def emit(name: str, *args: object) -> None:
            events.append((name, args))

        decky.emit = emit
        sys.modules["decky"] = decky
        sys.modules.pop("main", None)
        main = importlib.import_module("main")
        plugin = main.Plugin()
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            plugin.service = DiagnosticService(
                environ={},
                os_module=FakeOs(),
                pwd_module=FakePwd(),
                runner=ScriptedRunner(),
                sysfs_root=root / "sys",
                root=root,
                dev_root=root / "dev",
                home=None,
                epoch="epoch-rpc",
            )
            ping = asyncio.run(plugin.ping())
            self.assertTrue(ping["ok"])
            self.assertTrue(ping["result"]["pong"])
            self.assertFalse(ping["result"]["hardware_validated"])
            emitted = asyncio.run(plugin.emit_probe_event())
            self.assertTrue(emitted["ok"])
            self.assertEqual(events[0][0], "discdeck:changed")
            self.assertEqual(events[0][1][0]["domain"], "diagnostics")
            snapshot = asyncio.run(plugin.get_snapshot())
            self.assertTrue(snapshot["ok"])
            self.assertTrue(all(module["capability"] != "ready" for module in snapshot["result"]["modules"]))
            unknown = asyncio.run(plugin.probe_module("not-a-module"))
            self.assertFalse(unknown["ok"])
            self.assertEqual(unknown["code"], "UNSUPPORTED")
            asyncio.run(plugin._unload())
            asyncio.run(plugin._uninstall())
            self.assertEqual(plugin.lifecycle.phase, "uninstalled")
            self.assertFalse(plugin.lifecycle.eject_called)
            self.assertFalse(plugin.lifecycle.user_data_deleted)


if __name__ == "__main__":
    unittest.main()
