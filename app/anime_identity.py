from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import defaultdict
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlsplit

from .models import AnimePreference, Subscription
from .subscription_sources import classify_subscription_source, get_subscription_source

_TITLE_SEPARATORS = re.compile(r"[\s\-‐‑‒–—―_:：·・~～!！?？,，.。/\\|()（）\[\]【】{}]+")


def normalize_title(value: str | None) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold().strip()
    return _TITLE_SEPARATORS.sub("", text)


def title_key(value: str | None) -> str:
    normalized = normalize_title(value)
    if not normalized:
        return ""
    return "title:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]


def parse_bangumi_subject_id(url: str | None) -> int:
    match = re.search(r"/(?:subject|anime)/(\d+)(?:/|$)", str(url or ""), re.IGNORECASE)
    if not match:
        return 0
    try:
        return int(match.group(1))
    except ValueError:
        return 0


def source_anime_id_from_url(source_type: str, url: str | None) -> str:
    try:
        query = parse_qsl(urlsplit(str(url or "")).query, keep_blank_values=False)
    except ValueError:
        return ""
    wanted = {
        "mikan": {"bangumiid"},
        "anibt": {"bgmid", "bangumiid"},
        "ag": {"subject"},
    }.get(source_type, set())
    for key, value in query:
        if key.casefold() in wanted and str(value).strip():
            return str(value).strip()
    return ""


def _subscription_real_bangumi_id(subscription: Subscription) -> int:
    from_url = parse_bangumi_subject_id(subscription.bgm_url)
    if from_url > 0:
        return from_url
    source_type = subscription.source_type or classify_subscription_source(subscription.rss_url)
    if source_type in {"anibt", "ag"} and int(subscription.bangumi_id or 0) > 0:
        return int(subscription.bangumi_id)
    return 0


def subscription_aliases(subscription: Subscription) -> set[str]:
    values = {
        subscription.name,
        subscription.reference_title,
        subscription.manual_title,
        subscription.tmdb_title,
    }
    return {normalized for value in values if (normalized := normalize_title(value))}


def subscription_identity(subscription: Subscription) -> str:
    if str(subscription.canonical_key or "").strip():
        return str(subscription.canonical_key).strip()
    bangumi_id = _subscription_real_bangumi_id(subscription)
    if bangumi_id > 0:
        return f"bgm:{bangumi_id}"
    aliases = subscription_aliases(subscription)
    if aliases:
        return "title:" + hashlib.sha256(sorted(aliases)[0].encode("utf-8")).hexdigest()[:24]
    return ""


def subscriptions_related(left: Subscription, right: Subscription) -> bool:
    """Return whether two subscription rows represent the same anime.

    Deletion uses this broader relation so duplicate RSS groups and cross-source
    records do not survive after the user removes an anime.
    """

    if left.id is not None and right.id is not None and left.id == right.id:
        return True

    left_key = subscription_identity(left)
    right_key = subscription_identity(right)
    if left_key and right_key and left_key == right_key:
        return True

    left_bangumi_id = _subscription_real_bangumi_id(left)
    right_bangumi_id = _subscription_real_bangumi_id(right)
    if left_bangumi_id > 0 and left_bangumi_id == right_bangumi_id:
        return True

    left_source = (left.source_type or classify_subscription_source(left.rss_url)).strip().lower()
    right_source = (right.source_type or classify_subscription_source(right.rss_url)).strip().lower()
    left_source_id = str(left.source_anime_id or source_anime_id_from_url(left_source, left.rss_url)).strip()
    right_source_id = str(right.source_anime_id or source_anime_id_from_url(right_source, right.rss_url)).strip()
    if left_source and left_source == right_source and left_source_id and left_source_id == right_source_id:
        return True

    left_aliases = subscription_aliases(left)
    right_aliases = subscription_aliases(right)
    return bool(left_aliases and right_aliases and not left_aliases.isdisjoint(right_aliases))


def item_aliases(item: dict[str, Any]) -> set[str]:
    values: list[str] = []
    for key in ("title", "title_original", "title_english", "name"):
        value = str(item.get(key, "") or "").strip()
        if value:
            values.append(value)
    for value in item.get("aliases") or []:
        value = str(value or "").strip()
        if value:
            values.append(value)
    return {normalized for value in values if (normalized := normalize_title(value))}


