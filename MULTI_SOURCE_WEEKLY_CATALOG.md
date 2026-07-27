# FeedDock 1.17.0 原站番剧目录与跨站状态

## 目标

FeedDock 的番剧发现页只展示目标站点实际提供的数据：

- Mikan：读取 Mikan 季度目录和番剧详情；
- ANI.BT：读取 ANI.BT 季度周历和字幕组 API；
- Anime Garden：读取 Anime Garden 当前活跃番剧和资源 API；
- 其它 RSS：保留手动订阅，不伪造番剧周历。

不同站点不再共用 `bangumi-data`、GitHub Raw、jsDelivr 或 Mikan 回退目录。一个站点不可用时，只影响该站点。

## 原站请求

### Mikan

沿用现有 Mikan 缓存服务：

```text
/Home/BangumiCoverFlowByDayOfWeek
/Home/Search
/Home/Bangumi/{mikan_id}
```

Mikan 的季度目录、字幕组和 RSS 均由 Mikan 原站生成。

### ANI.BT

季度周历：

```text
GET https://anibt.net/api/seasons/anime?season=2026-07
```

搜索：

```text
GET https://anibt.net/api/seasons/anime?query=标题
```

字幕组与最近资源：

```text
GET https://anibt.net/api/anime/groups?bgmId=<Bangumi Subject ID>
```

生成的订阅 RSS：

```text
https://anibt.net/rss/anime.xml?bgmId=<ID>&groupSlug=<字幕组 slug>
```

### Anime Garden

当前活跃番剧：

```text
GET https://api.animes.garden/subjects
```

资源与字幕组：

```text
GET https://api.animes.garden/resources?subject=<Bangumi Subject ID>&pageSize=200&duplicate=false
```

生成的订阅 RSS：

```text
https://api.animes.garden/feed.xml?subject=<ID>&fansub=<字幕组名称>
```

Anime Garden 原站接口提供的是当前活跃列表，而不是季度归档。FeedDock 仍使用统一的年份/季度控件，但会明确提示该选择不参与 Anime Garden 原站筛选。

## 独立缓存

缓存继续复用 SQLite 的 `mikan_cache_entries` 表，但键按站点隔离：

```text
mikan:catalog:2026:夏
source:catalog:anibt:2026:夏
source:catalog:ag:2026:夏
source:detail:anibt:<摘要>
source:detail:ag:<摘要>
```

操作含义：

- **读取缓存**：缓存存在时不访问网络；首次没有缓存时请求当前站点；
- **强制更新**：只访问当前站点，成功后覆盖该站点缓存；
- 更新失败且当前站点已有缓存：显示该站点旧缓存并标记错误；
- 更新失败且没有当前站点缓存：返回错误，不使用另一站点的数据冒充。

后台刷新同样从缓存参数读取 `source_id`，逐站点更新。

## 统一番剧身份

跨站状态优先使用 Bangumi Subject ID：

```text
bgm:<subject_id>
```

没有 Bangumi ID 时，使用 Unicode NFKC、大小写折叠和标点清理后的标题指纹。订阅还保存：

```text
source_type
source_anime_id
canonical_key
```

精确匹配顺序：

1. `canonical_key`；
2. 当前站点的 `source_type + source_anime_id`；
3. Bangumi Subject ID；
4. 中文、原文、英文和订阅标题别名。

程序启动时会为旧订阅回填这些身份字段。ANI.BT 与 Anime Garden 的 URL 参数可直接恢复 Bangumi ID；Mikan ID 不会被误当成 Bangumi Subject ID。

## 跨站订阅标识

目录接口为每个番剧返回：

```json
{
  "subscribed": true,
  "subscribed_here": false,
  "subscribed_sources": ["Mikan"],
  "subscription_badge": "Mikan 已订阅"
}
```

显示规则：

- 当前站点已订阅：`✓ 已订阅`；
- 其它站点已订阅：`Mikan 已订阅`；
- 当前和其它站点都已订阅：`✓ 已订阅 · Mikan 也已订阅`；
- 多个其它来源：`Mikan、Anime Garden 已订阅`。

新增、编辑或删除订阅后，前端会根据同一身份规则立即重算当前已打开的目录，不需要再次请求原站。

## 跨站隐藏

`anime_preferences` 表保存统一身份级别的隐藏状态：

```text
canonical_key
bangumi_id
title_normalized
hidden
reason
```

在任意站点隐藏同一番剧后，其他站点的匹配条目也会隐藏。取消隐藏会同时删除：

- 相同 canonical key 的偏好；
- 相同 Bangumi ID 的偏好；
- 相同标准化标题的旧偏好。

Mikan 原有的按星期隐藏 ID 仍兼容写入，升级后不会突然恢复旧版隐藏项目。

## API

```text
GET  /api/discovery/mikan/catalog
POST /api/discovery/mikan/catalog/refresh
GET  /api/discovery/mikan/{mikan_id}
POST /api/discovery/mikan/{mikan_id}/refresh

GET  /api/discovery/catalog/anibt
POST /api/discovery/catalog/anibt/refresh
GET  /api/discovery/catalog/anibt/detail

GET  /api/discovery/catalog/ag
POST /api/discovery/catalog/ag/refresh
GET  /api/discovery/catalog/ag/detail

PUT  /api/discovery/preferences/hidden
```

## 数据库升级

1.17.0 启动时自动增加：

```text
subscriptions.source_type
subscriptions.source_anime_id
subscriptions.canonical_key
anime_preferences 表
```

迁移只增加字段和表，不删除订阅、RSS 指纹、下载条目或旧缓存。
