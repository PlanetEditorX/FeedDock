"""Move a downloaded trial episode into its confirmed media-library location."""

from __future__ import annotations

import posixpath
import shutil
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from .downloader import QBittorrentClient
from .media_paths import map_downloader_path_to_local
from .models import FeedItem, Subscription
from .naming import is_subtitle_file, is_video_file, render_desired_name, safe_segment
from .rss_service import render_save_path
from .runtime_config import load_metadata_config, load_qbittorrent_config


_TRIAL_DOWNLOAD_STATUSES = ("scheduled", "queued", "completed")


@dataclass(slots=True)
class TrialMigrationResult:
    found: bool
    moved: bool
    message: str
    item_id: int = 0
    source_path: str = ""
    target_path: str = ""


def _trial_item(db: Session, subscription: Subscription) -> FeedItem | None:
    return db.scalar(
        select(FeedItem)
        .where(
            FeedItem.subscription_id == subscription.id,
            FeedItem.status.in_(_TRIAL_DOWNLOAD_STATUSES),
        )
        .order_by(desc(FeedItem.completed_at), desc(FeedItem.id))
        .limit(1)
    )


def _video_candidates(directory: Path, item: FeedItem) -> list[Path]:
    videos = sorted(
        (path for path in directory.rglob("*") if path.is_file() and is_video_file(path.name)),
        key=lambda path: (len(path.parts), str(path).casefold()),
    )
    old_stem = safe_segment(item.desired_name, "") if item.desired_name else ""
    if old_stem:
        exact = [path for path in videos if path.stem == old_stem]
        if exact:
            return exact
    return videos


def _resolve_local_source(
    item: FeedItem,
    *,
    downloader_root: str,
    local_root: str,
) -> Path | None:
    recorded = str(item.trial_download_path or item.save_path or "").strip()
    if not recorded:
        return None
    mapped = map_downloader_path_to_local(recorded, downloader_root, local_root)
    if mapped.is_file():
        return mapped if is_video_file(mapped.name) else None
    if not mapped.exists() and mapped.parent.is_dir():
        candidates = _video_candidates(mapped.parent, item)
        return candidates[0] if len(candidates) == 1 else None
    if not mapped.is_dir():
        return None
    candidates = _video_candidates(mapped, item)
    return candidates[0] if len(candidates) == 1 else None


def _move_related_subtitles(source: Path, target: Path) -> int:
    moved = 0
    for candidate in list(source.parent.iterdir()):
        if not candidate.is_file() or not is_subtitle_file(candidate.name):
            continue
        if not candidate.stem.startswith(source.stem):
            continue
        suffix = candidate.stem[len(source.stem) :]
        destination = target.parent / f"{target.stem}{suffix}{candidate.suffix}"
        if destination.exists() and destination.resolve(strict=False) != candidate.resolve(strict=False):
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(candidate), str(destination))
        moved += 1
    return moved


def _remove_empty_trial_directories(start: Path, stop: Path) -> None:
    current = start
    stop = stop.resolve(strict=False)
    while current.resolve(strict=False) != stop and stop in current.resolve(strict=False).parents:
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


def promote_trial_download(
    db: Session,
    subscription: Subscription,
    *,
    client: QBittorrentClient | None = None,
) -> TrialMigrationResult:
    """Rename and relocate the downloaded trial episode after metadata confirmation.

    qBittorrent is used first while its task record still exists. If that record
    has already been cleaned up, the same operation is performed through the
    FeedDock-visible media mount. Missing files never block subscription startup.
    """

    item = _trial_item(db, subscription)
    if item is None:
        return TrialMigrationResult(False, False, "没有找到已推送的试看下载记录")

    source_record = str(item.trial_download_path or item.save_path or "").strip()
    if not item.trial_download_path:
        item.trial_download_path = source_record

    episode = str(item.episode or "1").strip() or "1"
    target_directory = render_save_path(subscription, episode, db)
    target_name = render_desired_name(subscription, episode)
    qbit_error = ""

    if item.torrent_hash and item.qbit_record_removed_at is None:
        relocation = (client or QBittorrentClient()).relocate_single_video(
            torrent_hash=item.torrent_hash,
            target_save_path=target_directory,
            desired_name=target_name,
        )
        if relocation.ok and relocation.found:
            item.save_path = target_directory
            item.desired_name = target_name
            item.rename_status = "completed" if item.completed_at is not None else "waiting_completion"
            item.rename_message = relocation.message[:2000]
            return TrialMigrationResult(
                True,
                relocation.moved,
                relocation.message,
                item.id,
                source_record,
                relocation.download_path,
            )
        if relocation.download_path:
            source_record = relocation.download_path
            item.trial_download_path = relocation.download_path
        qbit_error = relocation.message

    metadata = load_metadata_config(db)
    downloader_root = getattr(metadata, "downloader_root", "") or load_qbittorrent_config(db).download_path
    local_root = metadata.media_local_root
    try:
        source = _resolve_local_source(
            item,
            downloader_root=downloader_root,
            local_root=local_root,
        )
    except (ValueError, OSError) as exc:
        detail = f"；qBittorrent：{qbit_error}" if qbit_error else ""
        return TrialMigrationResult(
            True,
            False,
            f"试看下载路径无法映射：{exc}{detail}",
            item.id,
            source_record,
        )

    if source is None or not source.exists():
        detail = f"；qBittorrent：{qbit_error}" if qbit_error else ""
        return TrialMigrationResult(
            True,
            False,
            f"试看下载文件不存在或无法唯一识别，已保留订阅启动结果{detail}",
            item.id,
            source_record,
        )

    try:
        target_local_directory = map_downloader_path_to_local(
            target_directory,
            downloader_root,
            local_root,
        )
        target_local_directory.mkdir(parents=True, exist_ok=True)
        target = target_local_directory / f"{safe_segment(target_name)}{source.suffix}"
        if target.exists() and target.resolve(strict=False) != source.resolve(strict=False):
            return TrialMigrationResult(
                True,
                False,
                f"目标文件已存在，未覆盖：{target}",
                item.id,
                str(source),
                str(target),
            )

        original_parent = source.parent
        same_path = source.resolve(strict=False) == target.resolve(strict=False)
        subtitle_count = 0
        if not same_path:
            subtitle_count = _move_related_subtitles(source, target)
            shutil.move(str(source), str(target))
            local_root_path = Path(local_root).expanduser().resolve(strict=False)
            _remove_empty_trial_directories(original_parent, local_root_path)

        item.save_path = target_directory
        item.desired_name = target_name
        item.rename_status = "completed" if item.completed_at is not None else "waiting_completion"
        item.rename_message = (
            f"试看文件已迁移为 {target.name}"
            + (f"，并同步迁移 {subtitle_count} 个字幕" if subtitle_count else "")
        )[:2000]
        return TrialMigrationResult(
            True,
            not same_path,
            item.rename_message,
            item.id,
            str(source),
            str(target),
        )
    except (ValueError, OSError, shutil.Error) as exc:
        detail = f"；qBittorrent：{qbit_error}" if qbit_error else ""
        return TrialMigrationResult(
            True,
            False,
            f"试看文件迁移失败：{exc}{detail}",
            item.id,
            str(source),
        )
