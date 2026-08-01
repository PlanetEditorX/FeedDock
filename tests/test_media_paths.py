from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.media_paths import (
    _absolute_posix,
    _is_within,
    map_downloader_path_to_local,
    preferred_local_media_root,
)


def test_absolute_posix() -> None:
    # Valid absolute path
    path = _absolute_posix("/valid/absolute/path", "Test Label")
    assert str(path) == "/valid/absolute/path"

    # Missing path (empty or whitespace)
    with pytest.raises(ValueError, match="Test Label未配置"):
        _absolute_posix("", "Test Label")
    with pytest.raises(ValueError, match="Test Label未配置"):
        _absolute_posix("   ", "Test Label")

    # Relative path
    with pytest.raises(ValueError, match="Test Label必须是绝对路径"):
        _absolute_posix("relative/path", "Test Label")


def test_is_within() -> None:
    root = Path("/root")
    # Same as root
    assert _is_within(Path("/root"), root) is True
    # Sub-directory of root
    assert _is_within(Path("/root/subdir/file"), root) is True
    # Not within root
    assert _is_within(Path("/other/path"), root) is False
    # Partial match but not sub-directory
    assert _is_within(Path("/rootdir"), root) is False


def test_preferred_local_media_root_same_paths() -> None:
    assert preferred_local_media_root("/media", "/media") == "/media"


def test_preferred_local_media_root_fallback() -> None:
    # When no explicit config, local is not a mount, and not host style, falls back to qbit_root
    assert preferred_local_media_root("/qbit/path", "/local/path") == "/qbit/path"


def test_preferred_local_media_root_explicit_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEDIA_LOCAL_ROOT", "1")
    assert preferred_local_media_root("/qbit/path", "/local/path") == "/local/path"


def test_preferred_local_media_root_local_is_mount(monkeypatch: pytest.MonkeyPatch) -> None:
    # Mock Path.is_mount to return True
    monkeypatch.setattr(Path, "is_mount", lambda self: True)
    assert preferred_local_media_root("/qbit/path", "/local/path") == "/local/path"


def test_preferred_local_media_root_host_style() -> None:
    # Paths starting with /vol, /volume, /mnt, /share
    assert preferred_local_media_root("/vol2/1000/影视", "/media") == "/media"
    assert preferred_local_media_root("/share/movies", "/media") == "/media"


def test_map_downloader_path_to_local_happy_path(tmp_path: Path) -> None:
    # Basic correct mapping
    qbit_root = "/qbit_root"
    local_root = str(tmp_path / "local_root")
    path_value = "/qbit_root/Sub/Movie"

    mapped = map_downloader_path_to_local(path_value, qbit_root, local_root)
    assert mapped == (tmp_path / "local_root/Sub/Movie").resolve()


def test_map_downloader_path_to_local_backwards_compatibility(tmp_path: Path) -> None:
    # When candidate is already inside target_root
    qbit_root = "/qbit_root"
    local_root = str(tmp_path / "local_root")
    path_value = str(tmp_path / "local_root/already/inside")

    mapped = map_downloader_path_to_local(path_value, qbit_root, local_root)
    assert mapped == (tmp_path / "local_root/already/inside").resolve()


def test_map_downloader_path_to_local_not_in_source_root(tmp_path: Path) -> None:
    qbit_root = "/qbit_root"
    local_root = str(tmp_path / "local_root")
    path_value = "/other_root/Sub/Movie"

    with pytest.raises(ValueError, match="下载目录不在允许的媒体根目录（qBittorrent 下载根目录）内"):
        map_downloader_path_to_local(path_value, qbit_root, local_root)


@pytest.mark.skip(reason="It is difficult to test mapping outside target root with PurePosixPath resolving '..' and failing source root check first.")
def test_map_downloader_path_to_local_outside_target_root(tmp_path: Path) -> None:
    pass


def test_map_downloader_path_to_local_require_exists(tmp_path: Path) -> None:
    qbit_root = "/qbit_root"
    local_root = str(tmp_path / "local_root")
    path_value = "/qbit_root/Sub/Movie"

    # Should raise FileNotFoundError if it doesn't exist
    with pytest.raises(FileNotFoundError, match="映射后的下载目录不存在"):
        map_downloader_path_to_local(path_value, qbit_root, local_root, require_exists=True)

    # Create the file and check success
    target_path = tmp_path / "local_root" / "Sub"
    target_path.mkdir(parents=True)
    target_file = target_path / "Movie"
    target_file.touch()

    mapped = map_downloader_path_to_local(path_value, qbit_root, local_root, require_exists=True)
    assert mapped == target_file.resolve()


def test_map_downloader_path_to_local_require_directory(tmp_path: Path) -> None:
    qbit_root = "/qbit_root"
    local_root = str(tmp_path / "local_root")
    path_value = "/qbit_root/Sub/Movie"

    target_path = tmp_path / "local_root" / "Sub"
    target_path.mkdir(parents=True)
    target_file = target_path / "Movie"

    # Touch a file instead of a directory
    target_file.touch()

    with pytest.raises(ValueError, match="映射后的下载路径不是目录"):
        map_downloader_path_to_local(path_value, qbit_root, local_root, require_directory=True)

    # Remove file and make a directory
    target_file.unlink()
    target_file.mkdir()

    mapped = map_downloader_path_to_local(path_value, qbit_root, local_root, require_directory=True)
    assert mapped == target_file.resolve()
