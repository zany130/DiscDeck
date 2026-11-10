import stat
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from discdeck.commands import ScriptedRunner
from discdeck.diagnostics import DiagnosticService
from tests.support.assertions import assert_phase0_unproven
from tests.support.fixtures import (
    named_acl,
    scripted_bus_responses,
    udisks_busctl_payload,
    write_cdemu_installation,
    write_host_sysfs,
    write_redumper_wrapper,
    write_steam_home,
)


class FakeOs:
    def geteuid(self) -> int:
        return 1000

    def getegid(self) -> int:
        return 1000


class FakePwd:
    def getpwnam(self, name: str) -> SimpleNamespace:
        if name != "hostuser":
            raise KeyError(name)
        return SimpleNamespace(pw_name="hostuser", pw_uid=1000, pw_gid=1000)

    def getpwuid(self, uid: int) -> SimpleNamespace:
        return SimpleNamespace(pw_name="hostuser", pw_uid=1000, pw_gid=1000)


class DiagnosticSnapshotTests(unittest.TestCase):
    def test_host_shaped_fixture_never_reports_proven_hardware(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            sysfs = write_host_sysfs(root)
            dev = root / "dev"
            write_cdemu_installation(root, sysfs, dev)
            tools = root / "bin"
            write_redumper_wrapper(tools)
            home = root / "home" / "hostuser"
            write_steam_home(home)
            plugin = root / "plugin"
            plugin.mkdir()
            (plugin / "plugin.json").write_text('{"name":"DiscDeck","flags":["debug"]}\n', encoding="utf-8")
            settings = root / "settings"
            settings.mkdir()
            runner = ScriptedRunner(scripted_bus_responses(udisks_busctl_payload()))
            service = DiagnosticService(
                environ={
                    "PATH": str(tools),
                    "DECKY_USER": "hostuser",
                    "DECKY_USER_HOME": str(home),
                    "HOME": str(home),
                    "USER": "hostuser",
                    "DECKY_HOME": str(root / "homebrew"),
                    "DECKY_PLUGIN_DIR": str(plugin),
                    "DECKY_PLUGIN_SETTINGS_DIR": str(settings),
                    "DECKY_PLUGIN_RUNTIME_DIR": str(root / "runtime"),
                    "DECKY_PLUGIN_LOG_DIR": str(root / "logs"),
                    "DECKY_PLUGIN_NAME": "DiscDeck",
                    "DECKY_PLUGIN_VERSION": "0.0.1",
                    "DECKY_VERSION": "v3.3.1",
                    "DECKY_PLUGIN_LOG": str(root / "logs" / "plugin.log"),
                    "DECKY_PLUGIN_AUTHOR": "hostuser",
                },
                os_module=FakeOs(),
                pwd_module=FakePwd(),
                runner=runner,
                sysfs_root=sysfs,
                root=root,
                dev_root=dev,
                home=home,
                epoch="epoch-test",
                access=lambda node, mode: not node.endswith("sg0"),
                getfacl=named_acl,
                stat_fn=lambda node: SimpleNamespace(st_mode=stat.S_IFCHR | 0o660, st_uid=0, st_gid=0),
            )
            snapshot = service.snapshot()
            assert_phase0_unproven(snapshot)
            modules = {item["id"]: item for item in snapshot["modules"]}
            self.assertEqual(modules["physical"]["capability"], "ready")
            self.assertEqual(modules["physical"]["reason_code"], "INVENTORY_OBSERVED")
            self.assertEqual(modules["physical"]["effective"], "active")
            self.assertFalse(modules["physical"]["hardware_validated"])
            self.assertEqual(modules["images.iso"]["reason_code"], "LOOPSETUP_NOT_RUN")
            self.assertEqual(modules["dump.redumper"]["capability"], "untested")
            self.assertEqual(modules["virtual.cdemu"]["capability"], "untested")
            self.assertEqual(modules["virtual.cdemu"]["reason_code"], "DAEMON_INACTIVE")
            self.assertEqual(modules["launch.experimental"]["effective"], "disabled")
            self.assertEqual(modules["launch.autoplay"]["effective"], "disabled")
            self.assertFalse(snapshot["identity"]["root_requested"])
            self.assertEqual(snapshot["identity"]["effective_uid"], 1000)
            self.assertEqual(snapshot["identity"]["directories"]["runtime"]["durability"], "untested")
            bridge = [drive for drive in snapshot["drives"] if drive["shared_bridge"]]
            self.assertEqual(sorted(drive["lun"] for drive in bridge), [0, 1])
            self.assertEqual(snapshot["probes"]["redumper"]["version_status"], "not_executed")
            self.assertFalse(snapshot["probes"]["redumper"]["executed"])
            self.assertFalse(snapshot["probes"]["steam"]["shortcuts_read"])
            self.assertFalse(any(Path(call[0]).name in {"redumper", "cdemu", "mount", "eject", "steam"} for call in runner.calls))
            sr1 = next(drive for drive in snapshot["drives"] if drive["block_node"] == "/dev/sr1")
            self.assertTrue(sr1["optical"])
            self.assertFalse(sr1["media_present"])
            self.assertIn("udisks_optical_false_not_authoritative", sr1["optical_evidence"])

    def test_permission_denial_blocks_only_the_dump_capability(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            sysfs = write_host_sysfs(root)
            service = DiagnosticService(
                environ={"PATH": ""},
                os_module=FakeOs(),
                pwd_module=FakePwd(),
                runner=ScriptedRunner(),
                sysfs_root=sysfs,
                root=root,
                dev_root=root / "dev",
                home=root / "home",
                epoch="epoch-test",
                access=lambda node, mode: False,
                getfacl=lambda node: None,
                stat_fn=lambda node: SimpleNamespace(st_mode=stat.S_IFCHR | 0o660, st_uid=0, st_gid=0),
            )
            snapshot = service.snapshot()
            assert_phase0_unproven(snapshot)
            modules = {item["id"]: item for item in snapshot["modules"]}
            self.assertEqual(modules["dump.redumper"]["capability"], "missing")
            self.assertEqual(modules["dump.redumper"]["reason_code"], "REDUMPER_MISSING")

    def test_sg_denial_is_reported_when_redumper_exists(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            sysfs = write_host_sysfs(root)
            tools = root / "bin"
            write_redumper_wrapper(tools)
            service = DiagnosticService(
                environ={"PATH": str(tools)},
                os_module=FakeOs(),
                pwd_module=FakePwd(),
                runner=ScriptedRunner(),
                sysfs_root=sysfs,
                root=root,
                dev_root=root / "dev",
                home=root / "home",
                epoch="epoch-test",
                access=lambda node, mode: not node.startswith("/dev/sg"),
                getfacl=lambda node: None,
                stat_fn=lambda node: SimpleNamespace(st_mode=stat.S_IFCHR | 0o660, st_uid=0, st_gid=0),
            )
            snapshot = service.snapshot()
            assert_phase0_unproven(snapshot)
            dump = next(item for item in snapshot["modules"] if item["id"] == "dump.redumper")
            self.assertEqual(dump["capability"], "denied")
            self.assertEqual(dump["reason_code"], "SG_ACCESS_DENIED")
            self.assertNotEqual(dump["effective"], "active")

    def test_unavailable_dependencies_are_not_ready(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = DiagnosticService(
                environ={},
                os_module=FakeOs(),
                pwd_module=FakePwd(),
                runner=ScriptedRunner(),
                sysfs_root=root / "sys",
                root=root,
                dev_root=root / "dev",
                home=None,
                epoch="epoch-test",
            )
            snapshot = service.snapshot()
            assert_phase0_unproven(snapshot)
            modules = {item["id"]: item for item in snapshot["modules"]}
            self.assertEqual(modules["physical"]["capability"], "missing")
            self.assertEqual(modules["virtual.cdemu"]["capability"], "missing")
            self.assertEqual(modules["dump.redumper"]["capability"], "missing")
            self.assertEqual(snapshot["identity"]["reason_code"], "DECKY_ENV_ABSENT")


if __name__ == "__main__":
    unittest.main()
