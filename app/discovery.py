from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse

import httpx

from .config import settings
from .outbound import external_get
from .rss_parser import parse_feed
from .rss_service import extract_download_url


_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
_MIKAN_BANGUMI_RE = re.compile(r"/(?:Home|home)/Bangumi/(\d+)(?:[/?#]|$)")
_MIKAN_GROUP_RE = re.compile(r"/(?:Home|home)/PublishGroup/(\d+)(?:[/?#]|$)")
_GENERIC_LINK_LABELS = {"订阅", "詳情", "详情", "查看", "more", "rss", "download"}
_ALLOWED_SEASONS = ("冬", "春", "夏", "秋")
_WEEKDAY_ALIASES = {
    "星期一": "星期一", "周一": "星期一", "礼拜一": "星期一", "月曜日": "星期一",
    "星期二": "星期二", "周二": "星期二", "礼拜二": "星期二", "火曜日": "星期二",
    "星期三": "星期三", "周三": "星期三", "礼拜三": "星期三", "水曜日": "星期三",
    "星期四": "星期四", "周四": "星期四", "礼拜四": "星期四", "木曜日": "星期四",
    "星期五": "星期五", "周五": "星期五", "礼拜五": "星期五", "金曜日": "星期五",
    "星期六": "星期六", "周六": "星期六", "礼拜六": "星期六", "土曜日": "星期六",
    "星期日": "星期日", "星期天": "星期日", "周日": "星期日", "周天": "星期日",
    "礼拜日": "星期日", "礼拜天": "星期日", "日曜日": "星期日",
}
_DAY_NUMBER_NAMES = {
    0: "星期日",
    1: "星期一",
    2: "星期二",
    3: "星期三",
    4: "星期四",
    5: "星期五",
    6: "星期六",
    7: "星期日",
}


def _safe_attrs(attrs: list[tuple[str | None, str | None]]) -> dict[str, str]:
    """Normalize attributes while tolerating malformed upstream HTML."""

    return {str(key).lower(): (value or "") for key, value in attrs if key is not None}


@dataclass(slots=True)
class _Anchor:
    href: str
    title: str


