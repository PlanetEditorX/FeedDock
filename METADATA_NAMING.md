# FeedDock 元数据与规范命名

FeedDock 的元数据功能只服务于**识别、命名和总集数同步**，不执行本地媒体刮削。

## 来源

### TMDB

用于：规范标题、年份、季号、指定季度总集数、海报、简介和 TMDB ID。

### Bangumi

用于：中文/日文标题、放送日期、动漫话数、海报和简介。

### AniList

用于：动漫候选搜索、年份、季度、话数和封面。

## 季度识别

- `title`：从“第二季”“Season 2”“S02”等标题文本识别；
- `latest`：选择 TMDB 最新已播正式季度，排除 Season 0；
- `manual`：使用手动季编号。

## 目录与文件名

```text
{base}/{media_folder}/Season {season:02}
{title} - S{season:02}E{episode:02}
```

`media_folder` 在有 TMDB ID 时类似：

```text
金牌得主 (2025) [tmdbid=123456]
```

## 重命名边界

FeedDock 只通过 qBittorrent API 重命名，避免破坏做种状态：

- 单视频种子：自动改名；
- 同名前缀字幕：同步改名；
- 多视频合集：不自动猜测，标记手动处理；
- 无法识别集数：不执行实际 E01 重命名，预览中的 E01 仅为模板示例。

## 外部刮削

规范命名后，使用飞牛影视、Emby、Jellyfin、Plex 或其他媒体管理工具扫描媒体目录。FeedDock 不调用这些工具，也不写 NFO 或图片。
