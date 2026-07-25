from __future__ import annotations

import hashlib
import html
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup, Tag

from .config import settings
from .db import connect, transaction
from .runtime_config import hidden_id_set

SEASONS = {"winter", "spring", "summer", "fall"}
WEEKDAY_NAMES = {
    1: "星期一",
    2: "星期二",
    3: "星期三",
    4: "星期四",
    5: "星期五",
    6: "星期六",
    7: "星期日",
    0: "其他",
}
CACHE_SCHEMA_VERSION = 5


class MikanError(RuntimeError):
    pass


def normalize_season(value: str) -> str:
    aliases = {
        "1": "winter", "winter": "winter", "冬": "winter", "冬季": "winter",
        "2": "spring", "spring": "spring", "春": "spring", "春季": "spring",
        "3": "summer", "summer": "summer", "夏": "summer", "夏季": "summer",
        "4": "fall", "fall": "fall", "autumn": "fall", "秋": "fall", "秋季": "fall",
    }
    normalized = aliases.get(str(value).strip().lower())
    if not normalized:
        raise ValueError("不支持的季度")
    return normalized


def cache_key(year: int, season: str) -> str:
    return f"catalog:{year}:{normalize_season(season)}"


def catalog_endpoint(base_url: str, year: int, season: str) -> str:
    query = urlencode({"year": year, "seasonStr": normalize_season(season)})
    return f"{base_url}/Home/BangumiCoverFlowByDayOfWeek?{query}"


def _attr_text(tag: Tag | None, *names: str) -> str:
    if tag is None:
        return ""
    for name in names:
        value = tag.get(name)
        if isinstance(value, list):
            value = value[0] if value else ""
        if value is not None:
            text = html.unescape(str(value)).strip()
            if text:
                return text
    return ""


def _bangumi_id_from_href(href: str) -> int | None:
    match = re.search(r"/Home/Bangumi/(\d+)", href or "", re.I)
    return int(match.group(1)) if match else None


def _cover_from_card(card: Tag, response_url: str) -> str:
    image = card.find("img")
    if image is None:
        return ""
    raw = _attr_text(image, "data-src", "data-original", "data-lazy-src", "src")
    if not raw:
        srcset = _attr_text(image, "data-srcset", "srcset")
        if srcset:
            raw = srcset.split(",")[0].strip().split(" ")[0]
    if not raw or raw.startswith("data:"):
        return ""
    return urljoin(response_url, raw)


def _title_from_card(card: Tag, anchor: Tag | None = None) -> str:
    anchor = anchor or card.find("a", href=re.compile(r"/Home/Bangumi/\d+", re.I))
    image = card.find("img")
    for text in (
        _attr_text(anchor, "title"),
        _attr_text(image, "alt"),
        (card.select_one(".small-title") or card.select_one(".ellipsis") or card).get_text(" ", strip=True),
    ):
        text = html.unescape(text or "").strip()
        if text:
            return text
    return ""


def _weekday_from_block(block: Tag, fallback: int) -> int:
    for name in ("data-dayofweek", "data-day-of-week", "data-weekday", "dayofweek"):
        value = _attr_text(block, name)
        if value:
            match = re.search(r"\d+", value)
            if match:
                number = int(match.group())
                if 0 <= number <= 7:
                    return number
    classes = " ".join(block.get("class") or [])
    match = re.search(r"(?:day|week)[-_]?(\d+)", classes, re.I)
    if match:
        return int(match.group(1))
    heading = block.find(["h2", "h3", "h4", "strong", "span"])
    heading_text = heading.get_text(" ", strip=True) if heading else ""
    chinese = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "日": 7, "天": 7}
    match = re.search(r"星期([一二三四五六日天])", heading_text)
    if match:
        return chinese[match.group(1)]
    return fallback if 1 <= fallback <= 7 else 0


def _update_text(card: Tag) -> str:
    text = card.get_text(" ", strip=True)
    match = re.search(r"\d{4}/\d{1,2}/\d{1,2}\s*更新", text)
    return match.group(0) if match else ""