class _DocumentParser(HTMLParser):
    """Collect anchors and a conservative page title without extra dependencies."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.anchors: list[_Anchor] = []
        self.page_title = ""
        self._anchor_href = ""
        self._anchor_parts: list[str] = []
        self._anchor_open = False
        self._capture_title = False
        self._title_parts: list[str] = []
        self._heading_depth = 0
        self._heading_parts: list[str] = []
        self._headings: list[str] = []
        self.subgroup_ids: set[int] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = _safe_attrs(attrs)
        tag = tag.lower()
        for candidate in (attrs_dict.get("id", ""), attrs_dict.get("data-subgroupid", "")):
            match = re.search(r"(?:subgroup-)?(\d+)$", candidate)
            if match and ("subgroup" in candidate.lower() or attrs_dict.get("data-subgroupid")):
                self.subgroup_ids.add(int(match.group(1)))
        if tag == "a":
            self._finish_anchor()
            self._anchor_href = attrs_dict.get("href", "").strip()
            self._anchor_parts = [attrs_dict.get("title", ""), attrs_dict.get("aria-label", "")]
            self._anchor_open = True
        elif tag == "img" and self._anchor_open:
            self._anchor_parts.extend(
                [
                    attrs_dict.get("alt", ""),
                    attrs_dict.get("title", ""),
                    attrs_dict.get("aria-label", ""),
                ]
            )
        elif tag == "meta":
            prop = (attrs_dict.get("property") or attrs_dict.get("name") or "").lower()
            if prop in {"og:title", "twitter:title"} and attrs_dict.get("content"):
                self.page_title = _clean_text(attrs_dict["content"])
        elif tag == "title":
            self._capture_title = True
            self._title_parts = []
        elif tag in {"h1", "h2"}:
            self._heading_depth += 1
            if self._heading_depth == 1:
                self._heading_parts = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "a":
            self._finish_anchor()
        elif tag == "title":
            self._capture_title = False
            if not self.page_title:
                self.page_title = _clean_text(" ".join(self._title_parts))
        elif tag in {"h1", "h2"} and self._heading_depth:
            self._heading_depth -= 1
            if self._heading_depth == 0:
                value = _clean_text(" ".join(self._heading_parts))
                if value:
                    self._headings.append(value)

    def handle_data(self, data: str) -> None:
        if self._anchor_open:
            self._anchor_parts.append(data)
        if self._capture_title:
            self._title_parts.append(data)
        if self._heading_depth:
            self._heading_parts.append(data)

    def close(self) -> None:
        self._finish_anchor()
        super().close()
        if self._headings and not self.page_title:
            self.page_title = self._headings[0]

    def _finish_anchor(self) -> None:
        if not self._anchor_open:
            return
        title = _clean_text(" ".join(self._anchor_parts))
        self.anchors.append(_Anchor(self._anchor_href, title))
        self._anchor_href = ""
        self._anchor_parts = []
        self._anchor_open = False


@dataclass(slots=True)
class _HtmlNode:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list["_HtmlNode"] = field(default_factory=list)
    text_parts: list[str] = field(default_factory=list)
    parent: "_HtmlNode | None" = field(default=None, repr=False)

    def text(self) -> str:
        parts = list(self.text_parts)
        for child in self.children:
            parts.append(child.text())
        return _clean_text(" ".join(parts))

    def classes(self) -> set[str]:
        return {part for part in self.attrs.get("class", "").split() if part}

    def descendants(self, tag: str | None = None) -> Iterable["_HtmlNode"]:
        for child in self.children:
            if tag is None or child.tag == tag:
                yield child
            yield from child.descendants(tag)


class _TreeParser(HTMLParser):
    _VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _HtmlNode("document")
        self._stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        node = _HtmlNode(tag=tag, attrs=_safe_attrs(attrs), parent=self._stack[-1])
        self._stack[-1].children.append(node)
        if tag not in self._VOID_TAGS:
            self._stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if self._stack[-1].tag == tag.lower():
            self._stack.pop()

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index].tag == tag:
                del self._stack[index:]
                return

    def handle_data(self, data: str) -> None:
        if data:
            self._stack[-1].text_parts.append(data)


def _clean_text(value: str) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _clean_mikan_title(value: str) -> str:
    value = _clean_text(value)
    value = re.sub(r"^(?:蜜柑计划|Mikan Project)\s*[|｜-]\s*", "", value, flags=re.IGNORECASE).strip()
    value = re.sub(r"\s*[|｜-]\s*(?:蜜柑计划|Mikan Project).*$", "", value, flags=re.IGNORECASE).strip()
    if value.casefold() in {"mikan project", "mikan", "蜜柑计划"}:
        return ""
    return value


def _normalize_base(value: str) -> str:
    value = value.strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"站点地址无效：{value}")
    return f"{parsed.scheme}://{parsed.netloc}"


def _allowed_mikan_bases() -> tuple[str, ...]:
    values: list[str] = []
    for raw in (settings.mikan_base_url, *settings.mikan_fallback_urls):
        try:
            value = _normalize_base(raw)
        except ValueError:
            continue
        if value not in values:
            values.append(value)
    return tuple(values)


def _response_base(response: httpx.Response, allowed_bases: tuple[str, ...]) -> str:
    """Return the final Mikan origin after redirects.

    Mikan aliases can redirect to another configured domain. Relative cover and
    RSS paths must be resolved against the final response origin, otherwise a
    catalog fetched through one alias can incorrectly point images at another
    host that does not serve the same asset.
    """

    final_base = _normalize_base(str(response.url))
    if final_base not in allowed_bases:
        raise ValueError(f"Mikan 重定向到了未允许的站点：{final_base}")
    return final_base


def _subscription_preset(
    *,
    name: str,
    source_name: str,
    rss_url: str,
    sample_title: str = "",
) -> dict[str, Any]:
    cleaned_name = _clean_text(name) or "未命名番剧"
    return {
        "name": cleaned_name,
        "reference_title": cleaned_name,
        "tmdb_title": "",
        "bgm_url": "",
        "air_date": None,
        "season": 1,
        "primary_rss_name": source_name,
        "rss_url": rss_url,
        "backup_rss_name": "",
        "backup_rss_url": None,
        "include_keywords": "",
        "exclude_keywords": "",
        "episode_regex": "",
        "episode_group": 0,
        "episode_offset": 0,
        "total_episodes": 0,
        "save_path_template": "{base}/{media_folder}/Season {season:02}",
        "custom_download_path": "",
        "missing_detection": False,
        "only_latest": False,
        "enabled": True,
        "sample_title": _clean_text(sample_title),
    }


def _weekday_name(raw_text: str, raw_number: str) -> str:
    compact = _clean_text(raw_text)
    for alias, normalized in _WEEKDAY_ALIASES.items():
        if alias in compact:
            return normalized
    try:
        return _DAY_NUMBER_NAMES.get(int(raw_number), compact or "其他")
    except (TypeError, ValueError):
        return compact or "其他"


def _first_descendant(node: _HtmlNode, *, tag: str | None = None, class_name: str = "", attr: str = "") -> _HtmlNode | None:
    for candidate in node.descendants(tag):
        if class_name and class_name not in candidate.classes():
            continue
        if attr and not candidate.attrs.get(attr):
            continue
        return candidate
    return None


_IMAGE_ATTRIBUTES = ("data-src", "data-original", "data-lazy-src", "data-url", "src", "poster")
_CATALOG_CONTAINER_CLASSES = {"an-info-group", "an-info", "bangumi-item", "m-week-square"}


def _extract_style_url(style: str) -> str:
    match = re.search(r"(?:background-image|background)\s*:\s*url\(\s*['\"]?([^'\")]+)", style or "", re.IGNORECASE)
    return _clean_text(match.group(1)) if match else ""


def _usable_image_url(value: str) -> str:
    value = _clean_text(value)
    if not value or value.startswith(("data:", "blob:", "javascript:")):
        return ""
    return value


def _thumbnail_image_url(value: str) -> str:
    """Request a small WebP cover from Mikan instead of the 400px source.

    The official catalog already exposes an image-resize query. Replacing only
    these parameters keeps the original path stable while cutting transfer size
    for the 66x88px cards used by FeedDock.
    """

    value = _usable_image_url(value)
    if not value:
        return ""
    parsed = urlparse(value)
    params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    params.update(
        {
            "width": str(settings.mikan_thumbnail_width),
            "height": str(settings.mikan_thumbnail_height),
            "format": "webp",
        }
    )
    return parsed._replace(query=urlencode(params)).geturl()


def _extract_image_candidate(node: _HtmlNode) -> str:
    for candidate in (node, *node.descendants()):
        for attribute in _IMAGE_ATTRIBUTES:
            value = _usable_image_url(candidate.attrs.get(attribute, ""))
            if value:
                return value
        srcset = candidate.attrs.get("srcset", "")
        if srcset:
            value = _usable_image_url(srcset.split(",", 1)[0].strip().split(" ", 1)[0])
            if value:
                return value
        value = _usable_image_url(_extract_style_url(candidate.attrs.get("style", "")))
        if value:
            return value
    return ""


def _catalog_container(node: _HtmlNode, boundary: _HtmlNode) -> _HtmlNode:
    """Return the complete card node that contains both metadata and cover.

    Mikan's official desktop catalog places the title link inside
    ``div.an-info-group`` while the cover is a sibling ``span[data-src]``
    directly under the surrounding ``li``.  Stopping at ``an-info-group``
    therefore loses the cover.  Prefer an ancestor ``li`` when present, but
    retain the nearest known card container as a fallback for fragments that
    do not use list items.
    """

    current: _HtmlNode | None = node
    closest = node
    fallback: _HtmlNode | None = None
    while current is not None and current is not boundary:
        closest = current
        if current.tag == "li":
            return current
        if fallback is None and current.classes() & _CATALOG_CONTAINER_CLASSES:
            fallback = current
        current = current.parent
    return fallback or closest


def _subgroup_id(node: _HtmlNode) -> int | None:
    for raw in (node.attrs.get("data-subgroupid", ""), node.attrs.get("id", "")):
        match = re.search(r"(?:subgroup[-_])?(\d+)$", raw.strip(), re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def parse_mikan_catalog_html(
    content: str,
    base_url: str,
    *,
    year: int,
    season: str,
    query: str = "",
) -> list[dict[str, Any]]:
    """Parse Mikan's season/day-of-week fragment into stable catalog rows."""

    parser = _TreeParser()
    parser.feed(content)
    parser.close()
    query_folded = _clean_text(query).casefold()
    rows: list[dict[str, Any]] = []
    seen_ids: set[int] = set()

    for section in parser.root.descendants("div"):
        if "sk-bangumi" not in section.classes():
            continue
        day_number = section.attrs.get("data-dayofweek", "")
        heading_text = ""
        for child in section.children:
            if child.tag != "ul":
                heading_text = child.text()
                if heading_text:
                    break
        weekday = _weekday_name(heading_text, day_number)
        items: list[dict[str, Any]] = []

        candidates: list[tuple[int, _HtmlNode, _HtmlNode]] = []
        for anchor in section.descendants("a"):
            match = _MIKAN_BANGUMI_RE.search(anchor.attrs.get("href", ""))
            if match:
                candidates.append((int(match.group(1)), anchor, _catalog_container(anchor, section)))

        # Compatibility with older fragments where the ID only exists on data-bangumiid.
        if not candidates:
            for marker_node in section.descendants():
                raw_id = marker_node.attrs.get("data-bangumiid", "")
                if raw_id.isdigit():
                    candidates.append((int(raw_id), marker_node, _catalog_container(marker_node, section)))

        for bangumi_id, source_node, item_node in candidates:
            if bangumi_id in seen_ids:
                continue

            title = ""
            if source_node.tag == "a":
                title = _clean_mikan_title(source_node.attrs.get("title", "") or source_node.text())
            if not title:
                title_node = _first_descendant(item_node, class_name="an-text")
                if title_node is not None:
                    title = _clean_mikan_title(title_node.attrs.get("title", "") or title_node.text())
            if not title:
                title = _clean_mikan_title(source_node.attrs.get("title", ""))
            if not title:
                image = _first_descendant(item_node, tag="img")
                if image is not None:
                    title = _clean_mikan_title(image.attrs.get("alt", "") or image.attrs.get("title", ""))
            if not title:
                title = f"Mikan 番剧 #{bangumi_id}"
            if query_folded and query_folded not in title.casefold():
                continue

            date_node = _first_descendant(item_node, class_name="date-text")
            cover_raw = _thumbnail_image_url(_extract_image_candidate(item_node))
            detail_url = f"{base_url}/Home/Bangumi/{bangumi_id}"
            items.append(
                {
                    "bangumi_id": bangumi_id,
                    "title": title,
                    "cover_url": urljoin(base_url + "/", cover_raw) if cover_raw else "",
                    "cover_proxy_url": "",
                    "update_at": date_node.text() if date_node is not None else "",
                    "detail_url": detail_url,
                    "base_url": base_url,
                }
            )
            seen_ids.add(bangumi_id)

        if items:
            rows.append(
                {
                    "weekday": weekday,
                    "day_of_week": int(day_number) if day_number.isdigit() else None,
                    "items": items,
                }
            )

    return rows


