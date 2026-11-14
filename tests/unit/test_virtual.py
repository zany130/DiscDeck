import json
import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from discdeck.commands import CommandResult, ScriptedRunner
from discdeck.diagnostics import DiagnosticService
from discdeck.errors import UnsafeCommand
from discdeck.security import assert_readonly_argv, assert_virtual_argv
from discdeck.virtual import _mapping_parts, _number, _session_wrap, _status_parts, load_argv, mapping_argv, number_argv, start_daemon_argv, status_argv, unload_argv, validate_disc_image
from tests.support.fixtures import scripted_bus_responses, write_cdemu_installation


class FakeOs:
    def geteuid(self) -> int:
        return 1000

    def getegid(self) -> int:
        return 1000


class FakePwd:
    def getpwuid(self, uid: int) -> SimpleNamespace:
        return SimpleNamespace(pw_name="hostuser", pw_uid=uid, pw_gid=1000)


class SwitchingRunner:
    def __init__(self, before: dict[tuple[str, ...], CommandResult], after: dict[tuple[str, ...], CommandResult]) -> None:
        self.before = before
        self.after = after
        self.calls: list[list[str]] = []
        self.loaded = False
        self.policy = assert_virtual_argv

    def __call__(self, argv: list[str], timeout: float = 5, env: dict[str, str] | None = None, cwd: str | None = None, pass_fds: tuple[int, ...] = (), pty: bool = False) -> CommandResult:
        del timeout, env, cwd, pass_fds, pty
        self.policy(argv)
        self.calls.append(list(argv))
        key = tuple(argv)
        table = self.after if self.loaded else self.before
        if "DeviceLoad" in argv:
            self.loaded = True
        match = table.get(key) or self.before.get(key) or self.after.get(key)
        if match is None:
            return CommandResult(list(argv), 127, "", "not found")
        return match


def _result(argv: list[str], stdout: str, code: int = 0) -> CommandResult:
    return CommandResult(list(argv), code, stdout, "")


def _status_json(loaded: bool, files: list[str]) -> str:
    return json.dumps({"type": "bas", "data": [loaded, files]}) + "\n"


