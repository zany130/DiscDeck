import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from discdeck.commands import CommandResult, ScriptedRunner
from discdeck.diagnostics import DiagnosticService
from discdeck.errors import UnsafeCommand
from discdeck.launch import app_id, format_rungameid, launch_argv, list_shortcuts
from discdeck.security import assert_launch_argv, assert_readonly_argv
from tests.support.fixtures import write_steam_home


def _cstr(text: str) -> bytes:
    return text.encode("utf-8") + b"\x00"


def _shortcut_vdf(app_name: str, exe: str) -> bytes:
    fields = b"\x01" + _cstr("AppName") + _cstr(app_name) + b"\x01" + _cstr("Exe") + _cstr(exe)
    entry = b"\x00" + _cstr("0") + fields + b"\x08"
    return b"\x00" + _cstr("shortcuts") + entry + b"\x08"


class SteamLaunchTests(unittest.TestCase):
    def test_a_listed_shortcut_is_sent_to_steam_and_an_unknown_id_is_not(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "home"
            steam_root = write_steam_home(home)
            exe = '"/games/demo.exe"'
            blob = _shortcut_vdf("Demo", exe)
            shortcut = steam_root / "userdata" / "1" / "config" / "shortcuts.vdf"
            prefix = steam_root / "steamapps" / "compatdata" / "123" / "pfx" / "user.reg"
            before_prefix = prefix.read_bytes()
            shortcut.write_bytes(blob)
            listed = list_shortcuts(home)
            rungameid = format_rungameid(app_id(exe, "Demo"))
            self.assertEqual(listed["shortcuts"], [{"app_name": "Demo", "rungameid": rungameid}])
            self.assertNotIn(str(prefix), listed["files_read"])
            self.assertEqual(prefix.read_bytes(), before_prefix)
            binary = root / "bin" / "steam"
            binary.parent.mkdir()
            binary.write_bytes(b"")
            argv = launch_argv(str(binary), rungameid)
            runner = ScriptedRunner(
                {tuple(argv): CommandResult(argv, 0, "", "")},
                policy=assert_launch_argv,
            )
            service = DiagnosticService(
                environ={"PATH": str(binary.parent), "HOME": str(home)},
                os_module=object(),
                pwd_module=object(),
                home=home,
                root=root,
                launch_runner=runner,
                epoch="epoch-launch",
            )
            refused = service.launch_shortcut("1")
            self.assertFalse(refused["ok"])
            self.assertEqual(runner.calls, [])
            launched = service.launch_shortcut(rungameid)
            self.assertTrue(launched["ok"], launched)
            self.assertEqual(launched["result"]["app_name"], "Demo")
            self.assertFalse(launched["result"]["hardware_validated"])
            self.assertEqual(runner.calls, [argv])

    def test_a_symlink_shortcut_file_is_not_opened(self) -> None:
        with TemporaryDirectory() as temporary:
            home = Path(temporary)
            steam_root = write_steam_home(home)
            shortcut = steam_root / "userdata" / "1" / "config" / "shortcuts.vdf"
            shortcut.unlink()
            shortcut.symlink_to("user.reg")
            listed = list_shortcuts(home)
            self.assertEqual(listed["shortcuts"], [])
            self.assertFalse(listed["opened"])
            self.assertEqual(listed["files_read"], [])

    def test_launch_policy_allows_one_rungameid_url(self) -> None:
        assert_launch_argv(["/usr/bin/steam", "steam://rungameid/42"])
        for argv in (
            ["steam", "steam://rungameid/42"],
            ["/usr/bin/steam", "steam://openurl/https://example.invalid"],
            ["/usr/bin/steam", "steam://rungameid/42", "--extra"],
            ["/tmp/steam-runtime", "steam://rungameid/42"],
        ):
            with self.assertRaises(UnsafeCommand):
                assert_launch_argv(argv)
        with self.assertRaises(UnsafeCommand):
            assert_readonly_argv(["/usr/bin/steam", "steam://rungameid/42"])


if __name__ == "__main__":
    unittest.main()
