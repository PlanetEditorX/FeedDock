from __future__ import annotations

import unittest

import httpx

from app.discovery import (
    DiscoveryService,
    parse_mikan_catalog_html,
    parse_mikan_detail_html,
    parse_mikan_search_html,
)


MIKAN_CATALOG_HTML = """
<div class="sk-bangumi" data-dayofweek="1">
  <div class="row"><span>星期一</span></div>
  <ul>
    <li>
      <span class="js-bangumi-item" data-src="/images/Bangumi/202601/abc.jpg?width=240" data-bangumiid="3822"></span>
      <a class="an-text" title="金牌得主 第二季" href="/Home/Bangumi/3822">金牌得主 第二季</a>
      <div class="date-text">7/24/2026</div>
    </li>
    <li>
      <span data-src="https://cdn.mikan.test/3981.jpg" data-bangumiid="3981"></span>
      <a class="an-text" href="/Home/Bangumi/3981">魔法少女奈叶 EXCEEDS</a>
      <div class="date-text">7/25/2026</div>
    </li>
  </ul>
</div>
<div class="sk-bangumi" data-dayofweek="6">
  <div>星期六</div>
  <ul>
    <li>
      <span data-src="/images/Bangumi/681.jpg" data-bangumiid="681"></span>
      <a class="an-text" title="摩绪" href="/Home/Bangumi/681"></a>
    </li>
  </ul>
</div>
"""

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

MIKAN_MODERN_CATALOG_HTML = """
<div class="sk-bangumi" data-dayofweek="6">
  <div class="week-title">星期六</div>
  <div class="an-info-group">
    <span class="cover" style="background-image: url('/images/Bangumi/202607/681.jpg?width=240')"></span>
    <a href="/Home/Bangumi/681" title="摩绪"><span class="an-text">摩绪</span></a>
    <span class="date-text">7/24/2026</span>
  </div>
</div>
"""


MIKAN_CURRENT_CARD_HTML = """
<div class="sk-bangumi" data-dayofweek="6">
  <div class="week-title">星期六</div>
  <div class="detail">
    <div class="m-week-square">
      <div>
        <a href="/Home/Bangumi/3920" target="_blank" title="&#x6469;&#x7EEA;">
          <img data-src="/images/Bangumi/202604/edeef072.jpg?width=400&amp;height=400&amp;format=webp" alt="&#x6469;&#x7EEA;" class="b-lazy">
        </a>
        <div class="small-title ellipsis">&#x6469;&#x7EEA;</div>
      </div>
    </div>
  </div>
</div>
"""


MIKAN_OFFICIAL_DESKTOP_CARD_HTML = """
<div class="sk-bangumi" data-dayofweek="5">
  <div id="data-row-5" class="row">星期五</div>
  <div class="an-box animated fadeIn"><ul class="list-inline an-ul">
    <li>
      <span data-src="/images/Bangumi/200504/1df90634.jpg?width=400&amp;height=400&amp;format=webp"
            class="js-expand_bangumi b-lazy" data-bangumiid="681"
            data-bangumiindex="1" data-showsubscribed="false"></span>
      <div class="an-info">
        <div class="an-info-group">
          <div class="date-text">2026/07/23 更新</div>
          <a href="/Home/Bangumi/681" target="_blank" class="an-text"
             title="哆啦A梦">哆啦A梦</a>
        </div>
      </div>
    </li>
  </ul></div>
</div>
"""

MIKAN_MODERN_DETAIL_HTML = """
<!doctype html><html><head>
<meta charset="utf-8">
<meta content="noindex">
<title>Mikan Project - 金牌得主 第二季</title>
</head><body>
<div class="subgroup-text" id="370"><a href="/Home/PublishGroup/370">LoliHouse</a></div>
<table class="table"><tbody></tbody></table>
<div class="subgroup-text" id="513"><a>ANi</a></div>
<div class="subgroup-text" data-subgroupid="777">北宇治字幕组</div>
</body></html>
"""


