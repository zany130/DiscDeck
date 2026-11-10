import unittest

from discdeck.errors import UnsafeCommand
from discdeck.security import assert_readonly_argv, redact_home


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
        ):
            with self.assertRaises(UnsafeCommand):
                assert_readonly_argv(argv)

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
