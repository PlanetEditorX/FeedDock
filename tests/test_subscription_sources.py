from __future__ import annotations

import subprocess
import textwrap
import unittest
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.main import _subscription_out, _subscription_values, list_subscription_sources
from app.models import Subscription
from app.subscription_sources import (
    classify_subscription_source,
    extract_source_bangumi_id,
    subscription_source_catalog,
    subscription_source_label,
)


ROOT = Path(__file__).resolve().parents[1]


class SubscriptionSourceTests(unittest.TestCase):
    def test_catalog_contains_supported_add_subscription_sites(self) -> None:
        catalog = subscription_source_catalog()
        self.assertEqual([item["id"] for item in catalog], ["mikan", "anibt", "ag", "nyaa", "subsplease", "other"])
        by_id = {item["id"]: item for item in catalog}
        self.assertEqual(by_id["anibt"]["default_feed_url"], "https://anibt.net/rss/magnets.xml")
        self.assertEqual(by_id["ag"]["default_feed_url"], "https://api.animes.garden/feed.xml")
        self.assertEqual(by_id["mikan"]["catalog_view"], "add-catalog")
        self.assertFalse(by_id["other"]["default_feed_url"])

    def test_source_detection_uses_hostname_boundaries(self) -> None:
        cases = {
            "https://mikanime.tv/RSS/Bangumi?bangumiId=123": "mikan",
            "https://sub.mikanani.me/RSS/Bangumi?bangumiId=123": "mikan",
            "https://anibt.net/rss/anime.xml?bgmId=123": "anibt",
            "https://api.animes.garden/feed.xml": "ag",
            "https://nyaa.si/?page=rss&q=test": "nyaa",
            "https://subsplease.org/rss/?r=1080&t=": "subsplease",
            "https://example.com/feed.xml": "other",
            "https://anibt.net.example.com/feed.xml": "other",
            "not a url": "other",
        }
        for url, expected in cases.items():
            with self.subTest(url=url):
                self.assertEqual(classify_subscription_source(url), expected)

    def test_bangumi_id_extraction_supports_mikan_and_anibt_names(self) -> None:
        self.assertEqual(extract_source_bangumi_id("https://mikanime.tv/RSS/Bangumi?bangumiId=3921"), 3921)
        self.assertEqual(extract_source_bangumi_id("https://anibt.net/rss/anime.xml?bgmId=543360"), 543360)
        self.assertEqual(extract_source_bangumi_id("https://example.test/?bgmId=-1"), 0)
        self.assertEqual(extract_source_bangumi_id("https://example.test/?bgmId=nope"), 0)


    def test_subscription_values_fill_bangumi_id_from_known_source_url(self) -> None:
        from app.schemas import SubscriptionCreate

        values = _subscription_values(
            SubscriptionCreate(
                name="AniBT anime",
                rss_url="https://anibt.net/rss/anime.xml?bgmId=543360&groupSlug=pre-s",
            )
        )
        self.assertEqual(values["bangumi_id"], 543360)

    def test_subscription_output_exposes_stable_source_fields(self) -> None:
        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            subscription = Subscription(name="AG", rss_url="https://api.animes.garden/feed.xml")
            db.add(subscription)
            db.commit()
            db.refresh(subscription)
            output = _subscription_out(db, subscription)
            self.assertEqual(output.source_type, "ag")
            self.assertEqual(output.source_label, "Anime Garden")
            self.assertEqual(subscription_source_label(subscription.rss_url), "Anime Garden")
        engine.dispose()

    def test_authenticated_catalog_route_payload(self) -> None:
        payload = list_subscription_sources()
        self.assertEqual(payload["sources"][0]["id"], "mikan")
        self.assertEqual(payload["sources"][-1]["id"], "other")

    def test_frontend_source_module_detects_hosts_and_fallbacks(self) -> None:
        module_path = ROOT / "app/static/subscription-sources.js"
        script = textwrap.dedent(
            f"""
            const assert = require('node:assert/strict');
            const sources = require({str(module_path)!r});
            const catalog = sources.normalizeCatalog({{
              sources: [
                {{ id: 'anibt', label: 'ANI.BT', hosts: ['anibt.net'] }},
                {{ id: 'ag', label: 'Anime Garden', hosts: ['animes.garden'] }},
                {{ id: 'other', label: '其它 RSS', hosts: [] }},
              ],
            }});
            assert.equal(sources.detectSource(catalog, 'https://anibt.net/rss/anime.xml').id, 'anibt');
            assert.equal(sources.detectSource(catalog, 'https://api.animes.garden/feed.xml').id, 'ag');
            assert.equal(sources.detectSource(catalog, 'https://anibt.net.example.com/feed.xml').id, 'other');
            assert.equal(sources.getSource(catalog, 'missing').id, 'other');
            assert.equal(sources.canUseDefaultFeed({{ default_feed_url: 'https://example.test/rss' }}), true);
            """
        )
        result = subprocess.run(
            ["node", "-e", script], cwd=ROOT, capture_output=True, text=True, check=False
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_add_menu_and_source_context_are_present(self) -> None:
        index = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
        script = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
        for source, label in (
            ("mikan", "Mikan"),
            ("anibt", "ANI.BT"),
            ("ag", "Anime Garden（AG）"),
            ("nyaa", "Nyaa"),
            ("subsplease", "SubsPlease"),
            ("other", "其它 RSS"),
        ):
            self.assertIn(f'data-subscription-source="{source}"', index)
            self.assertIn(label, index)
        for element_id in (
            "subscriptionSourceContext",
            "subscriptionSourceBadge",
            "subscriptionSourceOfficial",
            "subscriptionSourceHelp",
            "useDefaultSourceFeed",
        ):
            self.assertIn(f'id="{element_id}"', index)
        self.assertIn("/api/subscription-sources", script)
        self.assertIn("全站 RSS 可能包含大量条目", script)
        self.assertIn("source_label", script)


if __name__ == "__main__":
    unittest.main()
