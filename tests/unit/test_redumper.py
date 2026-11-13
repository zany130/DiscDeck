import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from discdeck.adapters.redumper import discover, read_version
from discdeck.commands import CommandResult, ScriptedRunner
from discdeck.errors import UnsafeCommand
from discdeck.security import assert_readonly_argv
from tests.support.fixtures import write_managed_redumper, write_native_redumper, write_redumper_wrapper


class RedumperTests(unittest.TestCase):
    def test_path_user_bin_and_configured_host_copies_are_ignored(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            wrapper = write_redumper_wrapper(root / "bin")
            home = root / "home"
            write_redumper_wrapper(home / ".local" / "bin")
            plugin = root / "plugin"
            managed = write_managed_redumper(plugin)
            found = discover(
                {
                    "PATH": str(wrapper.parent),
                    "DECKY_USER_HOME": str(home),
                    "HOME": str(home),
                    "DECKY_PLUGIN_DIR": str(plugin),
                }
            )
            self.assertEqual(found["path"], str(managed))
            self.assertEqual(found["launch_kind"], "native_executable")
            self.assertEqual(found["origin"], "bundled")
            self.assertEqual(found["build"], 772)
            self.assertEqual(found["reason_code"], "REDUMPER_VERSION_NOT_EXECUTED")
            self.assertFalse(found["executed"])
            runner = ScriptedRunner()
            version = read_version(str(wrapper), runner, allow_untested_wrapper=True)
            self.assertEqual(version["reason_code"], "REDUMPER_NOT_MANAGED")
            self.assertEqual(runner.calls, [])

    def test_native_version_uses_only_version_flag(self) -> None:
        with TemporaryDirectory() as temporary:
            path = write_managed_redumper(Path(temporary) / "plugin")
            runner = ScriptedRunner({(str(path), "--version"): CommandResult([str(path), "--version"], 0, "redumper 772\n", "")})
            found = read_version(str(path), runner, allow_untested_wrapper=False)
            self.assertEqual(found["version_status"], "observed")
            self.assertEqual(found["status"], "untested")
            self.assertFalse(found["hardware_validated"])
            self.assertEqual(runner.calls, [[str(path), "--version"]])

    def test_unmanaged_elf_is_not_executed(self) -> None:
        with TemporaryDirectory() as temporary:
            path = write_native_redumper(Path(temporary))
            runner = ScriptedRunner({(str(path), "--version"): CommandResult([str(path), "--version"], 0, "redumper 772\n", "")})
            found = read_version(str(path), runner)
            self.assertEqual(found["reason_code"], "REDUMPER_NOT_MANAGED")
            self.assertEqual(runner.calls, [])

    def test_missing_binary(self) -> None:
        found = discover({"PATH": "/does/not/exist", "DECKY_PLUGIN_DIR": "/does/not/exist"})
        self.assertEqual(found["reason_code"], "REDUMPER_MISSING")
        self.assertFalse(found["executed"])

    def test_newer_update_wins_and_a_newer_bundle_wins_back(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            plugin = root / "plugin"
            settings = root / "settings"
            bundled = write_managed_redumper(plugin, build=772, origin="bundled")
            updated = write_managed_redumper(settings, build=780, origin="updated")
            environ = {"DECKY_PLUGIN_DIR": str(plugin), "DECKY_PLUGIN_SETTINGS_DIR": str(settings), "PATH": "/usr/bin"}
            found = discover(environ)
            self.assertEqual(found["path"], str(updated))
            self.assertEqual(found["origin"], "updated")
            self.assertEqual(found["build"], 780)
            self.assertEqual(found["bundled_build"], 772)
            self.assertNotEqual(found["path"], str(bundled))
            write_managed_redumper(plugin, build=790, origin="bundled")
            found = discover(environ)
            self.assertEqual(found["path"], str(plugin / "bin" / "redumper"))
            self.assertEqual(found["origin"], "bundled")
            self.assertEqual(found["build"], 790)
            self.assertNotEqual(found["path"], str(updated))

    def test_disc_command_is_refused(self) -> None:
        with self.assertRaises(UnsafeCommand):
            assert_readonly_argv(["redumper", "disc", "--drive=/dev/sg1"])


if __name__ == "__main__":
    unittest.main()
