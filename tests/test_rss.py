from app.rss import extract_episode, item_allowed, parse_feed


def test_rss_parse_and_rules():
    xml = b"""<?xml version='1.0'?><rss><channel><item><title>[Group] Demo - 14 [1080p]</title><link>magnet:?xt=urn:btih:abc</link></item></channel></rss>"""
    items = parse_feed(xml)
    assert len(items) == 1
    assert items[0].download_url.startswith("magnet:")
    assert item_allowed(items[0].title, "Demo", "720\n合集", "剧场版")
    assert extract_episode(items[0].title, r"\d+(\.5)?", 0, -13) == 1