def parse_mikan_search_html(content: str, base_url: str, limit: int = 30) -> list[dict[str, Any]]:
    parser = _DocumentParser()
    parser.feed(content)
    parser.close()

    by_id: dict[int, dict[str, Any]] = {}
    for anchor in parser.anchors:
        match = _MIKAN_BANGUMI_RE.search(anchor.href)
        if not match:
            continue
        bangumi_id = int(match.group(1))
        title = _clean_mikan_title(anchor.title)
        if title.casefold() in _GENERIC_LINK_LABELS:
            title = ""
        current = by_id.get(bangumi_id)
        if current and len(current["title"]) >= len(title):
            continue
        by_id[bangumi_id] = {
            "provider": "mikan",
            "result_type": "bangumi",
            "id": f"mikan-bangumi-{bangumi_id}",
            "title": title or f"Mikan 番剧 #{bangumi_id}",
            "description": "选择番剧后可继续选择字幕组，并生成该字幕组的专用 RSS。",
            "detail_url": urljoin(base_url + "/", anchor.href),
            "rss_url": "",
            "source_url": urljoin(base_url + "/", anchor.href),
            "published_at": "",
            "download_url": "",
            "base_url": base_url,
            "bangumi_id": bangumi_id,
            "preset": None,
        }
    return list(by_id.values())[:limit]


