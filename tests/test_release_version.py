from __future__ import annotations

import importlib.util
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "release_version",
    ROOT / "scripts/release_version.py",
)
assert SPEC is not None and SPEC.loader is not None
release_version = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = release_version
SPEC.loader.exec_module(release_version)


class ReleaseVersionTests(unittest.TestCase):
    def test_next_patch_uses_latest_release_when_current_is_not_higher(self) -> None:
        self.assertEqual(
            release_version.choose_release_version("1.17.12", "v1.17.12"),
            "1.17.13",
        )
        self.assertEqual(
            release_version.choose_release_version("1.17.11", "1.17.12"),
            "1.17.13",
        )

    def test_manually_raised_version_is_respected(self) -> None:
        self.assertEqual(
            release_version.choose_release_version("1.18.0", "1.17.12"),
            "1.18.0",
        )
        self.assertEqual(
            release_version.choose_release_version("2.0.0", ""),
            "2.0.0",
        )

    def test_release_paths_include_runtime_and_deployment_but_not_docs_or_tests(self) -> None:
        patterns = release_version.load_release_patterns(ROOT / ".github/release-paths.txt")
        matched = release_version.match_release_files(
            (
                "app/main.py",
                "src/future_module.py",
                "docker-compose.yml",
                "requirements.txt",
                "docs/README.md",
                "tests/test_auth_flow.py",
            ),
            patterns,
        )
        self.assertEqual(
            matched,
            (
                "app/main.py",
                "docker-compose.yml",
                "requirements.txt",
                "src/future_module.py",
            ),
        )

    def test_sync_updates_all_runtime_visible_versions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir)
            for relative in (
                "VERSION",
                "update.json",
                "Dockerfile",
                ".env.example",
                "README.md",
                "app/config.py",
            ):
                source = ROOT / relative
                destination = target / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
            shutil.copytree(ROOT / "app/static", target / "app/static")

            release_version.sync_version(
                target,
                "9.8.7",
                published_at="2026-07-28T12:34:56Z",
            )

            self.assertEqual(release_version.validate_version_files(target), [])
            self.assertEqual((target / "VERSION").read_text(encoding="utf-8"), "9.8.7\n")
            index = (target / "app/static/index.html").read_text(encoding="utf-8")
            self.assertIn("/static/app.js?v=9.8.7", index)
            self.assertNotIn("qbit-cleanup", index)

    def test_current_repository_version_files_are_consistent(self) -> None:
        self.assertEqual(release_version.validate_version_files(ROOT), [])


if __name__ == "__main__":
    unittest.main()
