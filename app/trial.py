"""Shared policies for first-episode trial subscriptions."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


BULK_TRIAL_SAVE_PATH_TEMPLATE = "{base}/试看"
SINGLE_TRIAL_SAVE_PATH_TEMPLATE = "{base}/试看/{media_folder}/Season {season:02}"
SUBSCRIBED_SAVE_PATH_TEMPLATE = "{base}/{media_folder}/Season {season:02}"
TRIAL_SKIP_REASON = "试看模式只下载首个可用剧集"


def select_trial_preset(groups: Iterable[Mapping[str, Any]]) -> dict[str, Any] | None:
    """Choose a trial RSS preset with a stable subtitle-group preference."""

    candidates = [group for group in groups if isinstance(group.get("preset"), dict)]
    for preferred_name in ("ani", "lolihouse"):
        for group in candidates:
            name = str(group.get("name") or "").strip().casefold()
            if name == preferred_name:
                return dict(group["preset"])
    return dict(candidates[0]["preset"]) if candidates else None
