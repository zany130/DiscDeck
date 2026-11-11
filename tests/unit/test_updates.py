import json
import unittest

from discdeck.updates import METADATA_URL, UpdateError, check_development_update

LOCAL = "a" * 40
REMOTE = "b" * 40


class Body:
    def __init__(self, payload: dict[str, object] | str) -> None:
        self.raw = payload if isinstance(payload, str) else json.dumps(payload)

    def read(self, size: int) -> bytes:
        return self.raw.encode()[:size]

    def __enter__(self) -> "Body":
        return self

    def __exit__(self, *args: object) -> bool:
        return False


def _release(commit: str, version: str | None = "0.2.1") -> dict[str, object]:
    body: dict[str, object] = {
        "channel": "development",
        "plugin": "DiscDeck",
        "commit": commit,
        "object_key": f"dev/builds/{commit}/DiscDeck-phase0-dev-{commit[:7]}.zip",
        "zip_sha256": "ab" * 32,
        "hardware_validated": False,
    }
    if version is not None:
        body["version"] = version
    return body


class UpdateCheckTests(unittest.TestCase):
    def test_same_commit_is_current(self) -> None:
        def opener(url: str, timeout: float) -> Body:
            self.assertEqual(url, METADATA_URL)
            self.assertGreater(timeout, 0)
            return Body(_release(LOCAL, "0.2.0"))

        result = check_development_update("0.2.0", LOCAL, opener=opener)
        self.assertTrue(result["up_to_date"])
        self.assertIsNone(result["artifact_url"])
        self.assertEqual(result["current_version"], "0.2.0")
        self.assertFalse(result["hardware_validated"])

    def test_different_commit_offers_the_named_development_zip(self) -> None:
        result = check_development_update("0.2.0", LOCAL, opener=lambda url, timeout: Body(_release(REMOTE)))
        self.assertFalse(result["up_to_date"])
        self.assertEqual(result["remote_version"], "0.2.1")
        self.assertEqual(
            result["artifact_url"],
            f"https://github.com/zany130/DiscDeck/releases/download/discdeck-dev/DiscDeck-phase0-dev-{REMOTE[:7]}.zip",
        )
        self.assertEqual(result["zip_sha256"], "ab" * 32)

    def test_object_name_and_channel_must_match_the_commit(self) -> None:
        bad = _release(REMOTE)
        bad["object_key"] = "dev/builds/other/DiscDeck.zip"
        with self.assertRaises(UpdateError):
            check_development_update("0.2.0", LOCAL, opener=lambda url, timeout: Body(bad))
        stable = _release(REMOTE)
        stable["channel"] = "stable"
        with self.assertRaises(UpdateError):
            check_development_update("0.2.0", LOCAL, opener=lambda url, timeout: Body(stable))

    def test_unread_metadata_stays_an_error(self) -> None:
        def opener(url: str, timeout: float) -> Body:
            raise TimeoutError("timed out")

        with self.assertRaises(UpdateError) as caught:
            check_development_update("0.2.0", LOCAL, opener=opener)
        self.assertIn("could not be read", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
