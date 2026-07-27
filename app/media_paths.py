from __future__ import annotations

import os
import posixpath
from pathlib import Path, PurePosixPath


def _absolute_posix(value: str, label: str) -> PurePosixPath:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise ValueError(f"{label}未配置")
    normalized = posixpath.normpath(cleaned)
    path = PurePosixPath(normalized)
    if not path.is_absolute():
        raise ValueError(f"{label}必须是绝对路径")
    return path


def _is_within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def preferred_local_media_root(downloader_root: str, configured_root: str) -> str:
    """Choose the FeedDock-visible media root without breaking bare-metal use.

    Docker deployments normally mount the library at ``/media`` while
    qBittorrent may report an fnOS host path such as ``/vol2/1000/影视``.  Test
    and bare-metal installations may intentionally use the same ordinary path
    for both processes, so only prefer the configured root when it was
    explicitly supplied, is an actual mount point, or the downloader root
    clearly looks like a NAS/host path.
    """

    qbit_root = str(downloader_root or "").strip().rstrip("/") or "/"
    local_root = str(configured_root or "").strip().rstrip("/") or "/media"
    if local_root == qbit_root:
        return local_root

    explicitly_configured = bool(os.getenv("MEDIA_LOCAL_ROOT", "").strip())
    local_is_mount = Path(local_root).expanduser().is_mount()
    host_style_root = qbit_root.startswith(("/vol", "/volume", "/mnt", "/share"))
    return local_root if explicitly_configured or local_is_mount or host_style_root else qbit_root


def map_downloader_path_to_local(
    path_value: str,
    downloader_root: str,
    local_root: str,
    *,
    require_exists: bool = False,
    require_directory: bool = False,
) -> Path:
    """Map a qBittorrent-visible path to the matching FeedDock mount path.

    qBittorrent and FeedDock may mount the same host directory at different
    container paths.  For example qBittorrent can save to
    ``/vol2/1000/影视/Show`` while FeedDock sees that host directory at
    ``/media/Show``.  The relative path below the configured downloader root is
    preserved and joined to the FeedDock-local root.
    """

    downloader_path = _absolute_posix(path_value, "下载目录")
    source_root = _absolute_posix(downloader_root, "qBittorrent 下载根目录")
    target_root = Path(str(_absolute_posix(local_root, "FeedDock 本地媒体挂载目录"))).expanduser().resolve(
        strict=False
    )

    # Backwards compatibility: records created when both containers used the
    # same internal path may already contain a FeedDock-local path.
    local_candidate = Path(str(downloader_path)).expanduser().resolve(strict=False)
    if _is_within(local_candidate, target_root):
        target = local_candidate
    else:
        try:
            relative = downloader_path.relative_to(source_root)
        except ValueError as exc:
            raise ValueError(
                "下载目录不在允许的媒体根目录（qBittorrent 下载根目录）内："
                f"{downloader_path}（根目录：{source_root}）"
            ) from exc
        target = target_root.joinpath(*relative.parts).resolve(strict=False)

    if not _is_within(target, target_root):
        raise ValueError("映射后的媒体目录不在允许的 FeedDock 本地媒体根目录内")
    if require_exists and not target.exists():
        raise FileNotFoundError(
            "映射后的下载目录不存在："
            f"{target}（qBittorrent 路径：{downloader_path}；"
            f"qBittorrent 根目录：{source_root}；FeedDock 挂载根目录：{target_root}）"
        )
    if require_directory and target.exists() and not target.is_dir():
        raise ValueError(f"映射后的下载路径不是目录：{target}")
    return target
