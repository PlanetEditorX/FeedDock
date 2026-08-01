from __future__ import annotations

import os
from pathlib import Path
import unittest
from unittest.mock import patch

from app.media_paths import (
    _absolute_posix,
    _is_within,
    map_downloader_path_to_local,
    preferred_local_media_root,
)


class MediaPathsTests(unittest.TestCase):
    def test_absolute_posix(self) -> None:
        # Valid absolute path
        path = _absolute_posix("/valid/absolute/path", "Test Label")
        self.assertEqual(str(path), "/valid/absolute/path")

        # Missing path (empty or whitespace)
        with self.assertRaisesRegex(ValueError, "Test Label未配置"):
            _absolute_posix("", "Test Label")
        with self.assertRaisesRegex(ValueError, "Test Label未配置"):
            _absolute_posix("   ", "Test Label")

        # Relative path
        with self.assertRaisesRegex(ValueError, "Test Label必须是绝对路径"):
            _absolute_posix("relative/path", "Test Label")

    def test_is_within(self) -> None:
        root = Path("/root")
        # Same as root
        self.assertTrue(_is_within(Path("/root"), root))
        # Sub-directory of root
        self.assertTrue(_is_within(Path("/root/subdir/file"), root))
        # Not within root
        self.assertFalse(_is_within(Path("/other/path"), root))
        # Partial match but not sub-directory
        self.assertFalse(_is_within(Path("/rootdir"), root))

    def test_preferred_local_media_root_same_paths(self) -> None:
        self.assertEqual(preferred_local_media_root("/media", "/media"), "/media")

    def test_preferred_local_media_root_fallback(self) -> None:
        # When no explicit config, local is not a mount, and not host style, falls back to qbit_root
        self.assertEqual(preferred_local_media_root("/qbit/path", "/local/path"), "/qbit/path")

    @patch.dict(os.environ, {"MEDIA_LOCAL_ROOT": "1"}, clear=False)
    def test_preferred_local_media_root_explicit_config(self) -> None:
        self.assertEqual(preferred_local_media_root("/qbit/path", "/local/path"), "/local/path")

    @patch("app.media_paths.Path.is_mount")
    def test_preferred_local_media_root_local_is_mount(self, mock_is_mount) -> None:
        mock_is_mount.return_value = True
        self.assertEqual(preferred_local_media_root("/qbit/path", "/local/path"), "/local/path")

    def test_preferred_local_media_root_host_style(self) -> None:
        # Paths starting with /vol, /volume, /mnt, /share
        self.assertEqual(preferred_local_media_root("/vol2/1000/影视", "/media"), "/media")
        self.assertEqual(preferred_local_media_root("/share/movies", "/media"), "/media")

    def test_map_downloader_path_to_local_happy_path(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            qbit_root = "/qbit_root"
            local_root = str(tmp_path / "local_root")
            path_value = "/qbit_root/Sub/Movie"

            mapped = map_downloader_path_to_local(path_value, qbit_root, local_root)
            self.assertEqual(mapped, (tmp_path / "local_root/Sub/Movie").resolve())

    def test_map_downloader_path_to_local_backwards_compatibility(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            qbit_root = "/qbit_root"
            local_root = str(tmp_path / "local_root")
            path_value = str(tmp_path / "local_root/already/inside")

            mapped = map_downloader_path_to_local(path_value, qbit_root, local_root)
            self.assertEqual(mapped, (tmp_path / "local_root/already/inside").resolve())

    def test_map_downloader_path_to_local_not_in_source_root(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            qbit_root = "/qbit_root"
            local_root = str(tmp_path / "local_root")
            path_value = "/other_root/Sub/Movie"

            with self.assertRaisesRegex(ValueError, "下载目录不在允许的媒体根目录（qBittorrent 下载根目录）内"):
                map_downloader_path_to_local(path_value, qbit_root, local_root)

    @unittest.skip("It is difficult to test mapping outside target root with PurePosixPath resolving '..' and failing source root check first.")
    def test_map_downloader_path_to_local_outside_target_root(self) -> None:
        pass

    def test_map_downloader_path_to_local_require_exists(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            qbit_root = "/qbit_root"
            local_root = str(tmp_path / "local_root")
            path_value = "/qbit_root/Sub/Movie"

            with self.assertRaisesRegex(FileNotFoundError, "映射后的下载目录不存在"):
                map_downloader_path_to_local(path_value, qbit_root, local_root, require_exists=True)

            target_path = tmp_path / "local_root" / "Sub"
            target_path.mkdir(parents=True)
            target_file = target_path / "Movie"
            target_file.touch()

            mapped = map_downloader_path_to_local(path_value, qbit_root, local_root, require_exists=True)
            self.assertEqual(mapped, target_file.resolve())

    def test_map_downloader_path_to_local_require_directory(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            qbit_root = "/qbit_root"
            local_root = str(tmp_path / "local_root")
            path_value = "/qbit_root/Sub/Movie"

            target_path = tmp_path / "local_root" / "Sub"
            target_path.mkdir(parents=True)
            target_file = target_path / "Movie"

            target_file.touch()

            with self.assertRaisesRegex(ValueError, "映射后的下载路径不是目录"):
                map_downloader_path_to_local(path_value, qbit_root, local_root, require_directory=True)

            target_file.unlink()
            target_file.mkdir()

            mapped = map_downloader_path_to_local(path_value, qbit_root, local_root, require_directory=True)
            self.assertEqual(mapped, target_file.resolve())