def item_identity(item: dict[str, Any]) -> str:
    for key in ("subject_id", "bangumi_subject_id"):
        try:
            value = int(item.get(key) or 0)
        except (TypeError, ValueError):
            value = 0
        if value > 0:
            return f"bgm:{value}"
    aliases = item_aliases(item)
    if aliases:
        return "title:" + hashlib.sha256(sorted(aliases)[0].encode("utf-8")).hexdigest()[:24]
    return ""


def prepare_subscription_identity(values: dict[str, Any], existing: Subscription | None = None) -> dict[str, Any]:
    rss_url_was_updated = "rss_url" in values
    rss_url = str(values.get("rss_url") or (existing.rss_url if existing else "") or "")
    source_type = str(values.get("source_type") or (existing.source_type if existing else "") or "").strip().lower()
    detected_source_type = classify_subscription_source(rss_url)
    if rss_url_was_updated and existing and rss_url != existing.rss_url:
        if not source_type or source_type == (existing.source_type or ""):
            source_type = detected_source_type
    if not source_type or source_type not in {"mikan", "anibt", "ag", "other"}:
        source_type = detected_source_type
    values["source_type"] = source_type

    source_anime_id_was_updated = "source_anime_id" in values
    source_anime_id = str(values.get("source_anime_id") or (existing.source_anime_id if existing else "") or "").strip()
    if rss_url_was_updated and existing and rss_url != existing.rss_url and not source_anime_id_was_updated:
        source_anime_id = source_anime_id_from_url(source_type, rss_url)
    elif not source_anime_id:
        source_anime_id = source_anime_id_from_url(source_type, rss_url)
    values["source_anime_id"] = source_anime_id

    bangumi_id = int(values.get("bangumi_id") or (existing.bangumi_id if existing else 0) or 0)
    bgm_url = str(values.get("bgm_url") or (existing.bgm_url if existing else "") or "")
    real_bangumi_id = parse_bangumi_subject_id(bgm_url)
    if not real_bangumi_id and source_type in {"anibt", "ag"}:
        if bangumi_id <= 0 and source_anime_id.isdigit():
            bangumi_id = int(source_anime_id)
            values["bangumi_id"] = bangumi_id
        real_bangumi_id = bangumi_id

    canonical_key = str(values.get("canonical_key") or "").strip()
    if real_bangumi_id > 0:
        canonical_key = f"bgm:{real_bangumi_id}"
    elif not canonical_key or canonical_key.startswith("bgm:"):
        title = (
            values.get("reference_title")
            or values.get("manual_title")
            or values.get("name")
            or (existing.reference_title if existing else "")
            or (existing.name if existing else "")
        )
        canonical_key = title_key(str(title or ""))
    values["canonical_key"] = canonical_key
    return values


def build_subscription_index(subscriptions: Iterable[Subscription]) -> tuple[dict[str, list[dict[str, Any]]], list[tuple[set[str], dict[str, Any]]]]:
    by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    aliases: list[tuple[set[str], dict[str, Any]]] = []
    for subscription in subscriptions:
        source_type = subscription.source_type or classify_subscription_source(subscription.rss_url)
        source = get_subscription_source(source_type)
        record = {
            "subscription_id": subscription.id,
            "source_type": source_type,
            "source_label": source.label,
            "subscription_mode": subscription.subscription_mode,
            "enabled": bool(subscription.enabled),
            "source_anime_id": subscription.source_anime_id or source_anime_id_from_url(source_type, subscription.rss_url),
        }
        key = subscription_identity(subscription)
        if key:
            by_key[key].append(record)
        if record["source_anime_id"]:
            by_key[f"source:{source_type}:{record['source_anime_id']}"].append(record)
        normalized_aliases = subscription_aliases(subscription)
        if normalized_aliases:
            aliases.append((normalized_aliases, record))
    return dict(by_key), aliases


