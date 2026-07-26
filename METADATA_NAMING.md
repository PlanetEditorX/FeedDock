# FeedDock 元数据、命名、路径与刮削设计

## 1. 数据源职责

### Mikan

提供季度番剧目录、字幕组 RSS 和原始发布标题。Mikan 不作为 Emby 外部 ID 来源。

### Bangumi

提供动漫中文名、原名、放送日期、简介、封面和话数。公开读取通常无需 Token。

### TMDB

提供 Emby 使用的 TMDB ID、规范标题、年份、电视剧季度、简介、海报、背景图和季度总集数。

### Emby

读取 FeedDock 生成的规范目录、`[tmdbid=...]`、NFO 和本地图片，也可以继续使用自己的在线元数据提供者补充演员、评分和剧集简介。

## 2. 年份与名称

选择 TMDB 或 Bangumi 搜索结果时，FeedDock 会统一写入：

```text
标题 (年份)
```

例如：

```text
从0位居民开始的边境领主大人 (2026)
```

该名称会显示在订阅编辑器和订阅卡片中。生成媒体目录时会自动避免重复年份，因此不会出现 `(2026) (2026)`。

名称模式：

| 模式 | 名称来源 |
|---|---|
| auto | 手动标题 → TMDB 标题 → Bangumi 标题 → 订阅名称 |
| manual | 手动规范标题 |
| tmdb | TMDB 标题 |
| bangumi | Bangumi/参考标题 |

非法文件名字符会替换为下划线。

## 3. 唯一下载根目录

qBittorrent、订阅路径和本地刮削必须使用相同的容器路径，默认：

```text
/media
```

网页保存 qBittorrent 根目录时，FeedDock 会同步所有订阅的根目录及刮削根目录。每个订阅不再使用第二套独立根目录；自定义目录结构应通过模板完成：

```text
{base}/{media_folder}/Season {season:02}
```

任何模板路径穿越都会回退到安全的默认媒体目录。

## 4. Emby 目录与文件名

电视剧目录：

```text
从0位居民开始的边境领主大人 (2026) [tmdbid=296437]/Season 01
```

剧集文件：

```text
从0位居民开始的边境领主大人 (2026) - S01E01.mkv
```

电影目录：

```text
电影标题 (2026) [tmdbid=123456]
```

当预览标题中没有集数时，FeedDock 使用 `E01` 作为明确标注的演示值。真实下载不会使用该演示值；只有成功识别 RSS 集数后才生成自动改名目标。

## 5. qBittorrent 安全重命名

FeedDock 不直接对活动任务执行系统 `mv`。它使用 qBittorrent WebUI API：

- 添加任务并传递 `savepath`、`rename`、唯一 `tags`；
- 查询标签对应任务及下载进度；
- 获取种子内部文件列表；
- 单视频任务通过 `renameFile` 改名；
- 同目录、同原文件名前缀的字幕同步改名；
- 多视频合集标记为 `manual_required`，不猜测集数。

## 6. 总集数

- TMDB：优先读取所选季度 `episodes` 数量；必要时读取季度汇总字段；
- Bangumi：读取条目话数，缺失时回退到 episode API 总数；
- 手动锁定：`total_episodes_locked=true` 后不被同步覆盖。

## 7. 下载完成后自动刮削

新订阅默认 `scrape_enabled=true`。后台每 2 分钟检查带 FeedDock 标签的 qBittorrent 任务：

1. 读取进度；
2. 必要时执行安全重命名；
3. 只有进度达到 100% 才开始本地刮削；
4. 成功后记录完成时间、刮削状态和刮削时间；
5. 一批任务完成后可通知 Emby 刷新。

刮削生成：

```text
tvshow.nfo
poster.jpg
backdrop.jpg
Season 01/season.nfo
season01-poster.jpg
```

电影生成：

```text
movie.nfo
poster.jpg
backdrop.jpg
```

本地有效图片不会重复下载。

## 8. 权限

飞牛默认以 `PUID=0`、`PGID=0` 运行。入口脚本不会递归修改整个媒体库，只检查 `/data` 与 `/media` 是否可写。需要非 root 运行时，必须保证所选 UID/GID 对宿主机挂载目录具备读写权限。

## 9. 清理策略

“清理最近条目”只设置隐藏标记，保留 `subscription_id + fingerprint` 唯一记录，因此旧 RSS 条目不会重复下载。“清理系统日志”会真实删除日志表中的当前记录。

## 10. 限制

- 多视频合集仍需要人工确认每个文件对应的集数；
- Bangumi 与 TMDB 的季度划分可能不同，保存前应确认季编号和总集数；
- FeedDock 不下载或分发媒体，只处理用户配置的 RSS、下载器任务和本地元数据。
