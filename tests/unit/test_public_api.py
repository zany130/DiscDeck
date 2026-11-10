import json
import re
import unittest
from pathlib import Path


class PublicApiTests(unittest.TestCase):
    def test_phase0_helpers_are_pinned_public_exports(self) -> None:
        root = Path(__file__).resolve().parents[2]
        exports = json.loads((root / "tests" / "fixtures" / "decky-api-1.1.3-exports.json").read_text(encoding="utf-8"))
        text = (root / "src" / "api" / "bridge.ts").read_text(encoding="utf-8")
        match = re.search(r"PHASE0_PUBLIC_HELPERS = \[([^\]]+)\]", text, re.S)
        self.assertIsNotNone(match)
        helpers = re.findall(r'"([^"]+)"', match.group(1))
        self.assertTrue(set(helpers) <= set(exports["exports"]))
        self.assertNotIn("executeInTab", helpers)
        self.assertNotIn("__DECKY_SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED_deckyLoaderAPIInit", text)


if __name__ == "__main__":
    unittest.main()
