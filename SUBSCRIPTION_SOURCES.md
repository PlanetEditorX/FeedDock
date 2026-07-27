# FeedDock 1.15.0 订阅站点说明

FeedDock 的“添加”菜单将订阅入口拆分为：

1. Mikan
2. ANI.BT
3. Anime Garden（AG）
4. 其它 RSS

站点入口不仅改变标题和占位文字，也会加载对应的官方地址、RSS 说明、安全提示和来源识别规则。

## Mikan

入口：`添加 → Mikan`

Mikan 使用 FeedDock 已有的季度番剧目录：

- 按年份、季度和标题搜索番剧；
- 查看字幕组及其 RSS；
- 自动带入番剧名称、RSS、Bangumi ID 和字幕组名称；
- 已经订阅的番剧显示“已订阅”；
- 不提供“全站 RSS”快捷填充，避免一次处理大量无关条目。

支持识别以下主机及其子域名：

- `mikanime.tv`
- `mikanani.me`
- `mikanani.kas.pub`
- `mikan.tangbai.cc`

## ANI.BT

入口：`添加 → ANI.BT`

表单会显示：

- ANI.BT 官方站点；
- RSS 主入口文档；
- 推荐 URL 格式；
- 全站磁力 RSS 的风险提示；
- 经用户确认后填入全站 RSS 的按钮。

推荐的单番剧 RSS 形式：

```text
https://anibt.net/rss/anime.xml?bgmId=543360&groupSlug=pre-s
```

全站磁力 RSS：

```text
https://anibt.net/rss/magnets.xml
```

全站流不会默认写入表单。点击“使用全站 RSS”时会再次确认，并提醒先配置匹配和排除规则。

ANI.BT URL 中的 `bgmId` 或兼容的 `bangumiId` 会自动写入订阅的 Bangumi ID；用户仍可在保存前修改。

## Anime Garden（AG）

入口：`添加 → Anime Garden（AG）`

表单会显示：

- Anime Garden 官方站点；
- 项目/API 说明；
- 过滤 RSS 地址格式；
- 未过滤全站 feed 的风险提示；
- 经用户确认后填入全站 feed 的按钮。

推荐从 Anime Garden 资源页生成带筛选条件的 RSS，例如：

```text
https://api.animes.garden/feed.xml?filter=...
```

全站 feed：

```text
https://api.animes.garden/feed.xml
```

全站 feed 不会默认写入表单，以免新订阅首次检查时处理大量无关资源。

## 其它 RSS

入口：`添加 → 其它 RSS`

接受标准 RSS 2.0、Atom 或 RDF 地址。FeedDock 的解析器会优先使用：

- RSS `<enclosure url="...">`；
- Atom `rel="enclosure"`；
- 条目中的磁力链接或种子下载链接。

未知站点在订阅列表中优先显示用户填写的“主 RSS 名称”，而不是强制显示“其它 RSS”。

## 来源识别安全性

来源识别只比较 URL 的真实主机名边界：

- `anibt.net` 和 `rss.anibt.net` 可识别为 ANI.BT；
- `anibt.net.example.com` 不会被误识别；
- 无效 URL 和未知主机统一归类为其它 RSS。

前端和后端都使用同一套来源目录语义。后端在订阅 API 中返回：

```json
{
  "source_type": "anibt",
  "source_label": "ANI.BT"
}
```

当前来源类型：`mikan`、`anibt`、`ag`、`other`。

## API

### 获取订阅站点目录

```http
GET /api/subscription-sources
```

需要管理员登录。响应包含每个站点的：

- ID 和显示名称；
- 描述；
- RSS 名称和占位格式；
- 官方地址和帮助地址；
- 可选全站 RSS；
- 允许识别的主机；
- Mikan 专用目录视图；
- 安全提示。

## 升级说明

从 1.14.0 升级到 1.15.0：

- 不增加数据库字段；
- 不修改现有订阅和条目；
- 来源类型由主 RSS URL 动态计算；
- 老订阅在刷新页面后自动显示新的来源标签；
- 静态资源缓存参数升级为 `v=1.15.0`，建议升级后强制刷新一次浏览器。
