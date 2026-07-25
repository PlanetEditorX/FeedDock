from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from xml.etree import ElementTree as ET


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _child(element: ET.Element, name: str) -> ET.Element | None:
    wanted = name.lower()
    for child in element:
        if _local_name(child.tag) == wanted:
            return child
    return None


def _children(element: ET.Element, name: str) -> list[ET.Element]:
    wanted = name.lower()
    return [child for child in element if _local_name(child.tag) == wanted]


def _text(element: ET.Element | None) -> str:
    if element is None:
        return ""
    return "".join(element.itertext()).strip()


def _parse_date(value: str) -> datetime | None:
    value = value.strip()
    if not value:
        return None
    try:
        result = parsedate_to_datetime(value)
        if result.tzinfo is None:
            result = result.replace(tzinfo=timezone.utc)
        return result.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        pass
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            result = result.replace(tzinfo=timezone.utc)
        return result.astimezone(timezone.utc)
    except ValueError:
        return None


def _parse_rss_item(item: ET.Element) -> dict[str, Any]:
    links: list[dict[str, str]] = []
    enclosures: list[dict[str, str]] = []

    for enclosure in _children(item, "enclosure"):
        href = enclosure.attrib.get("url", "").strip()
        if href:
            data = {"href": href, "type": enclosure.attrib.get("type", "")}
            enclosures.append(data)
            links.append(data)

    link_text = _text(_child(item, "link"))
    if link_text:
        links.append({"href": link_text, "type": "", "rel": "alternate"})

    published = _text(_child(item, "pubDate")) or _text(_child(item, "date"))
    return {
        "title": _text(_child(item, "title")),
        "link": link_text,
        "links": links,
        "enclosures": enclosures,
        "id": _text(_child(item, "guid")),
        "guid": _text(_child(item, "guid")),
        "summary": _text(_child(item, "description")),
        "description": _text(_child(item, "description")),
        "published": published,
        "published_datetime": _parse_date(published),
    }


def _parse_atom_entry(entry: ET.Element) -> dict[str, Any]:
    links: list[dict[str, str]] = []
    enclosures: list[dict[str, str]] = []
    source_url = ""

    for link in _children(entry, "link"):
        href = link.attrib.get("href", "").strip()
        if not href:
            continue
        rel = link.attrib.get("rel", "alternate")
        media_type = link.attrib.get("type", "")
        data = {"href": href, "type": media_type, "rel": rel}
        links.append(data)
        if rel == "enclosure":
            enclosures.append(data)
        if not source_url and rel in {"alternate", ""}:
            source_url = href

    published = _text(_child(entry, "published")) or _text(_child(entry, "updated"))
    summary = _text(_child(entry, "summary")) or _text(_child(entry, "content"))
    entry_id = _text(_child(entry, "id"))
    return {
        "title": _text(_child(entry, "title")),
        "link": source_url,
        "links": links,
        "enclosures": enclosures,
        "id": entry_id,
        "guid": entry_id,
        "summary": summary,
        "description": summary,
        "published": published,
        "published_datetime": _parse_date(published),
    }


def parse_feed(content: bytes) -> list[dict[str, Any]]:
    if len(content) > 10 * 1024 * 1024:
        raise ValueError("RSS 响应超过 10 MiB 限制")
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise ValueError(f"XML 解析失败：{exc}") from exc

    root_name = _local_name(root.tag)
    if root_name == "rss":
        channel = _child(root, "channel")
        if channel is None:
            channel = root
        return [_parse_rss_item(item) for item in _children(channel, "item")]
    if root_name == "rdf":
        return [_parse_rss_item(item) for item in _children(root, "item")]
    if root_name == "feed":
        return [_parse_atom_entry(entry) for entry in _children(root, "entry")]

    # Some feeds wrap RSS content in a custom root; search direct descendants conservatively.
    rss_items = [element for element in root.iter() if _local_name(element.tag) == "item"]
    if rss_items:
        return [_parse_rss_item(item) for item in rss_items]
    atom_entries = [element for element in root.iter() if _local_name(element.tag) == "entry"]
    if atom_entries:
        return [_parse_atom_entry(entry) for entry in atom_entries]
    raise ValueError("未识别的 RSS/Atom XML 格式")
