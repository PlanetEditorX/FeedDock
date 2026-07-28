from __future__ import annotations

import importlib.util
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
    def test_next_patch_uses_latest_remote_image_when_base_is_not_higher(self) -> None:
        self.assertEqual(
            release_version.choose_release_version("1.17.12", "v1.17.12"),
            "1.17.13",
        )
        self.assertEqual(
            release_version.choose_release_version("1.17.11", "1.17.12"),
            "1.17.13",
        )

    def test_manually_raised_base_version_is_respected(self) -> None:
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

    def test_base_version_validation_only_checks_semver_floor(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "VERSION").write_text("9.8.7\n", encoding="utf-8")
            self.assertEqual(release_version.validate_base_version(root), [])
            (root / "VERSION").write_text("latest\n", encoding="utf-8")
            self.assertTrue(release_version.validate_base_version(root))

    def test_current_repository_base_version_is_valid(self) -> None:
        self.assertEqual(release_version.validate_base_version(ROOT), [])
        self.assertFalse((ROOT / "update.json").exists())


if __name__ == "__main__":
    unittest.main()
