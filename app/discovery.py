from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlencode, urljoin, urlparse

import httpx

from .config import settings
from .rss_parser import parse_feed
from .rss_service import extract_download_url


_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
_MIKAN_BANGUMI_RE = re.compile(r"/(?:Home|home)/Bangumi/(\d+)(?:[/?#]|$)")
_MIKAN_GROUP_RE = re.compile(r"/(?:Home|home)/PublishGroup/(\d+)(?:[/?#]|$)")
_GENERIC_LINK_LABELS = {"订阅", "詳情", "详情", "查看", "more", "rss", "download"}


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
        attrs_dict = {key.lower(): (value or "") for key, value in attrs}
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
            prop = (attrs_dict.get("property") or attrs_dict.get("name")).lower()
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


def _clean_text(value: str) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _clean_mikan_title(value: str) -> str:
    value = _clean_text(value)
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
        "save_path_template": "{base}/{subscription}/Season {season}",
        "custom_download_path": "",
        "missing_detection": False,
        "only_latest": False,
        "enabled": True,
        "sample_title": _clean_text(sample_title),
    }


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


def build_dmhy_rss_url(query: str, base_url: str | None = None) -> str:
    base = _normalize_base(base_url or settings.dmhy_base_url)
    params = {
        "keyword": _clean_text(query),
        "sort_id": 2,
        "team_id": 0,
        "order": "date-desc",
    }
    return f"{base}/topics/rss/rss.xml?{urlencode(params)}"


def _published_string(entry: dict[str, Any]) -> str:
    published = entry.get("published_datetime")
    if isinstance(published, datetime):
        return published.isoformat()
    return str(entry.get("published", "") or "")


class DiscoveryService:
    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        mikan_bases: tuple[str, ...] | None = None,
        dmhy_base: str | None = None,
        timeout: int | float | None = None,
    ) -> None:
        self.client = client
        self.mikan_bases = tuple(_normalize_base(value) for value in (mikan_bases or _allowed_mikan_bases()))
        self.dmhy_base = _normalize_base(dmhy_base or settings.dmhy_base_url)
        self.timeout = timeout or settings.request_timeout_seconds
        self.headers = {
            "User-Agent": settings.rss_user_agent,
            "Accept": "text/html, application/rss+xml, application/xml, text/xml, */*",
        }

    def _get(self, url: str) -> httpx.Response:
        if self.client is not None:
            response = self.client.get(url, headers=self.headers, follow_redirects=True)
        else:
            response = httpx.get(
                url,
                headers=self.headers,
                timeout=self.timeout,
                follow_redirects=True,
            )
        response.raise_for_status()
        if len(response.content) > _MAX_RESPONSE_BYTES:
            raise ValueError("站点响应超过 8 MiB 限制")
        return response

    def search(self, provider: str, query: str, limit: int = 30) -> dict[str, Any]:
        provider = provider.strip().lower()
        query = _clean_text(query)
        if provider not in {"all", "mikan", "dmhy"}:
            raise ValueError("provider 仅支持 all、mikan 或 dmhy")
        if not query:
            raise ValueError("请输入搜索关键词")

        results: list[dict[str, Any]] = []
        errors: list[str] = []
        if provider in {"all", "mikan"}:
            try:
                results.extend(self.search_mikan(query, limit=limit))
            except Exception as exc:
                errors.append(f"Mikan：{exc}")
        if provider in {"all", "dmhy"}:
            try:
                results.extend(self.search_dmhy(query, limit=limit))
            except Exception as exc:
                errors.append(f"动漫花园：{exc}")

        return {
            "query": query,
            "provider": provider,
            "results": results[: max(limit, 1) * (2 if provider == "all" else 1)],
            "errors": errors,
        }

    def search_mikan(self, query: str, limit: int = 30) -> list[dict[str, Any]]:
        if not self.mikan_bases:
            raise RuntimeError("没有可用的 Mikan 站点地址")
        errors: list[str] = []

        for base in self.mikan_bases:
            url = f"{base}/Home/Search?{urlencode({'searchstr': query})}"
            try:
                response = self._get(url)
                results = parse_mikan_search_html(response.text, base, limit)
                if results:
                    return results
            except Exception as exc:
                errors.append(f"{base}: {exc}")

        # Mikan's RSS search endpoint is a useful fallback when the HTML layout
        # changes or the search page does not expose a bangumi detail link.
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
                detail = parse_mikan_detail_html(response.text, base, bangumi_id, title)
                if detail["groups"]:
                    return detail
                errors.append(f"{base}: 未解析到字幕组")
            except Exception as exc:
                errors.append(f"{base}: {exc}")
        raise RuntimeError("；".join(errors) or "未找到字幕组")

    def search_dmhy(self, query: str, limit: int = 30) -> list[dict[str, Any]]:
        rss_url = build_dmhy_rss_url(query, self.dmhy_base)
        response = self._get(rss_url)
        entries = parse_feed(response.content)

        results: list[dict[str, Any]] = [
            {
                "provider": "dmhy",
                "result_type": "feed",
                "id": "dmhy-keyword-feed",
                "title": f"订阅“{query}”的动漫花园搜索 RSS",
                "description": "使用关键词 RSS 持续接收后续发布；保存前可继续配置分辨率、字幕和排除规则。",
                "detail_url": f"{self.dmhy_base}/topics/list?{urlencode({'keyword': query})}",
                "rss_url": rss_url,
                "source_url": f"{self.dmhy_base}/topics/list?{urlencode({'keyword': query})}",
                "published_at": "",
                "download_url": "",
                "base_url": self.dmhy_base,
                "bangumi_id": None,
                "preset": _subscription_preset(
                    name=query,
                    source_name="动漫花园",
                    rss_url=rss_url,
                    sample_title=entries[0].get("title", "") if entries else query,
                ),
            }
        ]

        for index, entry in enumerate(entries[:limit]):
            title = _clean_text(str(entry.get("title", "") or "")) or f"动漫花园搜索结果 {index + 1}"
            results.append(
                {
                    "provider": "dmhy",
                    "result_type": "release",
                    "id": f"dmhy-release-{index}",
                    "title": title,
                    "description": "选择此条目会使用当前关键词 RSS，并把该标题带入规则预览。",
                    "detail_url": str(entry.get("link", "") or ""),
                    "rss_url": rss_url,
                    "source_url": str(entry.get("link", "") or ""),
                    "published_at": _published_string(entry),
                    "download_url": extract_download_url(entry),
                    "base_url": self.dmhy_base,
                    "bangumi_id": None,
                    "preset": _subscription_preset(
                        name=query,
                        source_name="动漫花园",
                        rss_url=rss_url,
                        sample_title=title,
                    ),
                }
            )
        return results
