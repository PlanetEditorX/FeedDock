# FeedDock v1.9.0 验证报告

## 自动化验证

- 67 项 pytest 测试通过。
- Python 全项目编译通过。
- JavaScript `node --check` 通过。
- Docker Compose、飞牛 Compose 和 GitHub Actions YAML 解析通过。
- FastAPI 登录、配置、订阅预览和数据库迁移冒烟测试通过。

## 覆盖功能

- Mikan 官网桌面目录真实结构解析。
- 240×320 WebP 封面地址和本地优先缓存。
- 每星期持久隐藏过滤。
- 手动、TMDB、Bangumi 与自动命名优先级。
- Emby 目录和 `SxxExx` 文件名生成。
- 路径穿越限制。
- qBittorrent 添加任务的 `rename`/`tags` 参数。
- 单视频及同名前缀字幕的 qBittorrent 内部重命名。
- 多视频合集安全跳过。
- 总集数同步与手动锁定。
- 本地 `tvshow.nfo`、`season.nfo` 写入。
- 板块收缩状态本地持久化代码检查。

## 安全与兼容

- 数据库只执行新增字段迁移。
- 旧订阅默认不开启自动重命名。
- 密钥接口不返回 Token/API Key 原文。
- 本地刮削只允许映射到配置的下载根目录之下。
- FeedDock 使用 qBittorrent API 重命名，不直接移动活动文件。
