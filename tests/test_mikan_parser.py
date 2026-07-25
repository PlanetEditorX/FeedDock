from app.mikan import parse_catalog_html


def test_cover_card_outside_weekday_section_is_merged():
    content = """
    <div class="sk-bangumi" data-dayofweek="4">
      <ul><li>
        <a href="/Home/Bangumi/681" title="哆啦A梦">哆啦A梦</a>
        <span>2026/07/23 更新</span>
      </li></ul>
    </div>
    <div class="detail">
      <div class="m-week-square">
        <div>
          <a href="/Home/Bangumi/681" target="_blank" title="哆啦A梦">
            <img data-src="/images/Bangumi/202604/edeef072.jpg?width=400&amp;height=400&amp;format=webp" alt="哆啦A梦" class="b-lazy">
          </a>
          <div class="small-title ellipsis">哆啦A梦</div>
        </div>
      </div>
    </div>
    """
    items = parse_catalog_html(content, "https://mikanani.me/Home/BangumiCoverFlowByDayOfWeek?year=2026")
    assert len(items) == 1
    assert items[0]["bangumi_id"] == 681
    assert items[0]["weekday"] == 4
    assert items[0]["title"] == "哆啦A梦"
    assert items[0]["cover_url"] == "https://mikanani.me/images/Bangumi/202604/edeef072.jpg?width=400&height=400&format=webp"
    assert items[0]["cover_proxy_url"].startswith("/api/discovery/mikan/image?url=")


def test_relative_cover_uses_final_response_domain():
    content = """
    <div class="sk-bangumi" data-dayofweek="2">
      <a href="/Home/Bangumi/3920" title="摩绪">摩绪</a>
    </div>
    <div class="m-week-square">
      <a href="/Home/Bangumi/3920"><img data-src="/images/Bangumi/202604/edeef072.jpg"></a>
    </div>
    """
    item = parse_catalog_html(content, "https://mikanani.me/Home/BangumiCoverFlowByDayOfWeek")[0]
    assert item["cover_url"].startswith("https://mikanani.me/images/")
