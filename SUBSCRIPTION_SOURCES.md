# FeedDock 1.16.1 订阅站点说明

“添加 → 添加订阅”现包含：

1. Mikan
2. ANI.BT
3. Anime Garden（AG）
4. Nyaa
5. SubsPlease
6. 其它 RSS

前五个站点进入统一的“番剧周历”页面，均支持搜索、读取缓存、强制更新、按星期浏览、资源详情缓存和订阅状态标识。其它 RSS 进入通用编辑器。

详细的周历和缓存设计见 [`MULTI_SOURCE_WEEKLY_CATALOG.md`](MULTI_SOURCE_WEEKLY_CATALOG.md)。

## Mikan

Mikan 使用自身季度目录，并提供字幕组维度的 RSS：

- 按年份、季度和标题搜索；
- 按星期展示；
- 读取缓存和强制更新；
- 查看字幕组及最近发布；
- 自动带入名称、RSS、Mikan 番剧 ID 和字幕组名称；
- 已订阅番剧显示“已订阅”。

## ANI.BT

ANI.BT 使用共享周历。标准数据使用 Bangumi 条目 ID；当共享镜像失败并回退 Mikan 时，使用 Mikan 番剧 ID：

- 全部发布；
- 1080p；
- 720p。

RSS 形式：

```text
# 标准周历
https://anibt.net/rss/anime.xml?bgmId=543360

# Mikan 回退周历
https://anibt.net/rss/anime.xml?bangumiId=3921
```

ANI.BT 官方兼容 Mikan 的 `bangumiId` 参数。只有 Bangumi ID 和 Mikan ID 都不存在时，周历卡片才会禁用。

## Anime Garden

Anime Garden 使用共享周历，根据标题生成过滤 RSS：

```text
https://api.animes.garden/feed.xml?filter=...
```

FeedDock 不会在周历入口中使用未过滤的全站 Feed。资源详情缓存过滤后的最近条目。

## Nyaa

Nyaa 使用原始日文或英文标题生成动画分类 RSS，并提供：

- 英文字幕动画；
- 可信发布；
- 日文原盘。

示例形式：

```text
https://nyaa.si/?page=rss&q=TITLE&c=1_2&f=0
```

Nyaa 的标题和发布组规则变化较大，保存前建议检查资源预览，并按需要增加包含、排除或字幕组关键词。

## SubsPlease

SubsPlease 提供分辨率级 RSS：

- 1080p；
- 720p；
- SD；
- 全部分辨率。

FeedDock 会自动把番剧英文标题写入包含规则，因为这些 RSS 本身不是单番剧 Feed。资源预览也会按标题别名过滤。

## 其它 RSS

接受标准 RSS 2.0、Atom 或 RDF。FeedDock 会优先使用 enclosure、磁力链接和种子下载链接。

未知站点在订阅列表中优先显示用户填写的主 RSS 名称，不会被强制覆盖成“其它 RSS”。

## 来源识别

来源识别使用 URL 的真实主机名边界：

- `anibt.net` 和其子域名可识别为 ANI.BT；
- `anibt.net.example.com` 不会被误识别；
- 无效 URL 和未知主机归类为其它 RSS。

当前 `source_type`：

```text
mikan
anibt
ag
nyaa
subsplease
other
```

## 安全默认值

- 全站 RSS 不会在周历模式中自动订阅；
- 点击番剧后先展示实际 RSS、包含规则和资源预览；
- 用户仍可在保存前修改规则、下载目录和命名设置；
- FeedDock 不提供、存储或分发媒体内容。

## 升级

1.16.0 → 1.16.1 不需要数据库迁移。升级后建议强制刷新浏览器；首次刷新非 Mikan 周历时会自动采用多镜像和 Mikan 回退逻辑。
