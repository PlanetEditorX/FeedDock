# FeedDock 1.17.5 验证报告

## 功能验证

- 下载完成后会先同步外部元数据，再写入媒体目录；
- 电视番剧写入 `tvshow.nfo`、`season.nfo`、剧集同名 NFO、海报、背景图和季海报；
- 电影写入 `movie.nfo`、电影文件同名 NFO、海报和背景图；
- NFO 包含标题、原始标题、简介、年份、首播日期、评分和可用的 TMDB/Bangumi/AniList ID；
- 图片仅接受图片响应，单张限制 25 MiB；
- 已存在图片会复用，避免每集完成后重复下载；
- 下载目录越过统一媒体根目录时拒绝写入；
- 写入采用临时文件、`fsync` 和原子替换；
- “刷新 → 刮削已完成媒体”可以批量补写历史任务；
- 旧版已完成条目通过一次性迁移进入刮削补写队列；
- 本地刮削失败只影响刮削状态，不改变下载完成状态；
- 日志包含订阅 ID、条目 ID、媒体目录和生成文件列表。

## 自动化与静态验证

- 151 项自动化测试通过；
- Python 全项目编译通过；
- 6 个 JavaScript 文件语法检查通过；
- Docker Compose、飞牛 Compose 和 GitHub Actions YAML 解析通过；
- 128 个页面 HTML ID 均唯一；
- FastAPI 导入与运行版本 `1.17.5` 检查通过；
- 1.17.4 数据库升级后，已完成条目被标记为 `scrape_status=pending`；
- 迁移标记 `migration:1.17.5:local-scrape-backfill` 写入成功。

## 环境限制

当前环境没有真实 qBittorrent、TMDB、Bangumi、AniList 或媒体服务器。外部元数据和图片下载使用模拟响应验证；NFO、图片、清单和目录越界保护在临时真实文件系统中完成验证。未执行 Docker 镜像构建。
