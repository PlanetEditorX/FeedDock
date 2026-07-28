from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.build_info import load_build_info


class BuildInfoTests(unittest.TestCase):
    def test_image_file_takes_precedence_over_stale_container_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / 'build.json'
            path.write_text(
                json.dumps(
                    {
                        'version': '1.17.15',
                        'revision': 'new-revision',
                        'created_at': '2026-07-28T03:00:00Z',
                    }
                ),
                encoding='utf-8',
            )
            with patch.dict(
                os.environ,
                {
                    'FEEDDOCK_BUILD_INFO_FILE': str(path),
                    'APP_VERSION': '1.17.12',
                    'APP_REVISION': 'old-revision',
                },
                clear=False,
            ):
                info = load_build_info()

        self.assertEqual(info.version, '1.17.15')
        self.assertEqual(info.revision, 'new-revision')
        self.assertTrue(info.source.startswith('image-file:'))

    def test_unexpanded_docker_build_arguments_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / 'build.json'
            path.write_text(
                json.dumps(
                    {
                        'version': '${APP_VERSION}',
                        'revision': '${APP_REVISION}',
                        'created_at': '${APP_CREATED_AT}',
                    }
                ),
                encoding='utf-8',
            )
            with patch.dict(
                os.environ,
                {
                    'FEEDDOCK_BUILD_INFO_FILE': str(path),
                    'APP_VERSION': 'fallback-version',
                    'APP_REVISION': 'fallback-revision',
                },
                clear=False,
            ):
                info = load_build_info()

        self.assertEqual(info.version, 'fallback-version')
        self.assertEqual(info.revision, 'fallback-revision')
        self.assertEqual(info.source, 'environment')

    def test_environment_is_used_for_source_checkout_without_image_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            missing = Path(tmpdir) / 'missing.json'
            with patch.dict(
                os.environ,
                {
                    'FEEDDOCK_BUILD_INFO_FILE': str(missing),
                    'APP_VERSION': 'dev-test',
                    'APP_REVISION': 'test-revision',
                },
                clear=False,
            ):
                info = load_build_info()

        self.assertEqual(info.version, 'dev-test')
        self.assertEqual(info.revision, 'test-revision')
        self.assertEqual(info.source, 'environment')


if __name__ == '__main__':
    unittest.main()
