import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from discdeck.adapters.steam import probe_steam
from tests.support.fixtures import write_steam_home


class SteamDiscoveryTests(unittest.TestCase):
    def test_discovery_does_not_read_shortcuts_or_prefixes(self) -> None:
        with TemporaryDirectory() as temporary:
            home = Path(temporary)
            steam = write_steam_home(home)
            shortcuts = steam / "userdata" / "1" / "config" / "shortcuts.vdf"
            prefix = steam / "steamapps" / "compatdata" / "123" / "pfx" / "user.reg"
            before = (shortcuts.read_bytes(), prefix.read_bytes(), shortcuts.stat().st_mtime_ns, prefix.stat().st_mtime_ns)
            found = probe_steam(home, {"PATH": ""}, root=home)
            after = (shortcuts.read_bytes(), prefix.read_bytes(), shortcuts.stat().st_mtime_ns, prefix.stat().st_mtime_ns)
            self.assertEqual(before, after)
            self.assertFalse(found["shortcuts_read"])
            self.assertFalse(found["prefixes_read"])
            self.assertFalse(found["launched"])
            self.assertEqual(found["status"], "untested")
            self.assertTrue(any(tool["name"] == "GE-Proton10-34" for tool in found["compatibility_tools"]))
            self.assertTrue(any(tool["name"] == "Proton 10.0" for tool in found["compatibility_tools"]))
            self.assertNotIn(str(shortcuts), found["files_read"])
            self.assertNotIn(str(prefix), found["files_read"])

    def test_missing_steam_is_not_ready(self) -> None:
        with TemporaryDirectory() as temporary:
            found = probe_steam(Path(temporary), {"PATH": ""}, root=Path(temporary))
            self.assertEqual(found["status"], "missing")
            self.assertFalse(found["hardware_validated"])


if __name__ == "__main__":
    unittest.main()
