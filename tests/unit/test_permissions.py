import stat
import unittest
from types import SimpleNamespace

from discdeck.adapters.permissions import inspect_nodes
from tests.support.fixtures import named_acl


class PermissionTests(unittest.TestCase):
    def test_named_acl_access_is_observed_not_proven(self) -> None:
        nodes = ["/dev/sr1", "/dev/sg2", "/dev/vhba_ctl"]

        def access(node: str, mode: int) -> bool:
            return node in nodes

        def stat_fn(node: str):
            return SimpleNamespace(st_mode=stat.S_IFCHR | 0o660, st_uid=0, st_gid=0)

        found = inspect_nodes(nodes, access=access, stat_fn=stat_fn, getfacl=named_acl)
        self.assertTrue(all(node["status"] == "observed" for node in found["nodes"]))
        self.assertEqual(found["nodes"][0]["named_users"], [{"user": "hostuser", "permissions": "rw-"}])
        self.assertTrue(all(node["hardware_validated"] is False for node in found["nodes"]))

    def test_effective_denial_is_denied(self) -> None:
        def access(node: str, mode: int) -> bool:
            return False

        def stat_fn(node: str):
            return SimpleNamespace(st_mode=stat.S_IFCHR | 0o660, st_uid=0, st_gid=6)

        found = inspect_nodes(["/dev/sg0"], access=access, stat_fn=stat_fn, getfacl=lambda node: "user::rw-\ngroup::rw-\nother::---\n")
        self.assertEqual(found["nodes"][0]["status"], "denied")
        self.assertEqual(found["nodes"][0]["reason_code"], "PERMISSION_DENIED")
        self.assertEqual(found["nodes"][0]["named_users"], [])

    def test_missing_getfacl_is_not_a_denial(self) -> None:
        def access(node: str, mode: int) -> bool:
            return True

        def stat_fn(node: str):
            return SimpleNamespace(st_mode=stat.S_IFCHR | 0o660, st_uid=0, st_gid=0)

        found = inspect_nodes(["/dev/sr0"], access=access, stat_fn=stat_fn, getfacl=lambda node: None)
        self.assertEqual(found["nodes"][0]["status"], "observed")
        self.assertEqual(found["nodes"][0]["acl_status"], "unavailable")

    def test_absent_node_is_missing(self) -> None:
        found = inspect_nodes(["/dev/does-not-exist-discdeck"], getfacl=lambda node: None)
        self.assertEqual(found["nodes"][0]["status"], "missing")


if __name__ == "__main__":
    unittest.main()
