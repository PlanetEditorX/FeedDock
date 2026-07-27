from __future__ import annotations

from dataclasses import dataclass
import os
import tempfile

from .models import FeedItem, Subscription
from .media_paths import map_downloader_path_to_local
from .runtime_config import MetadataConfig


@dataclass(frozen=True, slots=True)
class SidecarResult:
    ok: bool
    state: str
    message: str
    path: str = ""


def write_bangumi_ini(
    subscription: Subscription,
    item: FeedItem,
    config: MetadataConfig,
) -> SidecarResult:
    if not config.bangumi_ini_enabled:
        return SidecarResult(True, "skipped", "未启用 bangumi.ini")
    bangumi_id = int(subscription.bangumi_id or 0)
    if bangumi_id <= 0:
        return SidecarResult(True, "skipped", "订阅没有 Bangumi ID")
    try:
        directory = map_downloader_path_to_local(
            item.save_path,
            getattr(config, "downloader_root", config.media_local_root),
            config.media_local_root,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        return SidecarResult(False, "error", f"无法映射下载目录：{exc}")
    try:
        if (subscription.media_type or "tv") != "movie" and directory.name.casefold().startswith("season "):
            directory = directory.parent
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / "bangumi.ini"
        content = f"[Bangumi]\nid={bangumi_id}\n"
        if target.exists() and target.read_text(encoding="utf-8", errors="replace") == content:
            return SidecarResult(True, "completed", "bangumi.ini 已存在", str(target))
        descriptor, temporary = tempfile.mkstemp(prefix=".bangumi.", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return SidecarResult(True, "completed", "已生成 bangumi.ini", str(target))
    except OSError as exc:
        return SidecarResult(False, "error", f"写入 bangumi.ini 失败：{exc}")
