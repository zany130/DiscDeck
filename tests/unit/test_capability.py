import unittest

from discdeck.models import FORBIDDEN_READY, default_settings, effective_state, module_status
from discdeck.settings import load_settings
from pathlib import Path
from tempfile import TemporaryDirectory


class CapabilityPolicyTests(unittest.TestCase):
    def test_phase0_rejects_ready(self) -> None:
        with self.assertRaises(ValueError) as caught:
            module_status(
                "physical",
                enabled=True,
                capability="ready",
                reason_code=None,
                message="no",
                checked_at="2026-11-09T00:00:00+00:00",
            )
        self.assertEqual(str(caught.exception), FORBIDDEN_READY)

    def test_effective_precedence(self) -> None:
        self.assertEqual(effective_state(False, "ready", True), "disable_pending")
        self.assertEqual(effective_state(False, "untested", False), "disabled")
        self.assertEqual(effective_state(True, "untested", False), "unavailable")
        self.assertEqual(effective_state(True, "missing", False), "unavailable")
        self.assertEqual(effective_state(True, "denied", False), "unavailable")
        self.assertEqual(effective_state(True, "degraded", False), "unavailable")
        self.assertEqual(effective_state(True, "ready", True), "busy")
        self.assertEqual(effective_state(True, "ready", False), "active")

    def test_defaults_keep_launcher_and_autoplay_off(self) -> None:
        settings = default_settings()
        self.assertFalse(settings["modules"]["launch.experimental"])
        self.assertFalse(settings["modules"]["launch.autoplay"])
        self.assertEqual(settings["redumper_retries"], 0)
        self.assertIsNone(settings["output_root"])

    def test_invalid_settings_are_not_rewritten(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "settings.json"
            path.write_text("{", encoding="utf-8")
            before = path.read_bytes()
            loaded = load_settings(path)
            self.assertEqual(loaded["status"], "SETTINGS_INVALID")
            self.assertFalse(loaded["settings"]["modules"]["launch.experimental"])
            self.assertFalse(loaded["settings"]["modules"]["launch.autoplay"])
            self.assertEqual(path.read_bytes(), before)
            self.assertFalse(loaded["rewritten"])

    def test_absent_settings_are_not_created(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "settings.json"
            loaded = load_settings(path)
            self.assertEqual(loaded["status"], "absent")
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
