import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from discdeck.commands import CommandResult, ScriptedRunner
from discdeck.diagnostics import DiagnosticService
from discdeck.physical import GenerationTracker, eject_argv, mount_argv, session_argv, unmount_argv
from discdeck.security import assert_physical_udisks_argv
from tests.support.fixtures import scripted_bus_responses, write_host_sysfs

BLOCK = "/org/freedesktop/UDisks2/block_devices/sr1"
DRIVE = "/org/freedesktop/UDisks2/drives/bridge_lun0"


def _payload(media: bool) -> str:
    device = [ord(char) for char in "/dev/sr1"] + [0]
    return json.dumps(
        {
            "type": "(a{oa{sa{sv}}})",
            "data": [
                {
                    BLOCK: {
                        "org.freedesktop.UDisks2.Block": {
                            "Device": {"type": "ay", "data": device},
                            "Drive": {"type": "o", "data": DRIVE},
                        },
                        "org.freedesktop.UDisks2.Filesystem": {"MountPoints": {"type": "aay", "data": []}},
                    },
                    DRIVE: {
                        "org.freedesktop.UDisks2.Drive": {
                            "Optical": {"type": "b", "data": False},
                            "MediaAvailable": {"type": "b", "data": media},
                        }
                    },
                }
            ],
        }
    )


class FakeOs:
    def geteuid(self) -> int:
        return 1000

    def getegid(self) -> int:
        return 1000


class FakePwd:
    def getpwuid(self, uid: int) -> SimpleNamespace:
        return SimpleNamespace(pw_name="hostuser", pw_uid=uid, pw_gid=1000)

    def getpwnam(self, name: str) -> SimpleNamespace:
        return SimpleNamespace(pw_name=name, pw_uid=1000, pw_gid=1000)