def parse_mikan_detail_html(
    content: str,
    base_url: str,
    bangumi_id: int,
    fallback_title: str = "",
) -> dict[str, Any]:
    parser = _DocumentParser()
    parser.feed(content)
    parser.close()

    title = _clean_mikan_title(parser.page_title) or _clean_mikan_title(fallback_title)
    if not title:
        title = f"Mikan 番剧 #{bangumi_id}"

    groups: dict[int, dict[str, Any]] = {}

    # Current Mikan pages group resources under div.subgroup-text. Its id can be
    # a bare number, subgroup-123, or data-subgroupid; a PublishGroup link is optional.
    tree = _TreeParser()
    tree.feed(content)
    tree.close()
    for node in tree.root.descendants():
        if "subgroup-text" not in node.classes():
            continue
        subgroup_id = _subgroup_id(node)
        if subgroup_id is None:
            continue
        anchor_node = _first_descendant(node, tag="a")
        name = _clean_text(anchor_node.text() if anchor_node is not None else node.text())
        if not name or name.casefold() in _GENERIC_LINK_LABELS:
            name = f"字幕组 #{subgroup_id}"
        rss_url = f"{base_url}/RSS/Bangumi?{urlencode({'bangumiId': bangumi_id, 'subgroupid': subgroup_id})}"
        href = anchor_node.attrs.get("href", "") if anchor_node is not None else ""
        groups[subgroup_id] = {
            "subgroup_id": subgroup_id,
            "name": name,
            "rss_url": rss_url,
            "detail_url": urljoin(base_url + "/", href) if href else "",
            "preset": _subscription_preset(
                name=title,
                source_name=f"Mikan · {name}",
                rss_url=rss_url,
                sample_title=title,
            ),
        }

    for anchor in parser.anchors:
        match = _MIKAN_GROUP_RE.search(anchor.href)
        if not match:
            continue
        subgroup_id = int(match.group(1))
        name = _clean_text(anchor.title)
        if not name or name.casefold() in _GENERIC_LINK_LABELS:
            name = f"字幕组 #{subgroup_id}"
        rss_url = f"{base_url}/RSS/Bangumi?{urlencode({'bangumiId': bangumi_id, 'subgroupid': subgroup_id})}"
        current = groups.get(subgroup_id)
        if current and not current["name"].startswith("字幕组 #"):
            continue
        groups[subgroup_id] = {
            "subgroup_id": subgroup_id,
            "name": name,
            "rss_url": rss_url,
            "detail_url": urljoin(base_url + "/", anchor.href),
            "preset": _subscription_preset(
                name=title,
                source_name=f"Mikan · {name}",
                rss_url=rss_url,
                sample_title=title,
            ),
        }

    for subgroup_id in parser.subgroup_ids:
        if subgroup_id in groups:
            continue
        name = f"字幕组 #{subgroup_id}"
        rss_url = f"{base_url}/RSS/Bangumi?{urlencode({'bangumiId': bangumi_id, 'subgroupid': subgroup_id})}"
        groups[subgroup_id] = {
            "subgroup_id": subgroup_id,
            "name": name,
            "rss_url": rss_url,
            "detail_url": "",
            "preset": _subscription_preset(
                name=title,
                source_name=f"Mikan · {name}",
                rss_url=rss_url,
                sample_title=title,
            ),
        }

    return {
        "provider": "mikan",
        "bangumi_id": bangumi_id,
        "title": title,
        "base_url": base_url,
        "detail_url": f"{base_url}/Home/Bangumi/{bangumi_id}",
        "groups": list(groups.values()),
    }


