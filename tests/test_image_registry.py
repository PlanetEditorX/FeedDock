from __future__ import annotations

import unittest

from app.image_registry import RegistryImageClient, parse_image_reference


class ImageRegistryTests(unittest.TestCase):
    def test_parse_fully_qualified_tag_and_digest(self) -> None:
        tagged = parse_image_reference("ghcr.io/PlanetEditorX/FeedDock:latest")
        self.assertEqual(tagged.registry, "ghcr.io")
        self.assertEqual(tagged.repository, "PlanetEditorX/FeedDock")
        self.assertEqual(tagged.reference, "latest")
        self.assertEqual(tagged.display, "ghcr.io/PlanetEditorX/FeedDock:latest")

        pinned = parse_image_reference(
            "ghcr.io/planeteditorx/feeddock@sha256:0123456789abcdef"
        )
        self.assertEqual(pinned.reference, "sha256:0123456789abcdef")
        self.assertIn("@sha256:", pinned.display)

    def test_parse_docker_hub_shorthand(self) -> None:
        reference = parse_image_reference("python:3.13-slim")
        self.assertEqual(reference.registry, "registry-1.docker.io")
        self.assertEqual(reference.repository, "library/python")
        self.assertEqual(reference.reference, "3.13-slim")

    def test_select_current_platform_from_multiarch_index(self) -> None:
        client = RegistryImageClient(
            "ghcr.io/planeteditorx/feeddock:latest",
            operating_system="linux",
            architecture="amd64",
        )
        descriptor = client._select_platform_manifest(
            {
                "manifests": [
                    {
                        "digest": "sha256:attestation",
                        "platform": {"os": "unknown", "architecture": "unknown"},
                    },
                    {
                        "digest": "sha256:arm64",
                        "platform": {"os": "linux", "architecture": "arm64"},
                    },
                    {
                        "digest": "sha256:amd64",
                        "platform": {"os": "linux", "architecture": "amd64"},
                    },
                ]
            }
        )
        self.assertEqual(descriptor["digest"], "sha256:amd64")

    def test_missing_platform_is_reported(self) -> None:
        client = RegistryImageClient(
            "ghcr.io/planeteditorx/feeddock:latest",
            operating_system="linux",
            architecture="arm64",
        )
        with self.assertRaisesRegex(ValueError, "不包含 linux/arm64"):
            client._select_platform_manifest(
                {
                    "manifests": [
                        {
                            "digest": "sha256:amd64",
                            "platform": {"os": "linux", "architecture": "amd64"},
                        }
                    ]
                }
            )


if __name__ == "__main__":
    unittest.main()
