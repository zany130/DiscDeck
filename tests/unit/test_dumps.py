import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from discdeck.commands import CommandResult, CommandRunner, ScriptedRunner
from discdeck.diagnostics import DiagnosticService
from discdeck.dumps import disc_argv, process_start_token, validate_image_name, validate_output_root
from discdeck.errors import UnsafeCommand
from discdeck.physical import unmount_argv
from discdeck.security import assert_dump_argv, assert_physical_udisks_argv, assert_readonly_argv
from tests.support.fixtures import scripted_bus_responses, write_host_sysfs, write_native_redumper, write_redumper_wrapper

BLOCK = "/org/freedesktop/UDisks2/block_devices/sr1"
DRIVE = "/org/freedesktop/UDisks2/drives/bridge_lun0"


def _payload(media: bool, mount: str | None = None) -> str:
    device = [ord(char) for char in "/dev/sr1"] + [0]
    filesystem: dict[str, object] = {"MountPoints": {"type": "aay", "data": []}}
    if mount:
        filesystem = {"MountPoints": {"type": "aay", "data": [[ord(char) for char in mount] + [0]]}}
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
                        "org.freedesktop.UDisks2.Filesystem": filesystem,
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


class FakeDump:
    def __init__(self) -> None:
        self.pid = 4242
        self.start_token = "100"
        self.code: int | None = None
        self.signals: list[str] = []

    def poll(self) -> int | None:
        return self.code

    def terminate(self) -> None:
        self.signals.append("term")

    def kill(self) -> None:
        self.signals.append("kill")
        self.code = -9


class FakeSupervisor:
    def __init__(self) -> None:
        self.argv: list[list[str]] = []
        self.dumps: list[FakeDump] = []
        self.external: dict[int, str] = {}

    def spawn(self, argv: list[str], log_path: Path, on_exit: object, cwd: str | None = None, env: dict[str, str] | None = None) -> FakeDump:
        del on_exit
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self.cwd = cwd
        self.env = env
        self.argv.append(list(argv))
        dump = FakeDump()
        self.dumps.append(dump)
        return dump

    def inspect(self, pid: int, start_token: str) -> str:
        del start_token
        return self.external.get(pid, "gone")


