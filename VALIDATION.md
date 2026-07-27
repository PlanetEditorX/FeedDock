# FeedDock 1.17.3 验证报告

## 功能验证

- “刷新全部订阅”点击后直接执行，不再显示二次确认；
- qBittorrent 返回 `Ok.` 但标签回查为空时判定失败；
- 标签回查成功时保存实际任务名称、状态和哈希；
- HTTP/HTTPS `.torrent` 由 FeedDock 下载后以原始文件上传；
- Magnet 继续通过 URL 添加，并执行相同标签回查；
- 历史 `queued` 记录超过两分钟仍找不到任务时转为可重试错误；
- 日志不包含完整 magnet、Torrent URL 或 passkey。

## 自动化测试

- Python `unittest`：147 项通过；
- 覆盖 qBittorrent `Ok.` 假成功、任务标签回查、原始 Torrent 文件上传；
- 覆盖新订阅首次刷新、推送日志、失败重试和并发等待；
- 覆盖旧版假成功任务自动转为可重试错误；
- 覆盖登录、订阅管理、原站番剧目录、跨站状态、通知、设置和数据库兼容。

## 静态检查

- Python 全项目编译通过；
- 6 个 JavaScript 文件通过 `node --check`；
- Docker Compose、飞牛 Compose 和 GitHub Actions YAML 解析通过；
- 主页面 126 个 HTML ID 均唯一；
- 运行版本和静态资源缓存参数均为 `1.17.3`；
- `git diff --check` 通过。

## 外部服务边界

当前环境未连接用户的真实 qBittorrent 和私有 RSS 站点。qBittorrent WebUI API 行为通过本地模拟服务验证，包含登录、添加、按标签查询任务、保存哈希和未查到任务的失败路径。

官方 qBittorrent WebUI API 支持通过 `torrents` 字段上传原始 Torrent 文件，也支持使用 `tag` 参数查询任务列表。FeedDock 1.17.3 同时使用这两项能力确认任务真实存在。

## 数据库

不新增数据库字段，不需要手工迁移。现有 `feed_items.torrent_hash` 用于保存 qBittorrent 回查得到的任务哈希。
