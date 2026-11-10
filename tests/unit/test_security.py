import unittest

from discdeck.errors import UnsafeCommand
from discdeck.physical import mount_argv
from discdeck.security import assert_physical_udisks_argv, assert_readonly_argv, redact_home


class SecurityTests(unittest.TestCase):
    def test_mutating_commands_are_refused(self) -> None:
        for argv in (
            ["mount", "/dev/sr0", "/mnt"],
            ["systemctl", "start", "cdemu-daemon.service"],
            ["systemctl", "--user", "restart", "cdemu-daemon.service"],
            ["modprobe", "vhba"],
            ["cdemu", "load", "0"],
            ["sudo", "redumper", "--version"],
            ["redumper", "disc", "--drive=/dev/sg1"],
            ["busctl", "--system", "--no-pager", "call", "org.freedesktop.UDisks2", "/org/freedesktop/UDisks2/block_devices/sr0", "org.freedesktop.UDisks2.Filesystem", "Mount", "a{sv}", "1", "options", "s", "ro"],
        ):
            with self.assertRaises(UnsafeCommand):
                assert_readonly_argv(argv)

    def test_physical_calls_are_read_only_mount_unmount_or_eject(self) -> None:
        assert_physical_udisks_argv(mount_argv("/org/freedesktop/UDisks2/block_devices/sr1"))
        with self.assertRaises(UnsafeCommand):
            assert_physical_udisks_argv(["eject", "/dev/sr1"])
        with self.assertRaises(UnsafeCommand):
            assert_physical_udisks_argv(mount_argv("/org/freedesktop/UDisks2/block_devices/sr1")[:-1] + ["rw"])

    def test_read_only_queries_are_allowed(self) -> None:
        assert_readonly_argv(["busctl", "--system", "--no-pager", "list"])
        assert_readonly_argv(["systemctl", "--user", "is-active", "cdemu-daemon.service"])
        assert_readonly_argv(["getfacl", "-p", "/dev/sr0"])
        assert_readonly_argv(["/usr/bin/redumper", "--version"])

    def test_home_redaction(self) -> None:
        self.assertEqual(redact_home("/home/hostuser/games", "/home/hostuser"), "$HOME/games")
        self.assertEqual(redact_home("/other", "/home/hostuser"), "/other")


if __name__ == "__main__":
    unittest.main()