class DumpTests(unittest.TestCase):
    def _service(
        self,
        root: Path,
        binary: Path,
        supervisor: FakeSupervisor,
        *,
        media: bool = True,
        mount: str | None = None,
        mutation: ScriptedRunner | None = None,
        disk_free: int = 10**12,
        settings: dict[str, object] | None = None,
    ) -> DiagnosticService:
        sysfs = root / "sys"
        if not (sysfs / "class" / "block").exists():
            sysfs = write_host_sysfs(root)
        settings_dir = root / "settings"
        settings_dir.mkdir(parents=True, exist_ok=True)
        if settings is not None:
            (settings_dir / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
        logs = root / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        (root / "home").mkdir(parents=True, exist_ok=True)
        version = [str(binary), "--version"]
        return DiagnosticService(
            environ={
                "PATH": str(binary.parent),
                "HOME": str(root / "home"),
                "DECKY_PLUGIN_SETTINGS_DIR": str(settings_dir),
                "DECKY_PLUGIN_LOG_DIR": str(logs),
            },
            os_module=FakeOs(),
            pwd_module=FakePwd(),
            runner=ScriptedRunner(scripted_bus_responses(_payload(media, mount))),
            mutation_runner=mutation or ScriptedRunner(policy=assert_physical_udisks_argv),
            dump_runner=ScriptedRunner(
                {tuple(version): CommandResult(version, 0, "redumper 772\n", "")},
                policy=assert_dump_argv,
            ),
            dump_supervisor=supervisor,
            disk_free=lambda path: disk_free,
            sysfs_root=sysfs,
            root=root,
            dev_root=root / "dev",
            home=root / "home",
            epoch="epoch-dump",
            access=lambda node, mode: True,
        )

    def test_dump_uses_the_sysfs_sg_node_and_does_not_treat_exit_zero_as_verified(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            supervisor = FakeSupervisor()
            binary = write_native_redumper(root / "bin")
            service = self._service(root, binary, supervisor)
            output = root / "output"
            output.mkdir()
            drive = next(item for item in service.snapshot()["drives"] if item["block_node"] == "/dev/sr1")
            started = service.start_dump(drive["drive_id"], drive["generation"], "Demo_1", str(output))
            self.assertTrue(started["ok"], started)
            self.assertEqual(service.dump_runner.ptys, [True])
            self.assertEqual(service.dump_runner.cwds, [str((root / "home").resolve())])
            self.assertIn("/usr/bin", (service.dump_runner.envs[0] or {})["PATH"])
            self.assertEqual(supervisor.cwd, str((root / "home").resolve()))
            self.assertEqual(started["result"]["verification"], "unverified")
            self.assertNotIn("--overwrite", supervisor.argv[0])
            self.assertEqual(supervisor.argv[0][1], "disc")
            self.assertEqual(supervisor.argv[0][2], "--drive=/dev/sg2")
            self.assertTrue(supervisor.argv[0][3].startswith("--image-path="))
            self.assertEqual(supervisor.argv[0][4], "--image-name=Demo_1")
            self.assertFalse(any(call[1:] == ["disc"] or (len(call) > 1 and call[1] == "disc") for call in service.runner.calls))
            blocked = service.mount_drive(drive["drive_id"], drive["generation"], drive["media_generation"])
            self.assertEqual(blocked["code"], "DRIVE_BUSY")
            supervisor.dumps[0].code = 0
            service.dumps.reconcile(service.snapshot()["drives"])
            job = service.dumps.public_jobs()[0]
            self.assertEqual(job["state"], "completed_warnings")
            self.assertEqual(job["verification"], "unverified")
            self.assertIn("did not verify", str(job["message"]))
            self.assertNotIn(drive["drive_id"], service.physical.leases)

    def test_wrapper_runs_only_for_the_explicit_dump(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            supervisor = FakeSupervisor()
            binary = write_redumper_wrapper(root / "bin")
            service = self._service(root, binary, supervisor)
            self.assertEqual(service.snapshot()["probes"]["redumper"]["launch_kind"], "distrobox_wrapper")
            self.assertFalse(service.snapshot()["probes"]["redumper"]["executed"])
            self.assertEqual(service.runner.calls, [call for call in service.runner.calls if Path(call[0]).name != "redumper"])
            output = root / "output"
            output.mkdir()
            drive = next(item for item in service.snapshot()["drives"] if item["block_node"] == "/dev/sr1")
            started = service.start_dump(drive["drive_id"], drive["generation"], "disc", str(output))
            self.assertTrue(started["ok"], started)
            self.assertEqual(started["result"]["launch_kind"], "distrobox_wrapper")
            self.assertEqual(supervisor.argv[0][0], str(binary))
            self.assertEqual(supervisor.argv[0][1], "disc")

    def test_refusals_do_not_spawn_redumper(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            supervisor = FakeSupervisor()
            binary = write_native_redumper(root / "bin")
            output = root / "output"
            output.mkdir()
            link = root / "linked-output"
            link.symlink_to(output, target_is_directory=True)
            service = self._service(root, binary, supervisor)
            drive = next(item for item in service.snapshot()["drives"] if item["block_node"] == "/dev/sr1")
            bad_name = service.start_dump(drive["drive_id"], drive["generation"], "../disc", str(output))
            self.assertEqual(bad_name["code"], "OUTPUT_INVALID")
            linked = service.start_dump(drive["drive_id"], drive["generation"], "disc", str(link))
            self.assertEqual(linked["code"], "OUTPUT_INVALID")
            empty = self._service(root / "empty-media", binary, supervisor, media=False)
            empty_drive = next(item for item in empty.snapshot()["drives"] if item["block_node"] == "/dev/sr1")
            (root / "empty-media" / "output").mkdir(parents=True)
            no_media = empty.start_dump(empty_drive["drive_id"], empty_drive["generation"], "disc", str(root / "empty-media" / "output"))
            self.assertEqual(no_media["code"], "DRIVE_NOT_READY")
            tight = self._service(root / "tight", binary, supervisor, disk_free=10)
            (root / "tight" / "output").mkdir(parents=True)
            tight_drive = next(item for item in tight.snapshot()["drives"] if item["block_node"] == "/dev/sr1")
            space = tight.start_dump(tight_drive["drive_id"], tight_drive["generation"], "disc", str(root / "tight" / "output"))
            self.assertEqual(space["code"], "INSUFFICIENT_SPACE")
            self.assertEqual(supervisor.argv, [])

    def test_foreign_mount_is_left_alone_and_owned_mount_is_removed_first(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            binary = write_native_redumper(root / "bin")
            foreign_supervisor = FakeSupervisor()
            foreign = self._service(root / "foreign", binary, foreign_supervisor, mount="/run/media/hostuser/DISC")
            output = root / "foreign" / "output"
            output.mkdir(parents=True)
            drive = next(item for item in foreign.snapshot()["drives"] if item["block_node"] == "/dev/sr1")
            refused = foreign.start_dump(drive["drive_id"], drive["generation"], "disc", str(output))
            self.assertEqual(refused["code"], "UNMOUNT_FAILED")
            self.assertEqual(foreign_supervisor.argv, [])
            self.assertEqual(foreign.mutation_runner.calls, [])
            removed = unmount_argv(BLOCK)
            mutation = ScriptedRunner({tuple(removed): CommandResult(removed, 0, "", "")}, policy=assert_physical_udisks_argv)
            owned_supervisor = FakeSupervisor()
            owned = self._service(root / "owned", binary, owned_supervisor, mount="/run/media/hostuser/DISC", mutation=mutation)
            owned_output = root / "owned" / "output"
            owned_output.mkdir(parents=True)
            owned_drive = next(item for item in owned.snapshot()["drives"] if item["block_node"] == "/dev/sr1")
            owned.physical.owned_mounts[owned_drive["drive_id"]] = {"block_path": BLOCK, "mount_path": "/run/media/hostuser/DISC"}
            started = owned.start_dump(owned_drive["drive_id"], owned_drive["generation"], "disc", str(owned_output))
            self.assertTrue(started["ok"], started)
            self.assertEqual(mutation.calls, [removed])

    def test_cancel_keeps_output_and_force_stop_needs_confirmation(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            supervisor = FakeSupervisor()
            binary = write_native_redumper(root / "bin")
            service = self._service(root, binary, supervisor)
            output = root / "output"
            output.mkdir()
            drive = next(item for item in service.snapshot()["drives"] if item["block_node"] == "/dev/sr1")
            started = service.start_dump(drive["drive_id"], drive["generation"], "disc", str(output))
            job_id = started["result"]["job_id"]
            output_dir = Path(started["result"]["output_dir"])
            early = service.force_stop_dump(job_id, False)
            self.assertEqual(early["code"], "CONSENT_REQUIRED")
            cancelled = service.cancel_dump(job_id)
            self.assertTrue(cancelled["ok"], cancelled)
            self.assertEqual(supervisor.dumps[0].signals, ["term"])
            self.assertEqual(cancelled["result"]["state"], "cancel_requested")
            self.assertTrue(output_dir.is_dir())
            unconfirmed = service.force_stop_dump(job_id, False)
            self.assertEqual(unconfirmed["code"], "CONSENT_REQUIRED")
            self.assertEqual(supervisor.dumps[0].signals, ["term"])
            forced = service.force_stop_dump(job_id, True)
            self.assertTrue(forced["ok"], forced)
            self.assertEqual(forced["result"]["state"], "interrupted")
            self.assertEqual(forced["result"]["verification"], "unverified")
            self.assertTrue(output_dir.is_dir())

    def test_restart_keeps_an_unwatched_process_unverified_until_acknowledged(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            supervisor = FakeSupervisor()
            binary = write_native_redumper(root / "bin")
            service = self._service(root, binary, supervisor)
            output = root / "output"
            output.mkdir()
            drive = next(item for item in service.snapshot()["drives"] if item["block_node"] == "/dev/sr1")
            service.start_dump(drive["drive_id"], drive["generation"], "disc", str(output))
            restarted_supervisor = FakeSupervisor()
            restarted_supervisor.external[4242] = "running"
            restarted = self._service(root, binary, restarted_supervisor)
            job = restarted.snapshot()["jobs"][0]
            self.assertEqual(job["state"], "orphaned_running")
            self.assertEqual(job["verification"], "unverified")
            busy = restarted.start_dump(drive["drive_id"], drive["generation"], "disc", str(output))
            self.assertEqual(busy["code"], "DRIVE_BUSY")
            self.assertEqual(restarted_supervisor.argv, [])
            restarted_supervisor.external[4242] = "gone"
            restarted.dumps.reconcile(restarted.snapshot()["drives"])
            waiting = restarted.dumps.public_jobs()[0]
            self.assertTrue(waiting["needs_ack"])
            self.assertEqual(waiting["state"], "interrupted")
            released = restarted.acknowledge_dump(waiting["job_id"])
            self.assertTrue(released["ok"], released)
            self.assertFalse(released["result"]["needs_ack"])
            again = restarted.start_dump(drive["drive_id"], drive["generation"], "disc", str(output))
            self.assertTrue(again["ok"], again)

    def test_a_lost_drive_stops_the_dump_without_deleting_output(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            supervisor = FakeSupervisor()
            binary = write_native_redumper(root / "bin")
            service = self._service(root, binary, supervisor)
            output = root / "output"
            output.mkdir()
            drive = next(item for item in service.snapshot()["drives"] if item["block_node"] == "/dev/sr1")
            started = service.start_dump(drive["drive_id"], drive["generation"], "disc", str(output))
            service.dumps.reconcile([])
            job = service.dumps.public_jobs()[0]
            self.assertEqual(job["state"], "interrupted")
            self.assertIn("disappeared", str(job["message"]))
            self.assertEqual(supervisor.dumps[0].signals, ["term"])
            self.assertTrue(Path(started["result"]["output_dir"]).is_dir())

    def test_disabled_module_and_failed_version_do_not_run_disc(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            supervisor = FakeSupervisor()
            binary = write_native_redumper(root / "bin")
            disabled = self._service(
                root / "off",
                binary,
                supervisor,
                settings={"schema_version": 1, "settings_revision": 1, "modules": {"dump.redumper": False}},
            )
            output = root / "off" / "output"
            output.mkdir(parents=True)
            drive = next(item for item in disabled.snapshot()["drives"] if item["block_node"] == "/dev/sr1")
            refused = disabled.start_dump(drive["drive_id"], drive["generation"], "disc", str(output))
            self.assertEqual(refused["code"], "MODULE_DISABLED")
            version = [str(binary), "--version"]
            failed = DiagnosticService(
                environ={
                    "PATH": str(binary.parent),
                    "HOME": str(root / "home"),
                    "DECKY_PLUGIN_SETTINGS_DIR": str(root / "bad-settings"),
                    "DECKY_PLUGIN_LOG_DIR": str(root / "bad-logs"),
                },
                os_module=FakeOs(),
                pwd_module=FakePwd(),
                runner=ScriptedRunner(scripted_bus_responses(_payload(True))),
                dump_runner=ScriptedRunner({tuple(version): CommandResult(version, 1, "", "no")}, policy=assert_dump_argv),
                dump_supervisor=supervisor,
                disk_free=lambda path: 10**12,
                sysfs_root=write_host_sysfs(root / "bad"),
                root=root / "bad",
                dev_root=root / "bad" / "dev",
                home=root / "home",
                epoch="epoch-dump",
                access=lambda node, mode: True,
            )
            (root / "bad-settings").mkdir()
            (root / "bad-logs").mkdir()
            (root / "bad" / "output").mkdir()
            bad_drive = next(item for item in failed.snapshot()["drives"] if item["block_node"] == "/dev/sr1")
            version_failed = failed.start_dump(bad_drive["drive_id"], bad_drive["generation"], "disc", str(root / "bad" / "output"))
            self.assertEqual(version_failed["code"], "UNSUPPORTED_REDUMPER_VERSION")
            self.assertIn("exited 1: no", version_failed["message"])
            self.assertEqual(supervisor.argv, [])
            self.assertEqual(failed.dumps.public_jobs()[0]["state"], "failed")

    def test_plugin_imports_without_the_termios_module(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                "import builtins\n"
                "real = builtins.__import__\n"
                "def guarded(name, globals=None, locals=None, fromlist=(), level=0):\n"
                "    if name in {'pty', 'tty', 'termios'}:\n"
                "        raise ModuleNotFoundError(name)\n"
                "    return real(name, globals, locals, fromlist, level)\n"
                "builtins.__import__ = guarded\n"
                "import discdeck.commands\n"
                "import discdeck.dumps\n"
                "pair = discdeck.commands.open_pty_pair()\n"
                "assert pair is not None\n"
                "import os\n"
                "os.close(pair[0]); os.close(pair[1])\n",
            ],
            check=False,
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONPATH": "py_modules"},
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_terminal_version_text_is_captured(self) -> None:
        result = CommandRunner(policy=lambda argv: None)(["/bin/echo", "redumper (build: 772)"], timeout=5, pty=True)
        self.assertEqual(result.code, 0)
        self.assertIn("redumper (build: 772)", result.stdout)

    def test_retries_and_command_policy(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            supervisor = FakeSupervisor()
            binary = write_native_redumper(root / "bin")
            service = self._service(
                root,
                binary,
                supervisor,
                settings={"schema_version": 1, "settings_revision": 1, "redumper_retries": 2, "modules": {}},
            )
            output = root / "output"
            output.mkdir()
            drive = next(item for item in service.snapshot()["drives"] if item["block_node"] == "/dev/sr1")
            started = service.start_dump(drive["drive_id"], drive["generation"], "disc", str(output))
            self.assertTrue(started["ok"], started)
            self.assertEqual(supervisor.argv[0][-1], "--retries=2")
            argv = disc_argv(str(binary), "/dev/sg2", str(output / "job"), "disc", 2)
            assert_dump_argv(argv)
            with self.assertRaises(UnsafeCommand):
                assert_dump_argv(argv + ["--overwrite"])
            with self.assertRaises(UnsafeCommand):
                assert_readonly_argv([str(binary), "disc", "--drive=/dev/sg2"])
            self.assertEqual(process_start_token(12, lambda pid: "12 (redumper) S 1 12 12 0 -1 0 0 0 0 0 0 0 0 20 0 1 0 999 555\n"), "555")
            with self.assertRaises(ValueError):
                validate_image_name("a/b")
            with self.assertRaises(ValueError):
                validate_output_root("relative")


if __name__ == "__main__":
    unittest.main()