def matching_subscriptions(
    item: dict[str, Any],
    subscription_index: dict[str, list[dict[str, Any]]],
    alias_index: list[tuple[set[str], dict[str, Any]]],
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    seen: set[int] = set()
    key = item_identity(item)
    candidate_keys = [key] if key else []
    source_type = str(item.get("source_type") or item.get("source") or "").strip().lower()
    source_anime_id = str(item.get("source_anime_id") or "").strip()
    if source_type and source_anime_id:
        candidate_keys.append(f"source:{source_type}:{source_anime_id}")
    for candidate_key in candidate_keys:
        for record in subscription_index.get(candidate_key, []):
            if record["subscription_id"] not in seen:
                matches.append(record)
                seen.add(record["subscription_id"])

    aliases = item_aliases(item)
    if aliases:
        for candidate_aliases, record in alias_index:
            if aliases.isdisjoint(candidate_aliases):
                continue
            if record["subscription_id"] in seen:
                continue
            matches.append(record)
            seen.add(record["subscription_id"])
    return matches


def hidden_for_item(item: dict[str, Any], preferences: Iterable[AnimePreference]) -> bool:
    key = item_identity(item)
    aliases = item_aliases(item)
    subject_id = 0
    if key.startswith("bgm:"):
        try:
            subject_id = int(key.split(":", 1)[1])
        except ValueError:
            subject_id = 0
    for preference in preferences:
        if not preference.hidden:
            continue
        if key and preference.canonical_key == key:
            return True
        if subject_id and preference.bangumi_id == subject_id:
            return True
        if preference.title_normalized and preference.title_normalized in aliases:
            return True
    return False


def decorate_item(
    item: dict[str, Any],
    *,
    current_source: str,
    subscription_index: dict[str, list[dict[str, Any]]],
    alias_index: list[tuple[set[str], dict[str, Any]]],
    preferences: Iterable[AnimePreference],
) -> dict[str, Any]:
    result = dict(item)
    key = item_identity(result)
    matches = matching_subscriptions(result, subscription_index, alias_index)
    subscribed_matches = [record for record in matches if record.get("subscription_mode") != "trial"]
    trial_matches = [record for record in matches if record.get("subscription_mode") == "trial"]
    source_labels: list[str] = []
    for record in subscribed_matches:
        if record["source_label"] not in source_labels:
            source_labels.append(record["source_label"])
    subscribed_here = any(record["source_type"] == current_source for record in subscribed_matches)
    result["canonical_key"] = key
    result["subscriptions"] = matches
    result["subscribed"] = bool(subscribed_matches)
    result["trialed"] = bool(trial_matches) and not bool(subscribed_matches)
    result["subscribed_here"] = subscribed_here
    result["subscribed_sources"] = source_labels
    if result["trialed"]:
        result["subscription_badge"] = "已试看"
    elif subscribed_here:
        other_sources = [label for label in source_labels if label != get_subscription_source(current_source).label]
        result["subscription_badge"] = "✓ 已订阅" + (f" · {'、'.join(other_sources)} 也已订阅" if other_sources else "")
    else:
        result["subscription_badge"] = f"{'、'.join(source_labels)} 已订阅" if source_labels else ""
    result["hidden"] = hidden_for_item(result, preferences)
    return result


def backfill_subscription_identities(db) -> int:
    from sqlalchemy import select

    changed = 0
    for subscription in db.scalars(select(Subscription)).all():
        values: dict[str, Any] = {
            "source_type": subscription.source_type,
            "source_anime_id": subscription.source_anime_id,
            "canonical_key": subscription.canonical_key,
            "rss_url": subscription.rss_url,
            "name": subscription.name,
            "reference_title": subscription.reference_title,
            "manual_title": subscription.manual_title,
            "bgm_url": subscription.bgm_url,
            "bangumi_id": subscription.bangumi_id,
        }
        prepare_subscription_identity(values, existing=subscription)
        for field in ("source_type", "source_anime_id", "canonical_key", "bangumi_id"):
            value = int(values.get(field) or 0) if field == "bangumi_id" else str(values.get(field) or "")
            if getattr(subscription, field) != value:
                setattr(subscription, field, value)
                changed += 1
    if changed:
        db.commit()
    return changed
