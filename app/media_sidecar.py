from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import tempfile

from .models import FeedItem, Subscription
from .runtime_config import MetadataConfig


@dataclass(frozen=True, slots=True)
class SidecarResult:
    ok: bool
    state: str
    message: str
    path: str = ""


def _safe_directory(path_value: str, root_value: str) -> Path | None:
    if not path_value or not root_value:
        return None
    try:
        root = Path(root_value).resolve(strict=False)
        target = Path(path_value).resolve(strict=False)
        if target != root and root not in target.parents:
            return None
        return target
    except (OSError, RuntimeError, ValueError):
        return None


def write_bangumi_ini(
    subscription: Subscription,
    item: FeedItem,
    config: MetadataConfig,
) -> SidecarResult:
    if not config.bangumi_ini_enabled:
        return SidecarResult(True, "skipped", "未启用 bangumi.ini；FeedDock 已移除内置 NFO/图片刮削")
    bangumi_id = int(subscription.bangumi_id or 0)
    if bangumi_id <= 0:
        return SidecarResult(True, "skipped", "订阅没有 Bangumi ID")
    directory = _safe_directory(item.save_path, config.media_local_root)
    if directory is None:
        return SidecarResult(False, "error", "下载目录不在允许的媒体根目录内")
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
