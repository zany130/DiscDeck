import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from discdeck.commands import CommandResult, ScriptedRunner
from discdeck.diagnostics import DiagnosticService
from discdeck.images import backing_argv, loop_delete_argv, loop_setup_argv, parse_backing, parse_loop_object, udisksctl_delete_argv, udisksctl_setup_argv
from discdeck.physical import mount_argv, session_argv, unmount_argv
from discdeck.security import assert_physical_udisks_argv
from tests.support.fixtures import scripted_bus_responses
from tests.unit.test_physical import _payload


LOOP = "/org/freedesktop/UDisks2/block_devices/loop3"
FD = 17


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


class FixedOpener:
    def __init__(self) -> None:
        self.opened: list[Path] = []
        self.closed: list[int] = []

    def open(self, path: Path) -> int:
        self.opened.append(path)
        return FD

    def close(self, fd: int) -> None:
        self.closed.append(fd)


def _ok(argv: list[str], stdout: str) -> CommandResult:
    return CommandResult(argv, 0, stdout, "")


def _fail(argv: list[str], stderr: str) -> CommandResult:
    return CommandResult(argv, 1, "", stderr)


class ImageLibraryTests(unittest.TestCase):
    def _iso(self, root: Path, name: str = "demo.iso") -> Path:
        path = root / "games" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"ISO")
        return path

    def _service(self, root: Path, mutation: ScriptedRunner, opener: FixedOpener | None = None, *, udisks: bool = True) -> DiagnosticService:
        settings = root / "settings"
        settings.mkdir(exist_ok=True)
        service = DiagnosticService(
            environ={
                "PATH": "/usr/bin",
                "HOME": str(root / "home"),
                "DECKY_PLUGIN_SETTINGS_DIR": str(settings),
                "DECKY_USER": "hostuser",
            },
            os_module=FakeOs(),
            pwd_module=FakePwd(),
            runner=ScriptedRunner(scripted_bus_responses(_payload(False))) if udisks else ScriptedRunner(),
            mutation_runner=mutation,
            sysfs_root=root / "sys",
            root=root,
            dev_root=root / "dev",
            home=root / "home",
            epoch="epoch-iso",
        )
        service.images.opener = opener or FixedOpener()
        return service

    def _mount_responses(self, iso: Path, *, mount_code: int = 0, delete_code: int = 0) -> dict[tuple[str, ...], CommandResult]:
        setup = loop_setup_argv(FD)
        mounted = mount_argv(LOOP)
        deleted = loop_delete_argv(LOOP)
        responses = {
            tuple(setup): _ok(setup, json.dumps({"type": "o", "data": LOOP})),
            tuple(mounted): CommandResult(mounted, mount_code, json.dumps({"type": "s", "data": "/run/media/hostuser/DEMO"}), "No medium found" if mount_code else ""),
            tuple(deleted): CommandResult(deleted, delete_code, "", "" if delete_code == 0 else "delete failed"),
            tuple(udisksctl_delete_argv("/dev/loop3")): CommandResult(udisksctl_delete_argv("/dev/loop3"), delete_code, "", "delete failed"),
        }
        return responses

    def test_parsers_read_loop_names_and_backing_bytes(self) -> None:
        self.assertEqual(parse_loop_object("Mapped file /games/demo.iso as /dev/loop3."), LOOP)
        numbers = list(b"/games/demo.iso\0")
        self.assertEqual(parse_backing("ay " + " ".join(str(number) for number in numbers)), "/games/demo.iso")

    def test_symlink_and_non_iso_are_rejected_without_a_call(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            iso = self._iso(root)
            cue = iso.with_suffix(".cue")
            cue.write_bytes(b"FILE")
            alias = iso.parent / "alias.iso"
            alias.symlink_to(iso)
            jump = root / "jump"
            jump.symlink_to(iso.parent)
            opener = FixedOpener()
            mutation = ScriptedRunner(policy=assert_physical_udisks_argv)
            service = self._service(root, mutation, opener)
            for raw in (str(alias), str(jump / "demo.iso"), str(cue), "demo.iso"):
                result = service.mount_iso(raw)
                self.assertFalse(result["ok"])
                self.assertEqual(result["code"], "UNSUPPORTED")
            self.assertEqual(opener.opened, [])
            self.assertEqual(mutation.calls, [])

    def test_successful_mount_records_only_that_loop_and_unmount_removes_it(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            iso = self._iso(root)
            setup = loop_setup_argv(FD)
            mounted = mount_argv(LOOP)
            backing = backing_argv(LOOP)
            unmounted = unmount_argv(LOOP)
            deleted = loop_delete_argv(LOOP)
            responses = self._mount_responses(iso)
            responses[tuple(backing)] = _ok(backing, f"{iso}\n")
            responses[tuple(unmounted)] = _ok(unmounted, "")
            responses[tuple(deleted)] = _ok(deleted, "")
            opener = FixedOpener()
            mutation = ScriptedRunner(responses, policy=assert_physical_udisks_argv)
            service = self._service(root, mutation, opener)
            mounted_result = service.mount_iso(str(iso))
            self.assertTrue(mounted_result["ok"])
            self.assertEqual(mounted_result["result"]["mount_path"], "/run/media/hostuser/DEMO")
            self.assertFalse(mounted_result["result"]["hardware_validated"])
            self.assertTrue(mounted_result["result"]["read_only"])
            self.assertEqual(mutation.passed_fds[0], (FD,))
            self.assertFalse(any("LoopSetup" in call for call in service.runner.calls))
            self.assertFalse(any(Path(call[0]).name in {"cdemu", "redumper", "mount", "eject"} for call in mutation.calls))
            journal = json.loads((root / "settings" / "state" / "iso-ownership.json").read_text(encoding="utf-8"))
            self.assertEqual(journal["records"][0]["backing_path"], str(iso))
            self.assertTrue(journal["records"][0]["read_only"])
            foreign = service.unmount_iso("not-owned")
            self.assertFalse(foreign["ok"])
            self.assertNotIn(tuple(deleted), {tuple(call) for call in mutation.calls})
            removed = service.unmount_iso(mounted_result["result"]["image_id"])
            self.assertTrue(removed["ok"])
            self.assertFalse(removed["result"]["hardware_validated"])
            self.assertEqual(json.loads((root / "settings" / "state" / "iso-ownership.json").read_text(encoding="utf-8"))["records"], [])

    def test_mount_failure_deletes_the_loop_and_a_mismatch_does_not(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            iso = self._iso(root)
            deleted = loop_delete_argv(LOOP)
            mutation = ScriptedRunner(self._mount_responses(iso, mount_code=1), policy=assert_physical_udisks_argv)
            service = self._service(root, mutation)
            failed = service.mount_iso(str(iso))
            self.assertFalse(failed["ok"])
            self.assertIn(deleted, mutation.calls)
            self.assertFalse((root / "settings" / "state" / "iso-ownership.json").exists())

            backing = backing_argv(LOOP)
            responses = self._mount_responses(iso)
            responses[tuple(backing)] = _ok(backing, "/other/foreign.iso\n")
            mutation = ScriptedRunner(responses, policy=assert_physical_udisks_argv)
            service = self._service(root, mutation)
            mounted_result = service.mount_iso(str(iso))
            self.assertTrue(mounted_result["ok"])
            calls_before = len(mutation.calls)
            mismatched = service.unmount_iso(mounted_result["result"]["image_id"])
            self.assertFalse(mismatched["ok"])
            self.assertNotIn("Delete", {part for call in mutation.calls[calls_before:] for part in call})
            self.assertEqual(len(json.loads((root / "settings" / "state" / "iso-ownership.json").read_text(encoding="utf-8"))["records"]), 1)

    def test_changed_file_and_failed_cleanup_do_not_guess(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            iso = self._iso(root)
            backing = backing_argv(LOOP)
            responses = self._mount_responses(iso)
            responses[tuple(backing)] = _ok(backing, f"{iso}\n")
            mutation = ScriptedRunner(responses, policy=assert_physical_udisks_argv)
            service = self._service(root, mutation)
            mounted_result = service.mount_iso(str(iso))
            iso.write_bytes(b"CHANGED")
            calls_before = len(mutation.calls)
            changed = service.unmount_iso(mounted_result["result"]["image_id"])
            self.assertFalse(changed["ok"])
            self.assertIn("changed", changed["message"])
            self.assertNotIn("Delete", {part for call in mutation.calls[calls_before:] for part in call})

        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            iso = self._iso(root)
            mutation = ScriptedRunner(self._mount_responses(iso, mount_code=1, delete_code=1), policy=assert_physical_udisks_argv)
            service = self._service(root, mutation)
            failed = service.mount_iso(str(iso))
            self.assertFalse(failed["ok"])
            self.assertIn(LOOP, failed["message"])
            saved = json.loads((root / "settings" / "state" / "iso-ownership.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["records"][0]["loop_object_path"], LOOP)

    def test_permission_denial_uses_read_only_udisksctl_and_a_second_image_is_refused(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            iso = self._iso(root)
            setup = loop_setup_argv(FD)
            ctl = session_argv(udisksctl_setup_argv(str(iso)))
            mounted = mount_argv(LOOP)
            responses = {
                tuple(setup): _fail(setup, "NotAuthorized"),
                tuple(ctl): _ok(ctl, f"Mapped file {iso} as /dev/loop3.\n"),
                tuple(mounted): _ok(mounted, json.dumps({"type": "s", "data": "/run/media/hostuser/DEMO"})),
            }
            opener = FixedOpener()
            mutation = ScriptedRunner(responses, policy=assert_physical_udisks_argv)
            service = self._service(root, mutation, opener)
            result = service.mount_iso(str(iso))
            self.assertTrue(result["ok"])
            self.assertEqual(result["result"]["via"], "udisksctl")
            self.assertIn(ctl, mutation.calls)
            again = service.mount_iso(str(iso))
            self.assertFalse(again["ok"])
            self.assertEqual(again["code"], "DRIVE_BUSY")
            self.assertEqual(len(opener.opened), 1)

    def test_missing_udisks_and_a_bad_journal_do_not_create_a_loop(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            iso = self._iso(root)
            opener = FixedOpener()
            mutation = ScriptedRunner(policy=assert_physical_udisks_argv)
            service = self._service(root, mutation, opener, udisks=False)
            missing = service.mount_iso(str(iso))
            self.assertFalse(missing["ok"])
            self.assertEqual(missing["code"], "DEPENDENCY_MISSING")
            self.assertEqual(opener.opened, [])
            journal = root / "settings" / "state" / "iso-ownership.json"
            journal.parent.mkdir(parents=True)
            journal.write_text('{"schema_version": 9, "records": []}\n', encoding="utf-8")
            service = self._service(root, mutation, opener)
            refused = service.mount_iso(str(iso))
            self.assertFalse(refused["ok"])
            self.assertTrue(journal.read_text(encoding="utf-8").startswith('{"schema_version": 9'))
            self.assertEqual(mutation.calls, [])


if __name__ == "__main__":
    unittest.main()
