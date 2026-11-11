import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from discdeck.adapters.devices import enumerate_optical
from tests.support.fixtures import write_host_sysfs


class DeviceEnumerationTests(unittest.TestCase):
    def test_shared_bridge_keeps_distinct_luns_and_ignores_unlinked_sg(self) -> None:
        with TemporaryDirectory() as temporary:
            sysfs = write_host_sysfs(Path(temporary))
            found = enumerate_optical(sysfs, "epoch-a")
            by_node = {drive["block_node"]: drive for drive in found["drives"]}
            self.assertEqual(set(by_node), {"/dev/sr0", "/dev/sr1", "/dev/sr2"})
            self.assertEqual(by_node["/dev/sr0"]["generic_scsi_node"], "/dev/sg1")
            self.assertEqual(by_node["/dev/sr1"]["generic_scsi_node"], "/dev/sg2")
            self.assertEqual(by_node["/dev/sr2"]["generic_scsi_node"], "/dev/sg3")
            self.assertEqual(by_node["/dev/sr1"]["scsi_address"], "7:0:0:0")
            self.assertEqual(by_node["/dev/sr2"]["scsi_address"], "7:0:0:1")
            self.assertEqual(by_node["/dev/sr1"]["usb_id"], "152d:2338")
            self.assertTrue(by_node["/dev/sr1"]["shared_bridge"])
            self.assertTrue(by_node["/dev/sr2"]["shared_bridge"])
            self.assertFalse(by_node["/dev/sr0"]["shared_bridge"])
            self.assertNotEqual(by_node["/dev/sr1"]["drive_id"], by_node["/dev/sr2"]["drive_id"])
            self.assertEqual(found["ignored_generic_nodes"], ["/dev/sg0"])
            self.assertNotIn("/dev/sg0", {drive["generic_scsi_node"] for drive in found["drives"]})
            self.assertTrue(all(drive["optical"] for drive in found["drives"]))
            self.assertTrue(all(drive["hardware_validated"] is False for drive in found["drives"]))

    def test_identity_follows_sysfs_device_not_sr_name(self) -> None:
        with TemporaryDirectory() as temporary:
            sysfs = write_host_sysfs(Path(temporary))
            original = enumerate_optical(sysfs, "epoch-a")
            plextor = next(drive for drive in original["drives"] if drive["model"] == "CD-R PX-W4012A")
            link = sysfs / "class" / "block" / "sr2" / "device"
            target = os.readlink(link)
            renamed = sysfs / "class" / "block" / "sr9" / "device"
            renamed.parent.mkdir()
            renamed.symlink_to(target, target_is_directory=True)
            link.unlink()
            (sysfs / "class" / "block" / "sr2").rmdir()
            again = enumerate_optical(sysfs, "epoch-a")
            moved = next(drive for drive in again["drives"] if drive["model"] == "CD-R PX-W4012A")
            self.assertEqual(moved["block_node"], "/dev/sr9")
            self.assertEqual(moved["drive_id"], plextor["drive_id"])
            self.assertEqual(moved["generic_scsi_node"], "/dev/sg3")

    def test_missing_sysfs_is_not_ready(self) -> None:
        with TemporaryDirectory() as temporary:
            found = enumerate_optical(Path(temporary) / "sys", "epoch-a")
            self.assertEqual(found["status"], "missing")
            self.assertEqual(found["drives"], [])
            self.assertFalse(found["hardware_validated"])


if __name__ == "__main__":
    unittest.main()
