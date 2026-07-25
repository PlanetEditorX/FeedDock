import unittest

from app.rss_parser import parse_feed
from app.models import Subscription
from app.rss_service import (
    apply_episode_offset,
    extract_download_url,
    match_title,
    parse_episode,
    preview_subscription,
    render_save_path,
)


class RSSServiceTests(unittest.TestCase):
    def test_keyword_matching(self):
        self.assertTrue(match_title("Example 1080p 简体", "1080p,简体", "合集")[0])
        self.assertFalse(match_title("Example 1080p 合集", "1080p", "合集")[0])
        self.assertFalse(match_title("Example 720p", "1080p,2160p", "")[0])

    def test_episode_parsing(self):
        self.assertEqual(parse_episode("[Group] Example - 03 [1080p]"), "3")
        self.assertEqual(parse_episode("Example EP12"), "12")
        self.assertEqual(parse_episode("Example 第7集"), "7")
        self.assertEqual(parse_episode("Example S02E09", r"S\d+E(\d+)"), "9")

    def test_download_url_prefers_torrent_enclosure(self):
        entry = {
            "link": "https://example.com/post/1",
            "enclosures": [{"href": "https://example.com/file.torrent", "type": "application/x-bittorrent"}],
        }
        self.assertEqual(extract_download_url(entry), "https://example.com/file.torrent")

    def test_extract_magnet(self):
        entry = {"summary": '<a href="magnet:?xt=urn:btih:ABC123&amp;dn=test">download</a>'}
        self.assertTrue(extract_download_url(entry).startswith("magnet:?"))

    def test_parse_rss(self):
        content = b"""<?xml version='1.0'?><rss version='2.0'><channel><item><title>Demo - 01 [1080p]</title><guid>x1</guid><link>https://example.com/post</link><enclosure url='https://example.com/1.torrent' type='application/x-bittorrent'/><pubDate>Sat, 25 Jul 2026 12:00:00 +0000</pubDate></item></channel></rss>"""
        entries = parse_feed(content)
        self.assertEqual(entries[0]["title"], "Demo - 01 [1080p]")
        self.assertEqual(extract_download_url(entries[0]), "https://example.com/1.torrent")

    def test_parse_atom(self):
        content = b"""<?xml version='1.0'?><feed xmlns='http://www.w3.org/2005/Atom'><entry><title>Demo EP02</title><id>x2</id><updated>2026-07-25T12:00:00Z</updated><link rel='alternate' href='https://example.com/post/2'/><link rel='enclosure' type='application/x-bittorrent' href='https://example.com/2.torrent'/></entry></feed>"""
        entries = parse_feed(content)
        self.assertEqual(entries[0]["id"], "x2")
        self.assertEqual(extract_download_url(entries[0]), "https://example.com/2.torrent")

    def test_advanced_rules_offset_and_custom_path(self):
        sub = Subscription(
            name="金牌得主 第二季",
            reference_title="金牌得主 (2025)",
            rss_url="https://example.com/feed.xml",
            include_keywords="",
            exclude_keywords="720\n\\d-\\d\n合集\n特别篇",
            episode_regex=r"\d+(\.5)?",
            episode_group=0,
            episode_offset=-13,
            total_episodes=9,
            season=2,
            custom_download_path="/vol2/1000/影视/金牌得主 (2025)/Season 2",
            save_path_template="{base}/{subscription}/Season {season}",
        )
        result = preview_subscription(
            sub,
            "[LoliHouse] 金牌得主 - 14 [1080p]",
        )
        self.assertTrue(result["matched"])
        self.assertEqual(result["parsed_episode"], "14")
        self.assertEqual(result["adjusted_episode"], "1")
        self.assertEqual(result["save_path"], "/vol2/1000/影视/金牌得主 (2025)/Season 2")

    def test_regex_and_global_exclusion(self):
        self.assertFalse(match_title("Demo 01-02 1080p", "", r"\d-\d", "")[0])
        matched, reason = match_title("金牌得主 剧场版 1080p", "", "", "剧场版")
        self.assertFalse(matched)
        self.assertIn("全局排除", reason)

    def test_decimal_episode_offset(self):
        self.assertEqual(parse_episode("Demo 13.5", r"\d+(\.5)?", 0), "13.5")
        self.assertEqual(apply_episode_offset("13.5", -13), "0.5")

    def test_path_traversal_is_confined(self):
        sub = Subscription(name="Demo", rss_url="https://example.com/feed.xml", save_path_template="{base}/../../etc")
        self.assertTrue(render_save_path(sub, "1").endswith("/Demo"))


if __name__ == "__main__":
    unittest.main()