class DiscoveryParserTests(unittest.TestCase):
    def test_mikan_catalog_groups_by_weekday_and_extracts_cover(self) -> None:
        rows = parse_mikan_catalog_html(
            MIKAN_CATALOG_HTML,
            "https://mikan.test",
            year=2026,
            season="夏",
        )
        self.assertEqual([row["weekday"] for row in rows], ["星期一", "星期六"])
        self.assertEqual(rows[0]["items"][0]["bangumi_id"], 3822)
        self.assertEqual(rows[0]["items"][0]["title"], "金牌得主 第二季")
        self.assertEqual(
            rows[0]["items"][0]["cover_url"],
            "https://mikan.test/images/Bangumi/202601/abc.jpg?width=240",
        )
        self.assertEqual(rows[0]["items"][0]["update_at"], "7/24/2026")

    def test_mikan_catalog_can_filter_title(self) -> None:
        rows = parse_mikan_catalog_html(
            MIKAN_CATALOG_HTML,
            "https://mikan.test",
            year=2026,
            season="夏",
            query="魔法少女",
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual([item["bangumi_id"] for item in rows[0]["items"]], [3981])

    def test_mikan_catalog_supports_modern_container_and_css_cover(self) -> None:
        rows = parse_mikan_catalog_html(
            MIKAN_MODERN_CATALOG_HTML,
            "https://mikan.test",
            year=2026,
            season="夏",
        )
        self.assertEqual(rows[0]["weekday"], "星期六")
        self.assertEqual(rows[0]["items"][0]["title"], "摩绪")
        self.assertEqual(
            rows[0]["items"][0]["cover_url"],
            "https://mikan.test/images/Bangumi/202607/681.jpg?width=240",
        )


    def test_mikan_catalog_supports_current_m_week_square_data_src(self) -> None:
        rows = parse_mikan_catalog_html(
            MIKAN_CURRENT_CARD_HTML,
            "https://mikanani.me",
            year=2026,
            season="夏",
        )
        item = rows[0]["items"][0]
        self.assertEqual(item["bangumi_id"], 3920)
        self.assertEqual(item["title"], "摩绪")
        self.assertEqual(
            item["cover_url"],
            "https://mikanani.me/images/Bangumi/202604/edeef072.jpg?width=400&height=400&format=webp",
        )


    def test_mikan_catalog_supports_official_desktop_span_cover(self) -> None:
        rows = parse_mikan_catalog_html(
            MIKAN_OFFICIAL_DESKTOP_CARD_HTML,
            "https://mikanani.me",
            year=2026,
            season="夏",
        )
        item = rows[0]["items"][0]
        self.assertEqual(rows[0]["weekday"], "星期五")
        self.assertEqual(item["bangumi_id"], 681)
        self.assertEqual(item["title"], "哆啦A梦")
        self.assertEqual(item["update_at"], "2026/07/23 更新")
        self.assertEqual(
            item["cover_url"],
            "https://mikanani.me/images/Bangumi/200504/1df90634.jpg?width=400&height=400&format=webp",
        )

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

    def test_mikan_detail_supports_subgroup_text_and_meta_without_name(self) -> None:
        detail = parse_mikan_detail_html(
            MIKAN_MODERN_DETAIL_HTML,
            "https://mikan.test",
            3822,
            "备用标题",
        )
        groups = {group["subgroup_id"]: group for group in detail["groups"]}
        self.assertEqual(detail["title"], "金牌得主 第二季")
        self.assertEqual(groups[370]["name"], "LoliHouse")
        self.assertEqual(groups[513]["name"], "ANi")
        self.assertEqual(groups[777]["name"], "北宇治字幕组")


class DiscoveryServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "mikan.test" and request.url.path == "/Home/BangumiCoverFlowByDayOfWeek":
                self.assertEqual(request.url.params["year"], "2026")
                self.assertEqual(request.url.params["seasonStr"], "夏")
                return httpx.Response(200, text=MIKAN_CATALOG_HTML, request=request)
            if request.url.host == "mikan.test" and request.url.path == "/Home/Search":
                return httpx.Response(200, text=MIKAN_SEARCH_HTML, request=request)
            if request.url.host == "mikan.test" and request.url.path == "/Home/Bangumi/3822":
                return httpx.Response(200, text=MIKAN_MODERN_DETAIL_HTML, request=request)
            if request.url.host == "mikan.test" and request.url.path == "/images/Bangumi/202601/abc.jpg":
                return httpx.Response(
                    200,
                    content=b"\x89PNG\r\n\x1a\nmock",
                    headers={"Content-Type": "image/png"},
                    request=request,
                )
            return httpx.Response(404, request=request)

        self.client = httpx.Client(transport=httpx.MockTransport(handler))
        self.service = DiscoveryService(
            client=self.client,
            mikan_bases=("https://mikan.test",),
            timeout=3,
        )

    def tearDown(self) -> None:
        self.client.close()

    def test_catalog_then_select_group(self) -> None:
        response = self.service.catalog(2026, "夏")
        self.assertEqual(response["year"], 2026)
        self.assertEqual(response["season"], "夏")
        result = response["rows"][0]["items"][0]
        self.assertEqual(result["bangumi_id"], 3822)
        self.assertTrue(result["cover_proxy_url"].startswith("/api/discovery/mikan/image?"))

        detail = self.service.mikan_detail(
            result["bangumi_id"],
            result["base_url"],
            result["title"],
        )
        self.assertGreaterEqual(len(detail["groups"]), 2)
        self.assertTrue(detail["groups"][0]["preset"]["rss_url"].startswith("https://mikan.test/RSS/Bangumi"))

    def test_cover_proxy_fetches_same_host_image(self) -> None:
        content, content_type = self.service.fetch_image(
            "https://mikan.test",
            "https://mikan.test/images/Bangumi/202601/abc.jpg?width=240",
        )
        self.assertTrue(content.startswith(b"\x89PNG"))
        self.assertEqual(content_type, "image/png")

    def test_cover_proxy_rejects_other_hosts(self) -> None:
        with self.assertRaisesRegex(ValueError, "不属于允许"):
            self.service.fetch_image("https://mikan.test", "https://example.com/cover.jpg")


    def test_catalog_uses_final_redirect_origin_for_relative_covers(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "mikanime.tv":
                target = "https://mikanani.me" + request.url.raw_path.decode("ascii")
                return httpx.Response(302, headers={"Location": target}, request=request)
            if request.url.host == "mikanani.me" and request.url.path == "/Home/BangumiCoverFlowByDayOfWeek":
                return httpx.Response(200, text=MIKAN_CURRENT_CARD_HTML, request=request)
            return httpx.Response(404, request=request)

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            service = DiscoveryService(
                client=client,
                mikan_bases=("https://mikanime.tv", "https://mikanani.me"),
            )
            response = service.catalog(2026, "夏")

        item = response["rows"][0]["items"][0]
        self.assertEqual(response["base_url"], "https://mikanani.me")
        self.assertEqual(item["base_url"], "https://mikanani.me")
        self.assertTrue(item["cover_url"].startswith("https://mikanani.me/images/"))
        self.assertIn("base_url=https%3A%2F%2Fmikanani.me", item["cover_proxy_url"])

    def test_cover_proxy_allows_redirect_between_configured_mikan_hosts(self) -> None:
        image_path = "/images/Bangumi/202604/edeef072.jpg"

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "mikanime.tv" and request.url.path == image_path:
                return httpx.Response(
                    302,
                    headers={"Location": "https://mikanani.me" + image_path + "?format=webp"},
                    request=request,
                )
            if request.url.host == "mikanani.me" and request.url.path == image_path:
                return httpx.Response(
                    200,
                    content=b"RIFFmockWEBP",
                    headers={"Content-Type": "image/webp"},
                    request=request,
                )
            return httpx.Response(404, request=request)

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            service = DiscoveryService(
                client=client,
                mikan_bases=("https://mikanime.tv", "https://mikanani.me"),
            )
            content, content_type = service.fetch_image(
                "https://mikanime.tv",
                "https://mikanime.tv" + image_path,
            )

        self.assertEqual(content, b"RIFFmockWEBP")
        self.assertEqual(content_type, "image/webp")

    def test_keyword_search_remains_available_as_fallback(self) -> None:
        response = self.service.search("金牌得主", limit=20)
        self.assertFalse(response["errors"])
        self.assertEqual(response["provider"], "mikan")
        self.assertEqual(response["results"][0]["bangumi_id"], 3822)

    def test_catalog_rejects_invalid_season(self) -> None:
        with self.assertRaisesRegex(ValueError, "季度仅支持"):
            self.service.catalog(2026, "雨季")

    def test_catalog_uses_fallback_mikan_domain(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "primary.test":
                return httpx.Response(503, request=request)
            return httpx.Response(200, text=MIKAN_CATALOG_HTML, request=request)

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            service = DiscoveryService(
                client=client,
                mikan_bases=("https://primary.test", "https://fallback.test"),
            )
            response = service.catalog(2026, "夏")
        self.assertEqual(response["base_url"], "https://fallback.test")
        self.assertTrue(response["errors"])


if __name__ == "__main__":
    unittest.main()
