from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import parse_qsl, urlparse


def extract_mikan_bangumi_id(value: object) -> int:
    """Return the positive Mikan ``bangumiId`` contained in an RSS URL.

    Mikan links have appeared with different query-key casing across domains,
    so the key comparison is case-insensitive. Invalid, blank, or non-positive
    values are treated as not being a Mikan bangumi subscription.
    """

    if not isinstance(value, str) or not value.strip():
        return 0

    try:
        query_items = parse_qsl(urlparse(value.strip()).query, keep_blank_values=True)
    except (TypeError, ValueError):
        return 0

    for key, raw_value in query_items:
        if key.casefold() != "bangumiid":
            continue
        try:
            bangumi_id = int(raw_value)
        except (TypeError, ValueError):
            return 0
        return bangumi_id if bangumi_id > 0 else 0
    return 0


def collect_subscribed_mikan_bangumi_ids(
    rss_url_rows: Iterable[Iterable[object]],
) -> set[int]:
    """Collect unique Mikan bangumi IDs from primary and backup RSS values."""

    subscribed_ids: set[int] = set()
    for rss_urls in rss_url_rows:
        for value in rss_urls:
            bangumi_id = extract_mikan_bangumi_id(value)
            if bangumi_id:
                subscribed_ids.add(bangumi_id)
    return subscribed_ids
