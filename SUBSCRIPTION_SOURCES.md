# FeedDock 1.17.0 订阅站点

## 添加订阅菜单

```text
添加订阅
├── Mikan
├── ANI.BT
├── Anime Garden（AG）
└── 其它 RSS
```

Mikan、ANI.BT 和 Anime Garden 进入统一番剧列表页面；其它 RSS 进入手动编辑器。

## Mikan

- 原站季度番剧目录；
- 按星期展示；
- 标题搜索；
- 目录与详情独立缓存；
- 展开番剧后读取原站字幕组与 RSS；
- 保留 Mikan 封面缓存和旧版按星期隐藏设置。

## ANI.BT

- 直接读取 `anibt.net/api/seasons/anime`；
- 支持原站季度列表和标题搜索；
- 过滤没有 RSS 发布的番剧；
- 评分降序、按星期分组；
- 展开后读取 `api/anime/groups`；
- 为每个字幕组创建 `rss/anime.xml?bgmId=...&groupSlug=...`。

FeedDock 不再默认填入 ANI.BT 全站磁力 RSS。

## Anime Garden

- 直接读取 `api.animes.garden/subjects`；
- 使用原站 `activedAt` 计算星期；
- 展开后读取 `resources?subject=...`；
- 按字幕组聚合最近资源；
- 为每个字幕组创建 `feed.xml?subject=...&fansub=...`。

Anime Garden 提供当前活跃番剧，不提供与 Mikan 相同的季度归档，因此年份与季度选择仅保持统一界面，不改变原站返回范围。

## 其它 RSS

用于标准 RSS 2.0、Atom、RDF 或其它带磁力/种子附件的订阅。Nyaa、SubsPlease 等没有稳定原生星期番剧目录的来源仍可从这里手动添加，但不会在主菜单中伪装成周历站点。

## 来源识别

订阅来源按 URL 主机名边界识别：

```text
mikanime.tv / mikanani.me / Mikan 镜像 → mikan
anibt.net                                  → anibt
animes.garden                              → ag
其它                                       → other
```

`anibt.net.example.com` 不会被误识别成 ANI.BT。

## 订阅身份

创建订阅时保存：

```text
source_type
source_anime_id
canonical_key
bangumi_id（原站可提供时）
```

这些字段用于跨站显示 `Mikan 已订阅`、`ANI.BT 已订阅` 和跨站隐藏，不依赖 RSS URL 参数顺序。