def _published_string(entry: dict[str, Any]) -> str:
    published = entry.get("published_datetime")
    if published is not None and hasattr(published, "isoformat"):
        return str(published.isoformat())
    return str(entry.get("published", "") or "")


class DiscoveryService:
    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        mikan_bases: tuple[str, ...] | None = None,
        timeout: int | float | None = None,
    ) -> None:
        self.client = client
        self.mikan_bases = tuple(_normalize_base(value) for value in (mikan_bases or _allowed_mikan_bases()))
        self.timeout = timeout or settings.request_timeout_seconds
        self.headers = {
            "User-Agent": settings.rss_user_agent,
            "Accept": "text/html, application/rss+xml, application/xml, text/xml, */*",
        }

    def _get(self, url: str) -> httpx.Response:
        if self.client is not None:
            response = self.client.get(url, headers=self.headers, follow_redirects=True)
        else:
            response = external_get(
                url,
                headers=self.headers,
                timeout=self.timeout,
            )
        response.raise_for_status()
        if len(response.content) > _MAX_RESPONSE_BYTES:
            raise ValueError("站点响应超过 8 MiB 限制")
        return response

    def catalog(self, year: int, season: str, query: str = "") -> dict[str, Any]:
        if not 2000 <= year <= 2100:
            raise ValueError("年份必须在 2000 到 2100 之间")
        season = _clean_text(season)
        if season not in _ALLOWED_SEASONS:
            raise ValueError("季度仅支持冬、春、夏、秋")
        if not self.mikan_bases:
            raise RuntimeError("没有可用的 Mikan 站点地址")

        errors: list[str] = []
        for base in self.mikan_bases:
            url = f"{base}/Home/BangumiCoverFlowByDayOfWeek?{urlencode({'year': year, 'seasonStr': season})}"
            try:
                response = self._get(url)
                effective_base = _response_base(response, self.mikan_bases)
                rows = parse_mikan_catalog_html(
                    response.text,
                    effective_base,
                    year=year,
                    season=season,
                    query=query,
                )
                if rows:
                    for row in rows:
                        for item in row["items"]:
                            if item.get("cover_url"):
                                cover_base = _normalize_base(item.get("base_url") or effective_base)
                                cover_origin = _normalize_base(item["cover_url"])
                                if cover_base in self.mikan_bases and cover_origin in self.mikan_bases:
                                    item["cover_proxy_url"] = "/api/discovery/mikan/image?" + urlencode(
                                        {"base_url": cover_base, "url": item["cover_url"]}
                                    )
                    return {
                        "provider": "mikan",
                        "year": year,
                        "season": season,
                        "query": _clean_text(query),
                        "base_url": effective_base,
                        "rows": rows,
                        "errors": errors,
                    }
                errors.append(f"{base}: 未解析到番剧")
            except Exception as exc:
                errors.append(f"{base}: {exc}")
        raise RuntimeError("；".join(errors) or "未找到番剧目录")

    def fetch_image(self, base_url: str, image_url: str) -> tuple[bytes, str]:
        base = _normalize_base(base_url)
        if base not in self.mikan_bases:
            raise ValueError("Mikan 地址不在允许列表中")
        target = urljoin(base + "/", image_url.strip())
        target_parts = urlparse(target)
        target_base = _normalize_base(target)
        if target_parts.scheme not in {"http", "https"} or target_base not in self.mikan_bases:
            raise ValueError("封面地址不属于允许的 Mikan 站点")

        headers = {
            **self.headers,
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            "Referer": target_base + "/",
        }
        if self.client is not None:
            response = self.client.get(target, headers=headers, follow_redirects=True)
        else:
            response = external_get(target, headers=headers, timeout=self.timeout)
        response.raise_for_status()
        final_base = _normalize_base(str(response.url))
        if final_base not in self.mikan_bases:
            raise ValueError("封面重定向到了不受信任的站点")
        if len(response.content) > 6 * 1024 * 1024:
            raise ValueError("封面超过 6 MiB 限制")
        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if not content_type.startswith("image/"):
            raise ValueError("来源返回的内容不是图片")
        return response.content, content_type

    def search(self, query: str, limit: int = 30) -> dict[str, Any]:
        query = _clean_text(query)
        if not query:
            raise ValueError("请输入搜索关键词")
        try:
            results = self.search_mikan(query, limit=limit)
            return {"query": query, "provider": "mikan", "results": results, "errors": []}
        except Exception as exc:
            return {"query": query, "provider": "mikan", "results": [], "errors": [f"Mikan：{exc}"]}

    def search_mikan(self, query: str, limit: int = 30) -> list[dict[str, Any]]:
        if not self.mikan_bases:
            raise RuntimeError("没有可用的 Mikan 站点地址")
        errors: list[str] = []

        for base in self.mikan_bases:
            url = f"{base}/Home/Search?{urlencode({'searchstr': query})}"
            try:
                response = self._get(url)
                effective_base = _response_base(response, self.mikan_bases)
                results = parse_mikan_search_html(response.text, effective_base, limit)
                if results:
                    return results
            except Exception as exc:
                errors.append(f"{base}: {exc}")

        # Fallback to Mikan's keyword RSS when the HTML search page changes.
        for base in self.mikan_bases:
            rss_url = f"{base}/RSS/Search?{urlencode({'searchstr': query})}"
            try:
                response = self._get(rss_url)
                entries = parse_feed(response.content)
                results: list[dict[str, Any]] = []
                for index, entry in enumerate(entries[:limit]):
                    title = _clean_text(str(entry.get("title", "") or "")) or f"Mikan 搜索结果 {index + 1}"
                    results.append(
                        {
                            "provider": "mikan",
                            "result_type": "release",
                            "id": f"mikan-release-{index}",
                            "title": title,
                            "description": "未找到番剧详情链接，已回退到 Mikan 关键词 RSS。",
                            "detail_url": str(entry.get("link", "") or ""),
                            "rss_url": rss_url,
                            "source_url": str(entry.get("link", "") or ""),
                            "published_at": _published_string(entry),
                            "download_url": extract_download_url(entry),
                            "base_url": base,
                            "bangumi_id": None,
                            "preset": _subscription_preset(
                                name=query,
                                source_name="Mikan 关键词搜索",
                                rss_url=rss_url,
                                sample_title=title,
                            ),
                        }
                    )
                if results:
                    return results
            except Exception as exc:
                errors.append(f"{base} RSS: {exc}")

        detail = "；".join(errors[-4:]) if errors else "没有搜索结果"
        raise RuntimeError(detail)

    def mikan_detail(self, bangumi_id: int, preferred_base: str = "", title: str = "") -> dict[str, Any]:
        if bangumi_id <= 0:
            raise ValueError("bangumi_id 必须大于 0")
        bases = list(self.mikan_bases)
        if preferred_base:
            normalized = _normalize_base(preferred_base)
            if normalized not in bases:
                raise ValueError("Mikan 地址不在允许列表中")
            bases.remove(normalized)
            bases.insert(0, normalized)

        errors: list[str] = []
        for base in bases:
            url = f"{base}/Home/Bangumi/{bangumi_id}"
            try:
                response = self._get(url)
                effective_base = _response_base(response, self.mikan_bases)
                detail = parse_mikan_detail_html(response.text, effective_base, bangumi_id, title)
                if detail["groups"]:
                    return detail
                errors.append(f"{base}: 未解析到字幕组")
            except Exception as exc:
                errors.append(f"{base}: {exc}")
        raise RuntimeError("；".join(errors) or "未找到字幕组")
