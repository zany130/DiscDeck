import json
import sys
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import package_plugin  # noqa: E402
import publish_plan  # noqa: E402
import verify_zip  # noqa: E402


class PackagingTests(unittest.TestCase):
    def test_zip_matches_decky_layout_and_does_not_claim_validation(self) -> None:
        with TemporaryDirectory() as temporary:
            source = Path(temporary) / "source"
            (source / "dist").mkdir(parents=True)
            (source / "dist" / "index.js").write_text("export {}\n", encoding="utf-8")
            module = source / "py_modules" / "discdeck"
            module.mkdir(parents=True)
            (module / "__init__.py").write_text("", encoding="utf-8")
            (module / "build_info.json").write_text("{}\n", encoding="utf-8")
            (source / "main.py").write_text("class Plugin: pass\n", encoding="utf-8")
            (source / "package.json").write_text('{"name":"discdeck","version":"0.0.1"}\n', encoding="utf-8")
            (source / "plugin.json").write_text(
                '{"name":"DiscDeck","author":"zany130","flags":["debug"],"api_version":1}\n',
                encoding="utf-8",
            )
            (source / "LICENSE").write_text("BSD\n", encoding="utf-8")
            (source / "README.md").write_text("# DiscDeck\n", encoding="utf-8")
            (source / "defaults" / "note.txt").parent.mkdir()
            (source / "defaults" / "note.txt").write_text("note\n", encoding="utf-8")
            stage = Path(temporary) / "stage"
            package_plugin.stage_plugin(source, stage, "abcdef1234567890")
            destination = Path(temporary) / "DiscDeck-phase0-dev-abcdef1.zip"
            package_plugin.write_zip(stage, destination, "DiscDeck")
            self.assertEqual(verify_zip.verify_zip(destination), [])
            with zipfile.ZipFile(destination) as archive:
                names = set(archive.namelist())
                self.assertIn("DiscDeck/note.txt", names)
                self.assertNotIn("DiscDeck/defaults/note.txt", names)
                info = json.loads(archive.read("DiscDeck/py_modules/discdeck/build_info.json"))
            self.assertEqual(info["commit"], "abcdef1234567890")
            self.assertEqual(info["version"], "0.0.1")
            self.assertFalse(info["hardware_validated"])

    def test_root_flag_fails_verification(self) -> None:
        with TemporaryDirectory() as temporary:
            source = Path(temporary) / "source"
            self._minimum(source, flags=["root"])
            stage = Path(temporary) / "stage"
            package_plugin.stage_plugin(source, stage, None)
            destination = Path(temporary) / "bad.zip"
            package_plugin.write_zip(stage, destination, "DiscDeck")
            errors = verify_zip.verify_zip(destination)
            self.assertTrue(any("root" in error for error in errors))

    def test_development_plan_does_not_touch_stable(self) -> None:
        plan = publish_plan.plan_publish("development", "r2", "abcdef1234567890")
        publish_plan.assert_development_isolation(plan)
        self.assertEqual(plan["steps"][0], "verify-local-zip")
        self.assertLess(plan["steps"].index("upload-unique-object"), plan["steps"].index("write-channel-pointer"))
        self.assertEqual(publish_plan.select_mode("auto", r2_ready=False, repo_public=True), "github-release")
        self.assertEqual(publish_plan.select_mode("auto", r2_ready=True, repo_public=True), "r2")
        self.assertEqual(publish_plan.select_mode("github-release", r2_ready=False, repo_public=False), "refuse-private")
        stable = publish_plan.plan_publish("stable", "github-release", "abcdef1234567890")
        self.assertTrue(stable["unique_key"].startswith("stable/"))
        self.assertNotEqual(stable["release_tag"], plan["release_tag"])

    def test_publish_commands_move_the_pointer_after_the_unique_object(self) -> None:
        import publish_dev

        with TemporaryDirectory() as temporary:
            zip_path = Path(temporary) / "DiscDeck-phase0-dev-abcdef1.zip"
            zip_path.write_bytes(b"PK\x03\x04fixture")
            plan = publish_plan.plan_publish("development", "github-release", "abcdef1234567890")
            work = Path(temporary) / "work"
            publish_dev.prepare_work(plan, zip_path, work)
            commands = publish_dev.github_commands(plan, zip_path, {"PUBLISH_WORK": str(work), "GITHUB_REPOSITORY": "zany130/DiscDeck"})
            joined = [" ".join(command) for command in commands]
            unique_upload = next(index for index, command in enumerate(joined) if "DiscDeck-phase0-dev-abcdef1.zip" in command and " upload " in f" {command} ")
            canonical_upload = next(index for index, command in enumerate(joined) if "/DiscDeck.zip " in command or command.endswith("/DiscDeck.zip"))
            self.assertLess(unique_upload, canonical_upload)
            self.assertIn("metadata.json", joined[-1])
            self.assertGreater(len(joined) - 1, canonical_upload)
            pointer = json.loads((work / "latest.json").read_text(encoding="utf-8"))
            self.assertFalse(pointer["hardware_validated"])
            self.assertTrue(pointer["object_key"].startswith("dev/builds/"))

    def test_actions_token_is_passed_to_gh(self) -> None:
        import publish_dev

        env = publish_dev.github_cli_env({"GITHUB_TOKEN": "ghs_test", "PATH": "/usr/bin"})
        self.assertEqual(env["GH_TOKEN"], "ghs_test")
        explicit = publish_dev.github_cli_env({"GH_TOKEN": "explicit", "GITHUB_TOKEN": "other"})
        self.assertEqual(explicit["GH_TOKEN"], "explicit")

    def test_missing_release_is_created_and_auth_failure_is_not(self) -> None:
        import publish_dev

        view = ["gh", "release", "view", "discdeck-dev", "--repo", "zany130/DiscDeck"]
        with patch("publish_dev.subprocess.run", return_value=SimpleNamespace(returncode=4)) as run:
            self.assertEqual(publish_dev.default_runner(view), 4)
            self.assertEqual(run.call_count, 1)
        with patch(
            "publish_dev.subprocess.run",
            side_effect=[SimpleNamespace(returncode=1), SimpleNamespace(returncode=0)],
        ) as run:
            self.assertEqual(publish_dev.default_runner(view), 0)
            self.assertEqual(run.call_args_list[1].args[0][2], "create")

    def _minimum(self, source: Path, flags: list[str]) -> None:
        (source / "dist").mkdir(parents=True)
        (source / "dist" / "index.js").write_text("export {}\n", encoding="utf-8")
        module = source / "py_modules" / "discdeck"
        module.mkdir(parents=True)
        (module / "__init__.py").write_text("", encoding="utf-8")
        (module / "build_info.json").write_text('{"hardware_validated": false, "phase": "0"}\n', encoding="utf-8")
        (source / "main.py").write_text("class Plugin: pass\n", encoding="utf-8")
        (source / "package.json").write_text("{}\n", encoding="utf-8")
        (source / "plugin.json").write_text(json.dumps({"name": "DiscDeck", "flags": flags}), encoding="utf-8")
        (source / "LICENSE").write_text("BSD\n", encoding="utf-8")
        (source / "README.md").write_text("# DiscDeck\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
