# FeedDock 元数据、命名与刮削设计

## 1. 数据源职责

### Mikan

负责季度番剧目录、字幕组 RSS 和原始下载标题。Mikan 不作为 Emby 外部 ID 来源。

### Bangumi

负责动漫中文名、日文名、放送日期、简介、封面和话数。公开读取通常无需 Token。

### TMDB

负责 Emby 识别使用的 TMDB ID、规范标题、年份、电视剧季度信息、海报和背景图。TMDB 搜索需要 Read Access Token。

### Emby

负责最终媒体库识别、演员、剧集简介、评分和在线图片。FeedDock 可以生成本地 NFO，也可以只提供规范目录与 `[tmdbid=...]` 让 Emby 自己刮削。

## 2. 名称选择

| 模式 | 使用名称 |
|---|---|
| auto | 手动标题 → TMDB 标题 → Bangumi 标题 → 订阅名称 |
| manual | 手动规范标题 |
| tmdb | TMDB 标题 |
| bangumi | Bangumi/参考标题 |

非法文件名字符 `\\ / : * ? " < > |` 会替换为下划线，防止目录穿越和跨平台文件名错误。

## 3. Emby 目录

电视剧：

```text
{title} ({year}) [tmdbid={tmdb_id}]/Season {season:02}
```

剧集：

```text
{title} - S{season:02}E{episode:02}
```

电影：

```text
{title} ({year}) [tmdbid={tmdb_id}]
```

## 4. qBittorrent 安全重命名

FeedDock 不直接对活动任务执行系统 `mv`。它使用 WebUI API：

- 添加任务：`/api/v2/torrents/add`；
- 查询标签任务：`/api/v2/torrents/info?tag=...`；
- 获取文件：`/api/v2/torrents/files`；
- 改名：`/api/v2/torrents/renameFile`。

一个 RSS 条目对应一个唯一标签。磁力元数据未完成时不断重试；多视频合集不会自动猜测。

## 5. 总集数

- TMDB：读取所选季度的 `episodes` 数量。
- Bangumi：读取 `total_episodes`/`eps`，缺失时读取 episode 列表总数。
- 手动锁定：`total_episodes_locked=true` 后不覆盖。

## 6. 本地刮削文件

电视剧：

```text
tvshow.nfo
poster.jpg
backdrop.jpg
Season 02/season.nfo
season02-poster.jpg
```

电影：

```text
movie.nfo
poster.jpg
backdrop.jpg
```

NFO 中写入标题、年份、简介、首播日期、TMDB ID、Bangumi ID。TMDB ID 存在时作为默认唯一 ID。

## 7. 限制

- 多视频合集需要人工处理，因为单个 RSS 集数不能安全映射合集内全部文件。
- 本地刮削要求 qBittorrent 远程路径能够映射到 FeedDock 容器内媒体目录。
- Bangumi 与 TMDB 的季度划分可能不同，保存前应确认季编号和总集数。
- FeedDock 不下载或分发媒体，只处理用户提供的 RSS 和下载器任务。
