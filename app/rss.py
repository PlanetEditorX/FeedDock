from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Iterable

import httpx

from .config import settings
from .db import add_log, connect, transaction, utcnow_iso
from .qbittorrent import add_download, current_config


@dataclass
class FeedItem:
    title: str
    link: str = ""
    download_url: str = ""
    published_at: str = ""

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(f"{self.title}\n{self.link}\n{self.download_url}".encode()).hexdigest()


def _text(node: ET.Element | None) -> str:
    return (node.text or "").strip() if node is not None else ""


def parse_feed(content: bytes) -> list[FeedItem]:
    root = ET.fromstring(content)
    items: list[FeedItem] = []
    local = lambda tag: tag.rsplit("}", 1)[-1]
    for node in root.iter():
        if local(node.tag) not in {"item", "entry"}:
            continue
        fields: dict[str, str] = {}
        download_url = ""
        for child in list(node):
            name = local(child.tag)
            if name in {"title", "published", "updated", "pubDate", "guid"}:
                fields[name] = _text(child)
            if name == "link":
                href = child.attrib.get("href") or _text(child)
                rel = child.attrib.get("rel", "alternate")
                if rel == "enclosure" or child.attrib.get("type") == "application/x-bittorrent":
                    download_url = href
                elif not fields.get("link"):
                    fields["link"] = href
            if name == "enclosure":
                download_url = child.attrib.get("url", "")
        link = fields.get("link") or fields.get("guid", "")
        if link.startswith("magnet:"):
            download_url = link
        items.append(
            FeedItem(
                title=fields.get("title", "").strip(),
                link=link,
                download_url=download_url,
                published_at=fields.get("published") or fields.get("updated") or fields.get("pubDate", ""),
            )
        )
    return [item for item in items if item.title]


def _lines(text: str) -> list[str]:
    return [line.strip() for line in (text or "").splitlines() if line.strip() and line.strip().lower() != "无"]


def _matches_rule(title: str, rule: str) -> bool:
    try:
        return re.search(rule, title, re.I) is not None
    except re.error:
        return rule.casefold() in title.casefold()


def item_allowed(title: str, include_rules: str, exclude_rules: str, global_exclude_rules: str) -> bool:
    includes = _lines(include_rules)
    excludes = _lines(exclude_rules) + _lines(global_exclude_rules)
    if includes and not all(_matches_rule(title, rule) for rule in includes):
        return False
    return not any(_matches_rule(title, rule) for rule in excludes)


def extract_episode(title: str, pattern: str, group: int, offset: float) -> float | None:
    if not pattern:
        return None
    match = re.search(pattern, title, re.I)
    if not match:
        return None
    try:
        return float(match.group(group)) + offset
    except (ValueError, IndexError):
        return None


async def fetch_feed(url: str) -> list[FeedItem]:
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds, follow_redirects=True) as client:
        response = await client.get(url, headers={"User-Agent": "FeedDock/1.8 RSS reader"})
        response.raise_for_status()
        return parse_feed(response.content)


async def refresh_subscription(subscription_id: int) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM subscriptions WHERE id=?", (subscription_id,)).fetchone()
    if row is None:
        raise ValueError("订阅不存在")
    subscription = dict(row)
    urls = [subscription["primary_rss_url"], subscription["backup_rss_url"]]
    feed_items: list[FeedItem] = []
    source_url = ""
    errors: list[str] = []
    for url in filter(None, urls):
        try:
            feed_items = await fetch_feed(url)
            source_url = url
            break
        except Exception as exc:
            errors.append(f"{url}: {exc}")
    if not source_url:
        raise RuntimeError("；".join(errors) or "没有配置 RSS")

    allowed = [
        item for item in feed_items
        if item_allowed(
            item.title,
            subscription["include_rules"],
            subscription["exclude_rules"],
            subscription["global_exclude_rules"],
        )
    ]
    if subscription["latest_only"] and allowed:
        allowed = allowed[:1]

    created = 0
    pushed = 0
    for item in allowed:
        with transaction() as conn:
            exists = conn.execute(
                "SELECT 1 FROM rss_items WHERE subscription_id=? AND fingerprint=?",
                (subscription_id, item.fingerprint),
            ).fetchone()
            if exists:
                continue
            conn.execute(
                """
                INSERT INTO rss_items(subscription_id, fingerprint, title, link, download_url, published_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (subscription_id, item.fingerprint, item.title, item.link, item.download_url, item.published_at, utcnow_iso()),
            )
            created += 1
        if item.download_url and current_config(include_password=True).get("url"):
            try:
                await add_download(item.download_url, subscription["download_path"])
                pushed += 1
                with transaction() as conn:
                    conn.execute(
                        "UPDATE rss_items SET status='pushed' WHERE subscription_id=? AND fingerprint=?",
                        (subscription_id, item.fingerprint),
                    )
            except Exception as exc:
                with transaction() as conn:
                    conn.execute(
                        "UPDATE rss_items SET status='error', error=? WHERE subscription_id=? AND fingerprint=?",
                        (str(exc), subscription_id, item.fingerprint),
                    )
                add_log("error", "qBittorrent 推送失败", {"subscription_id": subscription_id, "error": str(exc)})

    with transaction() as conn:
        conn.execute("UPDATE subscriptions SET last_checked_at=?, updated_at=? WHERE id=?", (utcnow_iso(), utcnow_iso(), subscription_id))
    add_log("info", "订阅刷新完成", {"subscription_id": subscription_id, "source": source_url, "new": created, "pushed": pushed})
    return {"source_url": source_url, "feed_count": len(feed_items), "matched_count": len(allowed), "new_count": created, "pushed_count": pushed}


async def refresh_all() -> None:
    with connect() as conn:
        ids = [row["id"] for row in conn.execute("SELECT id FROM subscriptions WHERE enabled=1").fetchall()]
    for subscription_id in ids:
        try:
            await refresh_subscription(subscription_id)
        except Exception as exc:
            add_log("error", "订阅自动刷新失败", {"subscription_id": subscription_id, "error": str(exc)})
