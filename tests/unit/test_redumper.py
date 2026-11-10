import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from discdeck.adapters.redumper import discover, read_version
from discdeck.commands import CommandResult, ScriptedRunner
from discdeck.errors import UnsafeCommand
from discdeck.security import assert_readonly_argv
from tests.support.fixtures import write_native_redumper, write_redumper_wrapper


class RedumperTests(unittest.TestCase):
    def test_wrapper_is_discovered_and_not_executed(self) -> None:
        with TemporaryDirectory() as temporary:
            write_redumper_wrapper(Path(temporary))
            runner = ScriptedRunner()
            found = discover({"PATH": temporary})
            self.assertEqual(found["launch_kind"], "distrobox_wrapper")
            self.assertEqual(found["version_status"], "not_executed")
            self.assertFalse(found["executed"])
            self.assertIsNotNone(found["sha256"])
            version = read_version(found["path"], runner, allow_untested_wrapper=False)
            self.assertEqual(version["reason_code"], "DISTROBOX_WRAPPER_NOT_EXECUTED")
            self.assertEqual(runner.calls, [])

    def test_native_version_uses_only_version_flag(self) -> None:
        with TemporaryDirectory() as temporary:
            path = write_native_redumper(Path(temporary))
            runner = ScriptedRunner({(str(path), "--version"): CommandResult([str(path), "--version"], 0, "redumper 772\n", "")})
            found = read_version(str(path), runner, allow_untested_wrapper=False)
            self.assertEqual(found["version_status"], "observed")
            self.assertEqual(found["status"], "untested")
            self.assertFalse(found["hardware_validated"])
            self.assertEqual(runner.calls, [[str(path), "--version"]])

    def test_missing_binary(self) -> None:
        found = discover({"PATH": "/does/not/exist"})
        self.assertEqual(found["reason_code"], "REDUMPER_MISSING")
        self.assertFalse(found["executed"])

    def test_user_bin_is_found_when_decky_path_omits_it(self) -> None:
        with TemporaryDirectory() as temporary:
            home = Path(temporary) / "home" / "hostuser"
            path = write_redumper_wrapper(home / ".local" / "bin")
            found = discover({"PATH": "/usr/bin", "DECKY_USER_HOME": str(home)})
            self.assertEqual(found["path"], str(path))
            self.assertEqual(found["launch_kind"], "distrobox_wrapper")
            self.assertEqual(found["reason_code"], "REDUMPER_VERSION_NOT_EXECUTED")
            self.assertFalse(found["executed"])
            runner = ScriptedRunner()
            version = read_version(found["path"], runner, allow_untested_wrapper=False)
            self.assertEqual(version["reason_code"], "DISTROBOX_WRAPPER_NOT_EXECUTED")
            self.assertEqual(runner.calls, [])

    def test_disc_command_is_refused(self) -> None:
        with self.assertRaises(UnsafeCommand):
            assert_readonly_argv(["redumper", "disc", "--drive=/dev/sg1"])


if __name__ == "__main__":
    unittest.main()
