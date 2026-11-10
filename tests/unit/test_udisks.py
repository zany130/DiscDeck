import json
import unittest

from discdeck.adapters.udisks2 import classify_optical, normalize_managed_objects, probe_udisks
from discdeck.commands import CommandResult, ScriptedRunner
from tests.support.fixtures import udisks_busctl_payload


class UDisksTests(unittest.TestCase):
    def test_optical_false_does_not_override_sr_node_or_sysfs_type(self) -> None:
        optical, evidence = classify_optical(
            {"Optical": False},
            {"Device": "/dev/sr1"},
            "5",
        )
        self.assertTrue(optical)
        self.assertIn("sysfs_type_5", evidence)
        self.assertIn("udisks_optical_false_not_authoritative", evidence)
        not_optical, _ = classify_optical({"Optical": False}, {"Device": "/dev/sda"}, None)
        self.assertFalse(not_optical)

    def test_busctl_payload_marks_empty_sr_optical_without_mounting(self) -> None:
        payload = udisks_busctl_payload()
        objects = normalize_managed_objects(json.loads(payload))
        runner = ScriptedRunner(
            {
                ("busctl", "--system", "--no-pager", "list"): CommandResult(["busctl"], 0, "org.freedesktop.UDisks2 4242 udisksd root\n", ""),
                (
                    "busctl",
                    "--system",
                    "--json=short",
                    "call",
                    "org.freedesktop.UDisks2",
                    "/org/freedesktop/UDisks2",
                    "org.freedesktop.DBus.ObjectManager",
                    "GetManagedObjects",
                ): CommandResult(["busctl"], 0, payload, ""),
            }
        )
        found = probe_udisks(runner)
        self.assertEqual(found["status"], "observed")
        self.assertEqual(found["activated"], False)
        self.assertEqual(found["drives"][0]["device"], "/dev/sr1")
        self.assertTrue(found["drives"][0]["optical"])
        self.assertFalse(found["drives"][0]["udisks_optical_property"])
        self.assertFalse(found["drives"][0]["media_available"])
        self.assertTrue(all(state == "not_run" for state in found["drives"][0]["operations"].values()))
        self.assertEqual(len(runner.calls), 2)

    def test_inactive_service_is_not_activated(self) -> None:
        runner = ScriptedRunner(
            {
                ("busctl", "--system", "--no-pager", "list"): CommandResult(
                    ["busctl"],
                    0,
                    "org.freedesktop.UDisks2 - - -\n",
                    "",
                )
            }
        )
        found = probe_udisks(runner)
        self.assertEqual(found["reason_code"], "UDISKS2_INACTIVE")
        self.assertEqual(found["activated"], False)
        self.assertEqual(len(runner.calls), 1)

    def test_missing_client_is_missing(self) -> None:
        found = probe_udisks(ScriptedRunner())
        self.assertEqual(found["status"], "missing")
        self.assertEqual(found["reason_code"], "UDISKS2_CLIENT_MISSING")

    def test_normalized_objects_round_trip(self) -> None:
        objects = normalize_managed_objects(json.loads(udisks_busctl_payload()))
        self.assertIn("/org/freedesktop/UDisks2/drives/bridge_lun0", objects)

    def test_systemd_257_object_map_is_read_without_mounting(self) -> None:
        payload = json.dumps(
            {
                "type": "(a{oa{sa{sv}}})",
                "data": [
                    {
                        "/org/freedesktop/UDisks2/block_devices/sr0": {
                            "org.freedesktop.UDisks2.Block": {
                                "Device": {"type": "ay", "data": [ord(char) for char in "/dev/sr0"] + [0]},
                                "Drive": {"type": "o", "data": "/org/freedesktop/UDisks2/drives/generic"},
                                "Size": {"type": "t", "data": 0},
                            }
                        },
                        "/org/freedesktop/UDisks2/block_devices/sr1": {
                            "org.freedesktop.UDisks2.Block": {
                                "Device": {"type": "ay", "data": [ord(char) for char in "/dev/sr1"] + [0]},
                                "Drive": {"type": "o", "data": "/org/freedesktop/UDisks2/drives/bridge_lun0"},
                            }
                        },
                        "/org/freedesktop/UDisks2/block_devices/sr2": {
                            "org.freedesktop.UDisks2.Block": {
                                "Device": {"type": "ay", "data": [ord(char) for char in "/dev/sr2"] + [0]},
                                "Drive": {"type": "o", "data": "/org/freedesktop/UDisks2/drives/bridge_lun1"},
                            }
                        },
                        "/org/freedesktop/UDisks2/drives/bridge_lun0": {
                            "org.freedesktop.UDisks2.Drive": {
                                "Optical": {"type": "b", "data": False},
                                "MediaAvailable": {"type": "b", "data": False},
                                "ConnectionBus": {"type": "s", "data": "usb"},
                            }
                        },
                        "/org/freedesktop/UDisks2/drives/bridge_lun1": {
                            "org.freedesktop.UDisks2.Drive": {
                                "Optical": {"type": "b", "data": False},
                                "MediaAvailable": {"type": "b", "data": True},
                            }
                        },
                        "/org/freedesktop/UDisks2/drives/generic": {
                            "org.freedesktop.UDisks2.Drive": {
                                "Optical": {"type": "b", "data": False},
                                "MediaAvailable": {"type": "b", "data": False},
                            }
                        },
                    }
                ],
            }
        )
        found = probe_udisks(
            ScriptedRunner(
                {
                    ("busctl", "--system", "--no-pager", "list"): CommandResult(["busctl"], 0, "org.freedesktop.UDisks2 4242 udisksd root\n", ""),
                    (
                        "busctl",
                        "--system",
                        "--json=short",
                        "call",
                        "org.freedesktop.UDisks2",
                        "/org/freedesktop/UDisks2",
                        "org.freedesktop.DBus.ObjectManager",
                        "GetManagedObjects",
                    ): CommandResult(["busctl"], 0, payload, ""),
                }
            )
        )
        self.assertEqual(found["status"], "observed")
        self.assertEqual(found["reason_code"], None)
        by_device = {item["device"]: item for item in found["drives"]}
        self.assertEqual(set(by_device), {"/dev/sr0", "/dev/sr1", "/dev/sr2"})
        self.assertFalse(by_device["/dev/sr1"]["media_available"])
        self.assertTrue(by_device["/dev/sr2"]["media_available"])
        self.assertFalse(by_device["/dev/sr1"]["udisks_optical_property"])
        self.assertTrue(all(state == "not_run" for item in found["drives"] for state in item["operations"].values()))
        self.assertEqual(len(found["drives"]), 3)


if __name__ == "__main__":
    unittest.main()
