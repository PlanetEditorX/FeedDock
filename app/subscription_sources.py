from __future__ import annotations

from dataclasses import asdict, dataclass
from urllib.parse import parse_qsl, urlsplit


@dataclass(frozen=True, slots=True)
class SubscriptionSource:
    id: str
    label: str
    short_label: str
    description: str
    rss_name: str
    placeholder: str
    default_feed_url: str
    official_url: str
    help_url: str
    hosts: tuple[str, ...]
    catalog_view: str = ""
    caution: str = ""


_SOURCES: tuple[SubscriptionSource, ...] = (
    SubscriptionSource(
        id="mikan",
        label="Mikan",
        short_label="Mikan",
        description="从季度番剧目录选择番剧和字幕组，FeedDock 会自动带入对应 RSS 与 Bangumi ID。",
        rss_name="Mikan",
        placeholder="https://mikanime.tv/RSS/Bangumi?bangumiId=...",
        default_feed_url="",
        official_url="https://mikanime.tv",
        help_url="https://mikanime.tv",
        hosts=("mikanime.tv", "mikanani.me", "mikanani.kas.pub", "mikan.tangbai.cc"),
        catalog_view="add-mikan",
        caution="推荐使用 FeedDock 的 Mikan 番剧目录，不要直接订阅全站 RSS。",
    ),
    SubscriptionSource(
        id="anibt",
        label="ANI.BT",
        short_label="ANI.BT",
        description="支持单番剧、字幕组、标签过滤和全站磁力 RSS；推荐在 ANI.BT 生成过滤后的订阅地址。",
        rss_name="ANI.BT",
        placeholder="https://anibt.net/rss/anime.xml?bgmId=...&groupSlug=...",
        default_feed_url="https://anibt.net/rss/magnets.xml",
        official_url="https://anibt.net",
        help_url="https://wiki.anibt.net/docs/open-api/rss-anime",
        hosts=("anibt.net",),
        caution="全站磁力 RSS 会包含大量资源，只有明确需要时才使用。",
    ),
    SubscriptionSource(
        id="ag",
        label="Anime Garden",
        short_label="AG",
        description="使用 Anime Garden 资源页生成的过滤 RSS；可按标题、字幕组和资源特征组合筛选。",
        rss_name="Anime Garden",
        placeholder="https://api.animes.garden/feed.xml?filter=...",
        default_feed_url="https://api.animes.garden/feed.xml",
        official_url="https://animes.garden",
        help_url="https://github.com/yjl9903/AnimeGarden",
        hosts=("animes.garden",),
        caution="未带过滤条件的 feed.xml 是全站资源流，建议先在站点生成过滤 RSS。",
    ),
    SubscriptionSource(
        id="other",
        label="其它 RSS",
        short_label="其它",
        description="添加任意标准 RSS 2.0、Atom 或 RDF 订阅地址。",
        rss_name="",
        placeholder="https://example.com/feed.xml",
        default_feed_url="",
        official_url="",
        help_url="",
        hosts=(),
        caution="请确认 RSS 条目包含磁力链接或可直接下载的种子附件。",
    ),
)

_SOURCE_MAP = {source.id: source for source in _SOURCES}


def subscription_source_catalog() -> list[dict[str, object]]:
    """Return the public source catalog without implementation-only tuple values."""
    result: list[dict[str, object]] = []
    for source in _SOURCES:
        payload = asdict(source)
        payload["hosts"] = list(source.hosts)
        result.append(payload)
    return result


def get_subscription_source(source_id: str | None) -> SubscriptionSource:
    return _SOURCE_MAP.get(str(source_id or "").strip().lower(), _SOURCE_MAP["other"])


def _matches_host(hostname: str, allowed_host: str) -> bool:
    hostname = hostname.lower().rstrip(".")
    allowed_host = allowed_host.lower().rstrip(".")
    return hostname == allowed_host or hostname.endswith(f".{allowed_host}")


def classify_subscription_source(url: str | None) -> str:
    """Classify a subscription URL without trusting display names supplied by users."""
    try:
        hostname = (urlsplit(str(url or "")).hostname or "").lower()
    except ValueError:
        return "other"
    if not hostname:
        return "other"
    for source in _SOURCES:
        if source.id == "other":
            continue
        if any(_matches_host(hostname, allowed_host) for allowed_host in source.hosts):
            return source.id
    return "other"


def subscription_source_label(url: str | None) -> str:
    return get_subscription_source(classify_subscription_source(url)).label


def extract_source_bangumi_id(url: str | None) -> int:
    """Extract Mikan/AniBT-compatible Bangumi query identifiers when available."""
    try:
        query = urlsplit(str(url or "")).query
    except ValueError:
        return 0
    for key, value in parse_qsl(query, keep_blank_values=False):
        if key.lower() not in {"bangumiid", "bgmid"}:
            continue
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            return parsed
    return 0