class VirtualDiscTests(unittest.TestCase):
    def test_inactive_daemon_starts_then_moves_the_iso_onto_an_empty_device(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = root / "game.iso"
            image.write_bytes(b"iso")
            service, virtual = self._service(root, active=False, image=image)
            result = service.load_virtual(str(image))
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["result"]["device_number"], 0)
            self.assertEqual(result["result"]["sr_device"], "/dev/sr4")
            self.assertEqual(result["result"]["via"], "started")
            self.assertFalse(result["result"]["hardware_validated"])
            self.assertIn(start_daemon_argv(), virtual.calls)
            self.assertIn(load_argv(0, str(image)), virtual.calls)
            self.assertFalse(any(call[0] == "systemd-run" for call in virtual.calls))
            self.assertFalse(any(Path(call[0]).name in {"cdemu", "cdemu-daemon", "modprobe"} for call in virtual.calls))
            slots = service.snapshot()["virtual_slots"]
            self.assertEqual(slots[0]["image_path"], str(image))
            self.assertEqual(slots[0]["state"], "loaded")
            self.assertFalse(slots[0]["hardware_validated"])

    def test_running_daemon_is_not_started_again(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = root / "game.iso"
            image.write_bytes(b"iso")
            service, virtual = self._service(root, active=True, image=image)
            result = service.load_virtual(str(image))
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["result"]["via"], "already-active")
            self.assertNotIn(start_daemon_argv(), virtual.calls)

    def test_a_full_device_is_left_alone(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = root / "game.iso"
            image.write_bytes(b"iso")
            foreign = _status_json(True, ["/other/disc.iso"])
            service, virtual = self._service(root, active=True, image=image, initial_status=foreign)
            result = service.load_virtual(str(image))
            self.assertFalse(result["ok"])
            self.assertEqual(result["code"], "DRIVE_BUSY")
            self.assertNotIn(load_argv(0, str(image)), virtual.calls)

    def test_cue_without_its_track_file_is_not_sent_to_cdemu(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            cue = root / "game.cue"
            cue.write_text('FILE "game (Track 1).bin" BINARY\n', encoding="utf-8")
            service, virtual = self._service(root, active=True, image=cue)
            result = service.load_virtual(str(cue))
            self.assertFalse(result["ok"])
            self.assertEqual(result["code"], "UNSUPPORTED")
            self.assertEqual(virtual.calls, [])

    def test_cue_track_file_moves_with_the_sheet(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "game (Track 1).bin").write_bytes(b"bin")
            cue = root / "game.cue"
            cue.write_text('FILE "game (Track 1).bin" BINARY\nFILE "../secret.bin" BINARY\n', encoding="utf-8")
            with self.assertRaises(ValueError):
                validate_disc_image(str(cue))
            cue.write_text('FILE "game (Track 1).bin" BINARY\n', encoding="utf-8")
            service, virtual = self._service(root, active=True, image=cue)
            result = service.load_virtual(str(cue))
            self.assertTrue(result["ok"], result)
            self.assertIn(load_argv(0, str(cue)), virtual.calls)

    def test_symlink_and_other_suffixes_are_refused(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = root / "game.iso"
            image.write_bytes(b"iso")
            alias = root / "alias.iso"
            alias.symlink_to(image)
            (root / "game.bin").write_bytes(b"bin")
            service, virtual = self._service(root, active=True, image=image)
            for raw in (str(alias), str(root / "game.bin")):
                result = service.load_virtual(raw)
                self.assertFalse(result["ok"])
                self.assertEqual(result["code"], "UNSUPPORTED")
            self.assertEqual(virtual.calls, [])

    def test_missing_vhba_does_not_start_the_daemon(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = root / "game.iso"
            image.write_bytes(b"iso")
            service, virtual = self._service(root, active=False, image=image, vhba=False)
            result = service.load_virtual(str(image))
            self.assertFalse(result["ok"])
            self.assertEqual(result["code"], "DEPENDENCY_MISSING")
            self.assertNotIn(start_daemon_argv(), virtual.calls)

    def test_unload_requires_the_recorded_image(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = root / "game.iso"
            image.write_bytes(b"iso")
            service, virtual = self._service(root, active=True, image=image)
            loaded = service.load_virtual(str(image))
            self.assertTrue(loaded["ok"], loaded)
            virtual.calls.clear()
            virtual.after[tuple(status_argv(0))] = _result(status_argv(0), _status_json(True, ["/other/disc.iso"]))
            refused = service.unload_virtual(loaded["result"]["slot_id"])
            self.assertFalse(refused["ok"])
            self.assertNotIn(unload_argv(0), virtual.calls)
            virtual.after[tuple(status_argv(0))] = _result(status_argv(0), _status_json(True, [str(image)]))
            removed = service.unload_virtual(loaded["result"]["slot_id"])
            self.assertTrue(removed["ok"], removed)
            self.assertIn(unload_argv(0), virtual.calls)
            self.assertEqual(service.snapshot()["virtual_slots"], [])

    def test_classic_busctl_text_loads_the_image(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = root / "game.iso"
            image.write_bytes(b"iso")
            service, virtual = self._service(root, active=True, image=image)
            virtual.before[tuple(number_argv())] = _result(number_argv(), "Running as unit: run-u1.service\ni 1\n")
            virtual.before[tuple(status_argv(0))] = _result(status_argv(0), "b false\nas 0\n")
            virtual.after[tuple(status_argv(0))] = _result(status_argv(0), f'b true\nas 1 "{image}"\n')
            virtual.before[tuple(mapping_argv(0))] = _result(mapping_argv(0), 's "/dev/sr4"\ns "/dev/sg6"\n')
            virtual.after[tuple(mapping_argv(0))] = virtual.before[tuple(mapping_argv(0))]
            result = service.load_virtual(str(image))
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["result"]["sr_device"], "/dev/sr4")
            self.assertFalse(any(call[0] == "systemd-run" for call in virtual.calls))

    def test_launch_helper_failure_retries_inside_the_session_unit(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = root / "game.iso"
            image.write_bytes(b"iso")
            service, virtual = self._service(
                root,
                active=True,
                image=image,
                number_failure="Call failed: Launch helper exited with unknown return code 1",
            )
            result = service.load_virtual(str(image))
            self.assertTrue(result["ok"], result)
            self.assertIn(_session_wrap(number_argv()), virtual.calls)

    def test_user_bus_failure_retries_inside_the_session_unit(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = root / "game.iso"
            image.write_bytes(b"iso")
            service, virtual = self._service(root, active=True, image=image, number_in_session=True)
            result = service.load_virtual(str(image))
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["result"]["device_number"], 0)
            self.assertIn(_session_wrap(number_argv()), virtual.calls)

    def test_plain_device_count_is_accepted(self) -> None:
        self.assertEqual(_number(CommandResult(["busctl"], 0, "i 1\n", "")), 1)
        self.assertEqual(_number(CommandResult(["busctl"], 0, "Running as unit: run-u1.service\ni 1\n", "")), 1)
        self.assertIsNone(_number(CommandResult(["busctl"], 1, "i 1\n", "Failed to connect to bus")))
        empty = CommandResult(["busctl"], 0, "b false\nas 0\n", "")
        loaded = CommandResult(["busctl"], 0, 'b true\nas 1 "/games/game.iso"\n', "")
        self.assertEqual(_status_parts(empty), ("empty", []))
        self.assertEqual(_status_parts(loaded), ("loaded", ["/games/game.iso"]))
        self.assertEqual(
            _mapping_parts(CommandResult(["busctl"], 0, 's "/dev/sr4"\ns "/dev/sg6"\n', "")),
            ("/dev/sr4", "/dev/sg6"),
        )

    def test_virtual_policy_rejects_the_client_and_blank_discs(self) -> None:
        assert_virtual_argv(load_argv(0, "/games/demo.cue"))
        assert_virtual_argv(start_daemon_argv())
        for argv in (
            ["cdemu", "load", "0", "/games/demo.iso"],
            ["systemctl", "--user", "restart", "cdemu-daemon.service"],
            ["modprobe", "vhba"],
            ["busctl", "--user", "--no-pager", "call", "net.sf.cdemu.CDEmuDaemon", "/Daemon", "net.sf.cdemu.CDEmuDaemon", "AddDevice"],
        ):
            with self.assertRaises(UnsafeCommand):
                assert_virtual_argv(argv)
        with self.assertRaises(UnsafeCommand):
            assert_readonly_argv(["systemctl", "--user", "start", "cdemu-daemon.service"])
        wrapped = _session_wrap(
            number_argv(),
            {"XDG_RUNTIME_DIR": "/run/user/1000", "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus"},
        )
        assert_virtual_argv(wrapped)
        self.assertIn("--setenv=XDG_RUNTIME_DIR=/run/user/1000", wrapped)
        with_guid = _session_wrap(number_argv(), {"DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus,guid=abc"})
        self.assertIn("--setenv=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus", with_guid)
        with self.assertRaises(UnsafeCommand):
            assert_virtual_argv(["systemd-run", "--user", "--pipe", "--wait", "--collect", "--setenv=LD_PRELOAD=/tmp/x", *number_argv()])

    def _service(
        self,
        root: Path,
        *,
        active: bool,
        image: Path,
        initial_status: str | None = None,
        vhba: bool = True,
        number_in_session: bool = False,
        number_failure: str | None = None,
    ) -> tuple[DiagnosticService, SwitchingRunner]:
        sysfs = root / "sys"
        dev = root / "dev"
        write_cdemu_installation(root, sysfs, dev)
        if not vhba:
            shutil.rmtree(sysfs / "module" / "vhba")
        settings = root / "settings"
        settings.mkdir()
        empty = _status_json(False, [])
        loaded = _status_json(True, [str(image)])
        mapping = json.dumps({"type": "ss", "data": ["/dev/sr4", "/dev/sg6"]}) + "\n"
        number = json.dumps({"type": "i", "data": 1}) + "\n"
        if number_failure is None and number_in_session:
            number_failure = "Failed to connect to bus: No such file or directory"
        direct_number = CommandResult(number_argv(), 1, "", number_failure or "")
        before = {
            tuple(start_daemon_argv()): _result(start_daemon_argv(), ""),
            tuple(number_argv()): direct_number if number_failure else _result(number_argv(), number),
            tuple(_session_wrap(number_argv())): _result(_session_wrap(number_argv()), number),
            tuple(status_argv(0)): _result(status_argv(0), initial_status or empty),
            tuple(mapping_argv(0)): _result(mapping_argv(0), mapping),
            tuple(load_argv(0, str(image))): _result(load_argv(0, str(image)), ""),
            tuple(unload_argv(0)): _result(unload_argv(0), ""),
        }
        after = {
            tuple(status_argv(0)): _result(status_argv(0), loaded if initial_status is None else initial_status),
            tuple(mapping_argv(0)): _result(mapping_argv(0), mapping),
        }
        virtual = SwitchingRunner(before, after)
        service = DiagnosticService(
            environ={"DECKY_PLUGIN_SETTINGS_DIR": str(settings)},
            os_module=FakeOs(),
            pwd_module=FakePwd(),
            runner=ScriptedRunner(scripted_bus_responses("{}", cdemu_active=active)),
            virtual_runner=virtual,
            sysfs_root=sysfs,
            root=root,
            dev_root=dev,
            home=root / "home",
            epoch="epoch-virtual",
        )
        return service, virtual


if __name__ == "__main__":
    unittest.main()
