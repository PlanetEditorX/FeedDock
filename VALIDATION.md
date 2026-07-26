# FeedDock v1.10.1 验证报告

验证目标：在不改变 RSS、元数据、下载和重命名主流程的前提下，移除内置刮削。

结果：

- 76 项自动化测试全部通过；
- 登录与首次改密通过；
- 添加、编辑、删除订阅通过；
- Mikan 目录、缓存、封面和星期过滤通过；
- TMDB/Bangumi/AniList 元数据与季度识别通过；
- RSS/Atom、过滤、集数偏移和路径防穿越通过；
- 外部 qBittorrent 推送与内部文件重命名通过；
- 定时下载、代理、手动更新检查和 DEBUG 日志通过；
- Python 编译、JavaScript 语法、Compose 和 GitHub Actions YAML 检查通过；
- `app/scraper.py`、TMM/Emby API 路由、刮削前端控件和 `/media` FeedDock 挂载均不存在；
- 旧 SQLite 刮削列保留为兼容字段，但运行时不读取。