class PhysicalOperationTests(unittest.TestCase):
    def _service(self, root: Path, media: bool, mutation: ScriptedRunner) -> DiagnosticService:
        sysfs = write_host_sysfs(root)
        return DiagnosticService(
            environ={"PATH": "/usr/bin", "HOME": str(root / "home")},
            os_module=FakeOs(),
            pwd_module=FakePwd(),
            runner=ScriptedRunner(scripted_bus_responses(_payload(media))),
            mutation_runner=mutation,
            sysfs_root=sysfs,
            root=root,
            dev_root=root / "dev",
            home=root / "home",
            epoch="epoch-physical",
            getfacl=lambda node: None,
            access=lambda node, mode: False,
            stat_fn=lambda node: (_ for _ in ()).throw(FileNotFoundError(node)),
        )

    def test_mount_is_read_only_and_stale_generation_calls_nothing(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            mutation = ScriptedRunner(
                {tuple(mount_argv(BLOCK)): CommandResult(mount_argv(BLOCK), 0, '{"type":"s","data":"/run/media/hostuser/DISC"}', "")},
                policy=assert_physical_udisks_argv,
            )
            service = self._service(root, True, mutation)
            drive = next(item for item in service.snapshot()["drives"] if item["block_node"] == "/dev/sr1")
            stale = service.mount_drive(drive["drive_id"], drive["generation"] + 1, drive["media_generation"])
            self.assertFalse(stale["ok"])
            self.assertEqual(stale["code"], "STALE_DEVICE")
            self.assertEqual(mutation.calls, [])
            mounted = service.mount_drive(drive["drive_id"], drive["generation"], drive["media_generation"])
            self.assertTrue(mounted["ok"])
            self.assertEqual(mounted["result"]["mount_path"], "/run/media/hostuser/DISC")
            self.assertFalse(mounted["result"]["hardware_validated"])
            self.assertEqual(mutation.calls, [mount_argv(BLOCK)])
            self.assertNotIn("rw", mutation.calls[0])

    def test_empty_media_and_unconfirmed_eject_do_not_call_udisks(self) -> None:
        with TemporaryDirectory() as temporary:
            mutation = ScriptedRunner(policy=assert_physical_udisks_argv)
            service = self._service(Path(temporary), False, mutation)
            drive = next(item for item in service.snapshot()["drives"] if item["block_node"] == "/dev/sr1")
            empty = service.mount_drive(drive["drive_id"], drive["generation"], drive["media_generation"])
            self.assertEqual(empty["code"], "NOT_READY")
            eject = service.eject_drive(drive["drive_id"], drive["generation"], False)
            self.assertEqual(eject["code"], "CONSENT_REQUIRED")
            closed = service.close_tray(drive["drive_id"])
            self.assertIn("TRAY_CLOSE_UNSUPPORTED", closed["message"])
            self.assertEqual(mutation.calls, [])

    def test_confirmed_eject_unmounts_owned_mount_before_eject_and_stops_when_busy(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            mutation = ScriptedRunner(
                {
                    tuple(mount_argv(BLOCK)): CommandResult(mount_argv(BLOCK), 0, '{"type":"s","data":"/mnt/disc"}', ""),
                    tuple(unmount_argv(BLOCK)): CommandResult(unmount_argv(BLOCK), 1, "", "org.freedesktop.UDisks2.Error.DeviceBusy"),
                    tuple(eject_argv(DRIVE)): CommandResult(eject_argv(DRIVE), 0, "", ""),
                },
                policy=assert_physical_udisks_argv,
            )
            service = self._service(root, True, mutation)
            drive = next(item for item in service.snapshot()["drives"] if item["block_node"] == "/dev/sr1")
            self.assertTrue(service.mount_drive(drive["drive_id"], drive["generation"], drive["media_generation"])["ok"])
            denied = service.eject_drive(drive["drive_id"], drive["generation"], True)
            self.assertEqual(denied["code"], "DRIVE_BUSY")
            self.assertEqual(mutation.calls, [mount_argv(BLOCK), unmount_argv(BLOCK)])

    def test_authorization_failure_has_no_ioctl_fallback(self) -> None:
        with TemporaryDirectory() as temporary:
            mutation = ScriptedRunner(
                {tuple(mount_argv(BLOCK)): CommandResult(mount_argv(BLOCK), 1, "", "org.freedesktop.UDisks2.Error.NotAuthorized")},
                policy=assert_physical_udisks_argv,
            )
            service = self._service(Path(temporary), True, mutation)
            drive = next(item for item in service.snapshot()["drives"] if item["block_node"] == "/dev/sr1")
            refused = service.mount_drive(drive["drive_id"], drive["generation"], drive["media_generation"])
            self.assertEqual(refused["code"], "PERMISSION_DENIED")
            self.assertIn("NotAuthorized", refused["message"])
            self.assertIn("did not start", refused["message"])
            self.assertEqual(mutation.calls, [mount_argv(BLOCK), session_argv(mount_argv(BLOCK))])

    def test_user_session_retry_can_eject_after_a_direct_denial(self) -> None:
        with TemporaryDirectory() as temporary:
            direct = eject_argv(DRIVE)
            session = session_argv(direct)
            mutation = ScriptedRunner(
                {
                    tuple(direct): CommandResult(direct, 1, "", "org.freedesktop.UDisks2.Error.NotAuthorized"),
                    tuple(session): CommandResult(session, 0, "", ""),
                },
                policy=assert_physical_udisks_argv,
            )
            service = self._service(Path(temporary), True, mutation)
            drive = next(item for item in service.snapshot()["drives"] if item["block_node"] == "/dev/sr1")
            ejected = service.eject_drive(drive["drive_id"], drive["generation"], True)
            self.assertTrue(ejected["ok"])
            self.assertEqual(ejected["result"]["via"], "user-session")
            self.assertEqual(mutation.calls, [direct, session])

    def test_denied_eject_uses_the_writable_sr_node_without_root(self) -> None:
        with TemporaryDirectory() as temporary:
            direct = eject_argv(DRIVE)
            session = session_argv(direct)
            mutation = ScriptedRunner(
                {
                    tuple(direct): CommandResult(direct, 1, "", "org.freedesktop.UDisks2.Error.NotAuthorized"),
                    tuple(session): CommandResult(session, 1, "", "org.freedesktop.UDisks2.Error.NotAuthorized"),
                    ("eject", "/dev/sr1"): CommandResult(["eject", "/dev/sr1"], 0, "", ""),
                },
                policy=assert_physical_udisks_argv,
            )
            service = self._service(Path(temporary), True, mutation)
            service.access = lambda node, mode: node == "/dev/sr1"
            drive = next(item for item in service.snapshot()["drives"] if item["block_node"] == "/dev/sr1")
            ejected = service.eject_drive(drive["drive_id"], drive["generation"], True)
            self.assertTrue(ejected["ok"], ejected)
            self.assertEqual(ejected["result"]["via"], "user-eject")
            self.assertFalse(ejected["result"]["hardware_validated"])
            self.assertEqual(mutation.calls[-1], ["eject", "/dev/sr1"])

    def test_generation_follows_the_device_not_the_old_node_name(self) -> None:
        tracker = GenerationTracker()
        first = {"drive_id": "drv_a", "block_node": "/dev/sr1", "sysfs_device": "/sys/a", "media_present": False}
        tracker.observe([first])
        renamed = {"drive_id": "drv_a", "block_node": "/dev/sr9", "sysfs_device": "/sys/a", "media_present": False}
        tracker.observe([renamed])
        self.assertEqual(renamed["generation"], 2)
        self.assertEqual(renamed["media_generation"], 1)
        tracker.observe([])
        returned = {"drive_id": "drv_a", "block_node": "/dev/sr2", "sysfs_device": "/sys/a", "media_present": True}
        tracker.observe([returned])
        self.assertEqual(returned["generation"], 3)
        self.assertEqual(returned["media_generation"], 2)


if __name__ == "__main__":
    unittest.main()
