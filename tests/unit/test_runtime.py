import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from discdeck.runtime import drop_privileges, probe_runtime


class FakeOs:
    def __init__(self, euid: int = 1000, egid: int = 1000) -> None:
        self._euid = euid
        self._egid = egid
        self.setuid_calls: list[int] = []
        self.setgid_calls: list[int] = []

    def geteuid(self) -> int:
        return self._euid

    def getegid(self) -> int:
        return self._egid

    def setuid(self, uid: int) -> None:
        self.setuid_calls.append(uid)
        self._euid = uid

    def setgid(self, gid: int) -> None:
        self.setgid_calls.append(gid)
        self._egid = gid


class FakePwd:
    def __init__(self, users: dict[str, SimpleNamespace]) -> None:
        self.users = users

    def getpwnam(self, name: str) -> SimpleNamespace:
        if name not in self.users:
            raise KeyError(name)
        return self.users[name]

    def getpwuid(self, uid: int) -> SimpleNamespace:
        for user in self.users.values():
            if user.pw_uid == uid:
                return user
        raise KeyError(uid)


class RuntimeTests(unittest.TestCase):
    def test_non_root_process_is_not_changed(self) -> None:
        os_module = FakeOs(1000, 1000)
        pwd_module = FakePwd({"hostuser": SimpleNamespace(pw_name="hostuser", pw_uid=1000, pw_gid=1000)})
        result = drop_privileges(os_module, pwd_module, {"DECKY_USER": "hostuser"})
        self.assertEqual(result["status"], "already_unprivileged")
        self.assertEqual(os_module.setuid_calls, [])

    def test_unexpected_root_drops_to_resolved_owner_without_guessing(self) -> None:
        os_module = FakeOs(0, 0)
        pwd_module = FakePwd({"hostuser": SimpleNamespace(pw_name="hostuser", pw_uid=1000, pw_gid=1000)})
        result = drop_privileges(os_module, pwd_module, {"DECKY_USER": "hostuser"})
        self.assertEqual(result["status"], "dropped")
        self.assertEqual(os_module.setgid_calls, [1000])
        self.assertEqual(os_module.setuid_calls, [1000])

    def test_unknown_owner_does_not_assume_uid_1000(self) -> None:
        os_module = FakeOs(0, 0)
        result = drop_privileges(os_module, FakePwd({}), {"DECKY_USER": "missing-user"})
        self.assertEqual(result["error"], "PRIVILEGE_DROP_UNVERIFIED")
        self.assertEqual(os_module.setuid_calls, [])

    def test_underscore_root_flag_does_not_request_root(self) -> None:
        with TemporaryDirectory() as temporary:
            plugin = Path(temporary)
            (plugin / "plugin.json").write_text(json.dumps({"flags": ["debug", "_root"]}), encoding="utf-8")
            os_module = FakeOs()
            pwd_module = FakePwd({"hostuser": SimpleNamespace(pw_name="hostuser", pw_uid=1000, pw_gid=1000)})
            found = probe_runtime(
                os_module,
                pwd_module,
                {"USER": "hostuser", "DECKY_USER": "hostuser", "DECKY_PLUGIN_DIR": temporary},
            )
            self.assertFalse(found["root_requested"])
            self.assertEqual(found["owner_uid"], 1000)
            self.assertEqual(found["directories"]["settings"]["status"], "unset")
            self.assertEqual(found["directories"]["runtime"]["durability"], "untested")

    def test_root_flag_is_reported(self) -> None:
        with TemporaryDirectory() as temporary:
            (Path(temporary) / "plugin.json").write_text(json.dumps({"flags": ["root"]}), encoding="utf-8")
            found = probe_runtime(FakeOs(), FakePwd({}), {"DECKY_PLUGIN_DIR": temporary})
            self.assertTrue(found["root_requested"])


if __name__ == "__main__":
    unittest.main()
