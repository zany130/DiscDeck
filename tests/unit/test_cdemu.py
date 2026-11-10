import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from discdeck.adapters.cdemu import probe_cdemu
from discdeck.commands import ScriptedRunner
from tests.support.fixtures import scripted_bus_responses, write_cdemu_installation


class CdemuTests(unittest.TestCase):
    def test_installed_inactive_service_is_not_missing_or_ready(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            sysfs = root / "sys"
            dev = root / "dev"
            write_cdemu_installation(root, sysfs, dev)
            runner = ScriptedRunner(scripted_bus_responses("{}", cdemu_active=False))
            found = probe_cdemu(runner, root=root, sysfs_root=sysfs, dev_root=dev)
            self.assertEqual(found["status"], "untested")
            self.assertEqual(found["reason_code"], "DAEMON_INACTIVE")
            self.assertTrue(found["vhba_loaded"])
            self.assertTrue(found["vhba_ctl_present"])
            self.assertFalse(found["active"])
            self.assertFalse(found["interface_queried"])
            self.assertEqual(found["image_load"], "not_run")
            self.assertFalse(any(Path(call[0]).name in {"cdemu", "cdemu-daemon", "modprobe"} for call in runner.calls))

    def test_absent_installation_is_missing(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            found = probe_cdemu(ScriptedRunner(), root=root, sysfs_root=root / "sys", dev_root=root / "dev")
            self.assertEqual(found["status"], "missing")
            self.assertEqual(found["reason_code"], "CDEMU_MISSING")

    def test_active_daemon_still_does_not_load_images(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            sysfs = root / "sys"
            dev = root / "dev"
            write_cdemu_installation(root, sysfs, dev)
            runner = ScriptedRunner(scripted_bus_responses("{}", cdemu_active=True))
            found = probe_cdemu(runner, root=root, sysfs_root=sysfs, dev_root=dev)
            self.assertEqual(found["status"], "untested")
            self.assertEqual(found["reason_code"], "DAEMON_INTERFACE_NOT_VALIDATED")
            self.assertTrue(found["active"])
            self.assertEqual(found["image_load"], "not_run")


if __name__ == "__main__":
    unittest.main()
