from __future__ import annotations

import unittest

import httpx

from app.discovery import (
    DiscoveryService,
    build_dmhy_rss_url,
    parse_mikan_detail_html,
    parse_mikan_search_html,
)


MIKAN_SEARCH_HTML = """
<!doctype html><html><head><title>搜索结果 - Mikan Project</title></head><body>
<div id="sk-container"><div class="central-container"><ul>
  <li><a href="/Home/Bangumi/3822"><img alt="金牌得主 第二季"></a></li>
  <li><a href="/Home/Bangumi/3981">魔法少女奈叶 EXCEEDS Gun Blaze Vengeance</a></li>
  <li><a href="/Home/Bangumi/3822">详情</a></li>
</ul></div></div>
</body></html>
"""

MIKAN_DETAIL_HTML = """
<!doctype html><html><head><title>金牌得主 第二季 - Mikan Project</title></head><body>
<h1>金牌得主 第二季</h1>
<a href="/Home/PublishGroup/370">LoliHouse</a>
<a href="/Home/PublishGroup/513"><img alt="ANi"></a>
<section id="subgroup-777"></section>
</body></html>
"""

DMHY_RSS = b"""<?xml version='1.0' encoding='UTF-8'?>
<rss version='2.0'><channel>
<item>
<title>[LoliHouse] Medalist S2 - 01 [1080p][CHS]</title>
<link>https://share.dmhy.test/topics/view/123.html</link>
<guid>dmhy-123</guid>
<pubDate>Sat, 25 Jul 2026 12:00:00 +0000</pubDate>
<enclosure url='https://dl.dmhy.test/123.torrent' type='application/x-bittorrent'/>
</item>
</channel></rss>"""


class DiscoveryParserTests(unittest.TestCase):
    def test_mikan_search_extracts_unique_bangumi(self) -> None:
        results = parse_mikan_search_html(MIKAN_SEARCH_HTML, "https://mikan.test")
        self.assertEqual([item["bangumi_id"] for item in results], [3822, 3981])
        self.assertEqual(results[0]["title"], "金牌得主 第二季")
        self.assertEqual(results[0]["result_type"], "bangumi")

    def test_mikan_detail_extracts_groups_and_builds_rss(self) -> None:
        detail = parse_mikan_detail_html(
            MIKAN_DETAIL_HTML,
            "https://mikan.test",
            3822,
            "金牌得主 第二季",
        )
        groups = {group["subgroup_id"]: group for group in detail["groups"]}
        self.assertEqual(detail["title"], "金牌得主 第二季")
        self.assertEqual(groups[370]["name"], "LoliHouse")
        self.assertEqual(groups[513]["name"], "ANi")
        self.assertEqual(groups[777]["name"], "字幕组 #777")
        self.assertEqual(
            groups[370]["rss_url"],
            "https://mikan.test/RSS/Bangumi?bangumiId=3822&subgroupid=370",
        )
        self.assertEqual(groups[370]["preset"]["primary_rss_name"], "Mikan · LoliHouse")

    def test_dmhy_url_uses_keyword_rss(self) -> None:
        url = build_dmhy_rss_url("金牌 得主", "https://share.dmhy.test")
        self.assertIn("/topics/rss/rss.xml?", url)
        self.assertIn("keyword=%E9%87%91%E7%89%8C+%E5%BE%97%E4%B8%BB", url)
        self.assertIn("sort_id=2", url)


class DiscoveryServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "mikan.test" and request.url.path == "/Home/Search":
                return httpx.Response(200, text=MIKAN_SEARCH_HTML, request=request)
            if request.url.host == "mikan.test" and request.url.path == "/Home/Bangumi/3822":
                return httpx.Response(200, text=MIKAN_DETAIL_HTML, request=request)
            if request.url.host == "share.dmhy.test" and request.url.path == "/topics/rss/rss.xml":
                return httpx.Response(
                    200,
                    content=DMHY_RSS,
                    headers={"Content-Type": "application/rss+xml"},
                    request=request,
                )
            return httpx.Response(404, request=request)

        self.client = httpx.Client(transport=httpx.MockTransport(handler))
        self.service = DiscoveryService(
            client=self.client,
            mikan_bases=("https://mikan.test",),
            dmhy_base="https://share.dmhy.test",
            timeout=3,
        )

    def tearDown(self) -> None:
        self.client.close()

    def test_search_mikan_then_select_group(self) -> None:
        response = self.service.search("mikan", "金牌得主", limit=20)
        self.assertFalse(response["errors"])
        result = response["results"][0]
        self.assertEqual(result["bangumi_id"], 3822)

        detail = self.service.mikan_detail(
            result["bangumi_id"],
            result["base_url"],
            result["title"],
        )
        self.assertGreaterEqual(len(detail["groups"]), 2)
        self.assertTrue(detail["groups"][0]["preset"]["rss_url"].startswith("https://mikan.test/RSS/Bangumi"))

    def test_search_dmhy_returns_feed_and_release_presets(self) -> None:
        response = self.service.search("dmhy", "金牌得主", limit=20)
        self.assertFalse(response["errors"])
        self.assertEqual(response["results"][0]["result_type"], "feed")
        self.assertEqual(response["results"][0]["preset"]["name"], "金牌得主")
        release = response["results"][1]
        self.assertEqual(release["result_type"], "release")
        self.assertEqual(release["download_url"], "https://dl.dmhy.test/123.torrent")
        self.assertIn("Medalist", release["preset"]["sample_title"])

    def test_all_search_keeps_partial_results_and_reports_errors(self) -> None:
        def failing_handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "mikan.test":
                return httpx.Response(503, request=request)
            if request.url.host == "share.dmhy.test":
                return httpx.Response(200, content=DMHY_RSS, request=request)
            return httpx.Response(404, request=request)

        with httpx.Client(transport=httpx.MockTransport(failing_handler)) as client:
            service = DiscoveryService(
                client=client,
                mikan_bases=("https://mikan.test",),
                dmhy_base="https://share.dmhy.test",
            )
            response = service.search("all", "金牌得主", limit=10)
        self.assertTrue(any(item["provider"] == "dmhy" for item in response["results"]))
        self.assertTrue(any(error.startswith("Mikan：") for error in response["errors"]))


if __name__ == "__main__":
    unittest.main()
