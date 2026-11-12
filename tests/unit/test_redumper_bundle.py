import hashlib
import io
import json
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from discdeck.redumper_bundle import (
    RedumperInstallError,
    _GuardedRedirect,
    allowed_download_url,
    extract_release_binary,
    fetch_pinned_release,
    install_latest_redumper,
    load_pin,
    parse_latest_release,
    remove_updated_copy,
    select_redumper,
)
from tests.support.fixtures import linux_x64_elf_fixture, write_managed_redumper


def _zip(tag: str, payload: bytes) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(f"redumper-{tag}-linux-x64/bin/redumper", payload)
        archive.writestr("../redumper", payload)
    return buffer.getvalue()


def _release(tag: str, digest: str) -> dict[str, object]:
    name = f"redumper-{tag}-linux-x64.zip"
    return {
        "tag_name": tag,
        "assets": [
            {
                "name": name,
                "browser_download_url": f"https://github.com/superg/redumper/releases/download/{tag}/{name}",
                "digest": f"sha256:{digest}",
            }
        ],
    }


class BytesResponse:
    def __init__(self, data: bytes) -> None:
        self.data = data

    def read(self, amount: int = -1) -> bytes:
        if amount is None or amount < 0:
            amount = len(self.data)
        chunk = self.data[:amount]
        self.data = self.data[amount:]
        return chunk

    def __enter__(self) -> "BytesResponse":
        return self

    def __exit__(self, *_args: object) -> bool:
        return False


class RedumperBundleTests(unittest.TestCase):
    def test_pin_is_the_official_b772_linux_zip(self) -> None:
        pin = load_pin()
        self.assertEqual(pin["repository"], "superg/redumper")
        self.assertEqual(pin["tag"], "b772")
        self.assertEqual(pin["build"], 772)
        self.assertEqual(pin["sha256"], "ae4b68ded3f8c604162f7db35d337d6ccab33b666b347278b975c4226d72b577")
        self.assertEqual(pin["url"], "https://github.com/superg/redumper/releases/download/b772/redumper-b772-linux-x64.zip")
        self.assertEqual(pin["member"], "redumper-b772-linux-x64/bin/redumper")

    def test_extract_keeps_only_the_linux_x64_executable(self) -> None:
        binary = linux_x64_elf_fixture()
        extracted = extract_release_binary(_zip("b780", binary), "b780")
        self.assertEqual(extracted, binary)
        with self.assertRaises(RedumperInstallError):
            extract_release_binary(_zip("b780", b"#!/bin/sh\n"), "b780")
        slipped = io.BytesIO()
        with zipfile.ZipFile(slipped, "w") as archive:
            archive.writestr("../redumper", binary)
        with self.assertRaises(RedumperInstallError):
            extract_release_binary(slipped.getvalue(), "b780")

    def test_release_address_must_be_the_official_linux_zip(self) -> None:
        tag = "b780"
        digest = "ab" * 32
        payload = _release(tag, digest)
        parsed = parse_latest_release(payload)
        self.assertEqual(parsed["build"], 780)
        self.assertEqual(parsed["url"], "https://github.com/superg/redumper/releases/download/b780/redumper-b780-linux-x64.zip")
        forged = _release(tag, digest)
        forged["assets"][0]["browser_download_url"] = "https://example.test/redumper.zip"  # type: ignore[index]
        with self.assertRaises(RedumperInstallError):
            parse_latest_release(forged)
        self.assertFalse(allowed_download_url("http://github.com/superg/redumper/releases/download/b780/redumper-b780-linux-x64.zip"))
        self.assertFalse(allowed_download_url("https://evil.example/redumper"))
        with self.assertRaises(RedumperInstallError):
            _GuardedRedirect().redirect_request(None, None, 302, "Found", {}, "https://evil.example/redumper")

    def test_pinned_fetch_requests_the_pinned_url(self) -> None:
        seen: list[str] = []

        def opener(url: str, timeout: float) -> BytesResponse:
            del timeout
            seen.append(url)
            return BytesResponse(b"not-the-release")

        with self.assertRaises(RedumperInstallError):
            fetch_pinned_release(opener=opener)
        self.assertEqual(seen, [load_pin()["url"]])

    def test_update_saves_a_newer_build_and_does_not_replace_a_newer_bundle(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            plugin = root / "plugin"
            settings = root / "settings"
            write_managed_redumper(plugin, build=772)
            (settings / "settings.json").parent.mkdir()
            (settings / "settings.json").write_text("{}\n", encoding="utf-8")
            binary = linux_x64_elf_fixture()
            blob = _zip("b780", binary)
            digest = hashlib.sha256(blob).hexdigest()
            release = json.dumps(_release("b780", digest)).encode("utf-8")
            urls: list[str] = []

            def opener(url: str, timeout: float) -> BytesResponse:
                del timeout
                urls.append(url)
                if url.endswith("/releases/latest"):
                    return BytesResponse(release)
                return BytesResponse(blob)

            environ = {"DECKY_PLUGIN_DIR": str(plugin), "DECKY_PLUGIN_SETTINGS_DIR": str(settings)}
            result = install_latest_redumper(environ, opener=opener)
            self.assertTrue(result["updated"])
            self.assertEqual(result["active_build"], 780)
            self.assertEqual(result["active_origin"], "updated")
            selected = select_redumper(environ)
            self.assertEqual(selected["origin"], "updated")
            self.assertEqual(selected["build"], 780)
            self.assertEqual(selected["bundled_build"], 772)
            self.assertTrue((settings / "settings.json").is_file())
            self.assertEqual(urls[0], "https://api.github.com/repos/superg/redumper/releases/latest")
            self.assertTrue(urls[1].endswith("/redumper-b780-linux-x64.zip"))

            write_managed_redumper(plugin, build=790)
            same = json.dumps(_release("b780", digest)).encode("utf-8")

            def latest_only(url: str, timeout: float) -> BytesResponse:
                del timeout
                self.assertTrue(url.endswith("/releases/latest"))
                return BytesResponse(same)

            kept = install_latest_redumper(environ, opener=latest_only)
            self.assertFalse(kept["updated"])
            self.assertEqual(select_redumper(environ)["build"], 790)
            self.assertEqual(select_redumper(environ)["origin"], "bundled")

    def test_hash_mismatch_does_not_write_the_update(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = root / "settings"
            settings.mkdir()
            binary = linux_x64_elf_fixture()
            blob = _zip("b780", binary)
            release = json.dumps(_release("b780", "cd" * 32)).encode("utf-8")

            def opener(url: str, timeout: float) -> BytesResponse:
                del timeout
                if url.endswith("/releases/latest"):
                    return BytesResponse(release)
                return BytesResponse(blob)

            with self.assertRaises(RedumperInstallError):
                install_latest_redumper({"DECKY_PLUGIN_SETTINGS_DIR": str(settings)}, opener=opener)
            self.assertFalse((settings / "redumper").exists())

    def test_uninstall_removes_the_optional_update_only(self) -> None:
        with TemporaryDirectory() as temporary:
            settings = Path(temporary)
            write_managed_redumper(settings, build=780, origin="updated")
            (settings / "settings.json").write_text('{"schema_version": 1}\n', encoding="utf-8")
            self.assertTrue(remove_updated_copy({"DECKY_PLUGIN_SETTINGS_DIR": str(settings)}))
            self.assertFalse((settings / "redumper").exists())
            self.assertTrue((settings / "settings.json").is_file())
            self.assertFalse(remove_updated_copy({"DECKY_PLUGIN_SETTINGS_DIR": str(settings)}))


if __name__ == "__main__":
    unittest.main()