def parse_catalog_html(content: str, response_url: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(content, "html.parser")
    merged: dict[int, dict[str, Any]] = {}

    # First scan the entire document. Mikan may render title/update rows and image cards
    # in separate regions; covers are therefore collected globally and merged by ID.
    global_cards: dict[int, dict[str, str]] = {}
    for anchor in soup.find_all("a", href=re.compile(r"/Home/Bangumi/\d+", re.I)):
        href = _attr_text(anchor, "href")
        bangumi_id = _bangumi_id_from_href(href)
        if bangumi_id is None:
            continue
        card = anchor.find_parent(class_=re.compile(r"m-week-square|sk-bangumi|detail", re.I)) or anchor.parent
        if not isinstance(card, Tag):
            card = anchor
        info = global_cards.setdefault(bangumi_id, {"title": "", "cover_url": "", "update_at": ""})
        info["title"] = info["title"] or _title_from_card(card, anchor)
        info["cover_url"] = info["cover_url"] or _cover_from_card(card, response_url)
        info["update_at"] = info["update_at"] or _update_text(card)

    weekday_blocks = soup.select("div.sk-bangumi")
    for block_index, block in enumerate(weekday_blocks, start=1):
        weekday = _weekday_from_block(block, block_index)
        anchors = block.find_all("a", href=re.compile(r"/Home/Bangumi/\d+", re.I))
        for anchor in anchors:
            href = _attr_text(anchor, "href")
            bangumi_id = _bangumi_id_from_href(href)
            if bangumi_id is None:
                continue
            card = anchor.find_parent(["li", "div"]) or anchor
            global_info = global_cards.get(bangumi_id, {})
            existing = merged.setdefault(
                bangumi_id,
                {
                    "bangumi_id": bangumi_id,
                    "weekday": weekday,
                    "title": "",
                    "update_at": "",
                    "cover_url": "",
                    "base_url": f"{urlparse(response_url).scheme}://{urlparse(response_url).netloc}",
                },
            )
            if existing["weekday"] == 0 and weekday:
                existing["weekday"] = weekday
            existing["title"] = existing["title"] or _title_from_card(card, anchor) or global_info.get("title", "")
            existing["update_at"] = existing["update_at"] or _update_text(card) or global_info.get("update_at", "")
            existing["cover_url"] = existing["cover_url"] or _cover_from_card(card, response_url) or global_info.get("cover_url", "")

    # Some responses only contain m-week-square cards. Preserve them under '其他'
    # instead of discarding the catalog.
    for bangumi_id, global_info in global_cards.items():
        existing = merged.setdefault(
            bangumi_id,
            {
                "bangumi_id": bangumi_id,
                "weekday": 0,
                "title": "",
                "update_at": "",
                "cover_url": "",
                "base_url": f"{urlparse(response_url).scheme}://{urlparse(response_url).netloc}",
            },
        )
        existing["title"] = existing["title"] or global_info.get("title", "")
        existing["update_at"] = existing["update_at"] or global_info.get("update_at", "")
        existing["cover_url"] = existing["cover_url"] or global_info.get("cover_url", "")

    result: list[dict[str, Any]] = []
    for item in merged.values():
        if not item["title"]:
            item["title"] = f"番剧 {item['bangumi_id']}"
        item["detail_url"] = f"{item['base_url']}/Home/Bangumi/{item['bangumi_id']}"
        item["cover_proxy_url"] = (
            "/api/discovery/mikan/image?url=" + quote(item["cover_url"], safe="")
            if item["cover_url"]
            else ""
        )
        result.append(item)
    return sorted(result, key=lambda row: (row["weekday"], row["title"].casefold(), row["bangumi_id"]))


async def fetch_catalog(year: int, season: str) -> tuple[list[dict[str, Any]], str]:
    errors: list[str] = []
    urls = (settings.mikan_base_url, *settings.mikan_fallback_urls)
    headers = {
        "User-Agent": "FeedDock/1.8 (+self-hosted RSS manager)",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
    }
    async with httpx.AsyncClient(
        timeout=settings.request_timeout_seconds,
        follow_redirects=True,
        headers=headers,
    ) as client:
        for base_url in urls:
            endpoint = catalog_endpoint(base_url, year, season)
            try:
                response = await client.get(endpoint)
                response.raise_for_status()
                items = parse_catalog_html(response.text, str(response.url))
                if not items:
                    raise MikanError("返回内容中没有识别到番剧")
                return items, str(response.url)
            except Exception as exc:  # source fallback is intentional
                errors.append(f"{base_url}: {exc}")
    raise MikanError("Mikan 解析失败：" + "；".join(errors))


def save_catalog(year: int, season: str, items: list[dict[str, Any]], source_url: str) -> str:
    fetched_at = datetime.now(timezone.utc).isoformat()
    payload = json.dumps(items, ensure_ascii=False)
    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO mikan_cache(cache_key, payload, fetched_at, source_url, schema_version)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET
                payload=excluded.payload,
                fetched_at=excluded.fetched_at,
                source_url=excluded.source_url,
                schema_version=excluded.schema_version
            """,
            (cache_key(year, season), payload, fetched_at, source_url, CACHE_SCHEMA_VERSION),
        )
    return fetched_at


def load_catalog(year: int, season: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT payload, fetched_at, source_url, schema_version FROM mikan_cache WHERE cache_key=?",
            (cache_key(year, season),),
        ).fetchone()
    if row is None or int(row["schema_version"]) != CACHE_SCHEMA_VERSION:
        return None
    try:
        items = json.loads(row["payload"])
    except json.JSONDecodeError:
        return None
    fetched = datetime.fromisoformat(row["fetched_at"])
    stale = fetched + timedelta(hours=settings.mikan_cache_hours) <= datetime.now(timezone.utc)
    return {
        "items": items,
        "fetched_at": row["fetched_at"],
        "source_url": row["source_url"],
        "stale": stale,
    }


def apply_hidden(items: list[dict[str, Any]], year: int, season: str, include_hidden: bool) -> tuple[list[dict], int]:
    hidden = hidden_id_set(year, normalize_season(season))
    output: list[dict] = []
    hidden_count = 0
    for item in items:
        copied = dict(item)
        copied["hidden"] = (int(copied.get("weekday", 0)), int(copied["bangumi_id"])) in hidden
        if copied["hidden"]:
            hidden_count += 1
        if include_hidden or not copied["hidden"]:
            output.append(copied)
    return output, hidden_count


def group_by_weekday(items: list[dict], include_hidden: bool = True) -> list[dict]:
    groups: dict[int, list[dict]] = {day: [] for day in range(1, 8)}
    groups[0] = []
    for item in items:
        groups.setdefault(int(item.get("weekday", 0)), []).append(item)
    result: list[dict] = []
    for day in [1, 2, 3, 4, 5, 6, 7]:
        all_items = groups[day]
        result.append(
            {
                "weekday": day,
                "name": WEEKDAY_NAMES[day],
                "items": all_items if include_hidden else [item for item in all_items if not item.get("hidden")],
                "total_count": len(all_items),
                "hidden_count": sum(1 for item in all_items if item.get("hidden")),
            }
        )
    if groups[0]:
        all_items = groups[0]
        result.append(
            {
                "weekday": 0,
                "name": WEEKDAY_NAMES[0],
                "items": all_items if include_hidden else [item for item in all_items if not item.get("hidden")],
                "total_count": len(all_items),
                "hidden_count": sum(1 for item in all_items if item.get("hidden")),
            }
        )
    return result


def parse_bangumi_detail(content: str, response_url: str, bangumi_id: int) -> dict[str, Any]:
    soup = BeautifulSoup(content, "html.parser")
    title_tag = soup.select_one("h1, .bangumi-title, .title")
    title = title_tag.get_text(" ", strip=True) if title_tag else ""
    base_url = f"{urlparse(response_url).scheme}://{urlparse(response_url).netloc}"
    groups: dict[int, str] = {}

    for link in soup.find_all("a", href=True):
        href = _attr_text(link, "href")
        match = re.search(r"/Home/PublishGroup/(\d+)", href, re.I)
        if match:
            name = link.get_text(" ", strip=True) or f"字幕组 {match.group(1)}"
            groups[int(match.group(1))] = name
        for pattern in (r"subgroupid=(\d+)", r"subgroupId[=:]\s*['\"]?(\d+)"):
            match = re.search(pattern, href, re.I)
            if match:
                groups[int(match.group(1))] = link.get_text(" ", strip=True) or f"字幕组 {match.group(1)}"

    for node in soup.select("[data-subgroupid], [data-subgroup-id], [data-publishgroupid]"):
        value = _attr_text(node, "data-subgroupid", "data-subgroup-id", "data-publishgroupid")
        if value.isdigit():
            groups[int(value)] = node.get_text(" ", strip=True) or f"字幕组 {value}"

    # Current Mikan pages often expose names as div.subgroup-text and IDs elsewhere.
    names = [node.get_text(" ", strip=True) for node in soup.select("div.subgroup-text") if node.get_text(" ", strip=True)]
    if names and not groups:
        script_text = "\n".join(script.get_text(" ", strip=True) for script in soup.find_all("script"))
        ids = [int(value) for value in re.findall(r"subgroup(?:id|Id)[^\d]{0,10}(\d+)", script_text)]
        for group_id, name in zip(dict.fromkeys(ids), names):
            groups[group_id] = name

    rows = [
        {
            "subgroup_id": group_id,
            "name": name,
            "rss_url": f"{base_url}/RSS/Bangumi?bangumiId={bangumi_id}&subgroupid={group_id}",
        }
        for group_id, name in sorted(groups.items(), key=lambda item: item[1].casefold())
    ]
    return {
        "bangumi_id": bangumi_id,
        "title": title,
        "detail_url": str(response_url),
        "base_url": base_url,
        "subgroups": rows,
    }


async def fetch_bangumi_detail(bangumi_id: int, preferred_base_url: str = "") -> dict[str, Any]:
    candidates = []
    if preferred_base_url:
        candidates.append(preferred_base_url.rstrip("/"))
    candidates.extend([settings.mikan_base_url, *settings.mikan_fallback_urls])
    candidates = list(dict.fromkeys(candidates))
    errors: list[str] = []
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds, follow_redirects=True) as client:
        for base in candidates:
            try:
                response = await client.get(
                    f"{base}/Home/Bangumi/{bangumi_id}",
                    headers={"User-Agent": "FeedDock/1.8", "Accept-Language": "zh-CN,zh;q=0.9"},
                )
                response.raise_for_status()
                result = parse_bangumi_detail(response.text, str(response.url), bangumi_id)
                if result["subgroups"]:
                    return result
                errors.append(f"{base}: 未识别到字幕组 ID")
            except Exception as exc:
                errors.append(f"{base}: {exc}")
    raise MikanError("Mikan 详情解析失败：" + "；".join(errors))


def validate_image_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("无效图片地址")
    if parsed.hostname not in settings.allowed_mikan_hosts:
        raise ValueError("图片域名不在 Mikan 白名单")
    if not parsed.path.startswith("/images/"):
        raise ValueError("只允许代理 Mikan 图片路径")


def image_cache_path(url: str) -> Path:
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        suffix = ".img"
    return settings.image_cache_dir / f"{hashlib.sha256(url.encode()).hexdigest()}{suffix}"


async def fetch_image(url: str) -> tuple[Path, str]:
    validate_image_url(url)
    settings.image_cache_dir.mkdir(parents=True, exist_ok=True)
    target = image_cache_path(url)
    if target.exists() and datetime.fromtimestamp(target.stat().st_mtime, timezone.utc) + timedelta(days=1) > datetime.now(timezone.utc):
        return target, "application/octet-stream"
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds, follow_redirects=False) as client:
        current = url
        for _ in range(4):
            validate_image_url(current)
            response = await client.get(current, headers={"User-Agent": "FeedDock/1.8", "Referer": settings.mikan_base_url + "/"})
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if not location:
                    raise MikanError("图片重定向缺少 Location")
                current = urljoin(current, location)
                continue
            response.raise_for_status()
            content_type = response.headers.get("content-type", "application/octet-stream").split(";", 1)[0]
            if not content_type.startswith("image/"):
                raise MikanError("Mikan 返回的不是图片")
            target.write_bytes(response.content)
            return target, content_type
    raise MikanError("图片重定向次数过多")
