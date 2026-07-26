# FeedDock 元数据与规范命名

## 元数据用途

TMDB、Bangumi 和 AniList 只用于：

- 规范标题；
- 首播年份；
- 季度；
- 总集数；
- 简介；
- 页面海报；
- TMDB/Bangumi/AniList ID。

FeedDock 不会根据这些数据生成 NFO，也不会写入媒体目录。

## TMDB 季度

支持三种模式：

- `title`：从“第二季”“Season 2”“S02”等标题文字识别；
- `latest`：选择最高的已播正式季度，排除 Season 0；
- `manual`：手动指定季号。

## 规范目录

默认电视剧目录：

```text
{base}/{media_folder}/Season {season:02}
```

默认文件名：

```text
{title} - S{season:02}E{episode:02}
```

示例：

```text
/media/从0位居民开始的边境领主大人 (2026) [tmdbid=296437]/Season 01/
从0位居民开始的边境领主大人 (2026) - S01E03.mkv
```

FeedDock 通过 qBittorrent Web API 修改任务内部文件名，不直接移动媒体文件。

## 未识别集数

预览时使用 E01 作为格式示例，但实际 RSS 条目未识别集数时不会强行重命名为 E01。应调整集数正则、捕获组或偏移值。
