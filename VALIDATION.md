# FeedDock v1.9.1 验证报告

## 自动化验证

- 71 项 pytest 测试通过。
- Python 全项目编译通过。
- JavaScript `node --check` 通过。
- Docker Compose、飞牛 Compose 和 GitHub Actions YAML 解析通过。
- FastAPI 登录、配置、订阅、清理接口和数据库迁移冒烟测试通过。

## 本次重点覆盖

- TMDB/Bangumi 元数据选择后订阅名称包含年份。
- 同一标题不会重复附加年份。
- 无集数预览使用 E01 演示，不出现 `Eunknown`。
- 实际下载仍要求识别到真实集数才生成改名目标。
- qBittorrent、订阅和刮削使用同一根目录。
- 保存 qBittorrent 根目录时，现有订阅路径同步更新。
- 路径穿越回退到安全默认目录。
- 订阅卡片显示海报和简介。
- qBittorrent 达到 100% 后才触发自动刮削。
- 自动刮削状态、完成进度和时间持久化。
- 最近条目安全隐藏且保留去重指纹。
- 系统日志清空接口。
- 新订阅默认启用本地 NFO/图片；升级迁移默认开启。
- 飞牛 Compose 默认 `PUID=0`、`PGID=0`。
- 入口脚本对 `/data`、`/media` 进行实际写权限检测。

## 保留功能

- Mikan 官网目录解析与 240×320 WebP 本地优先封面缓存。
- 每星期过滤、折叠和浏览器状态记忆。
- 手动、TMDB、Bangumi、自动命名模式。
- 总集数同步和手动锁定。
- qBittorrent 单视频与字幕安全改名。
- 本地 NFO、海报、背景图和 Emby 刷新通知。

## 说明

当前验证环境没有 Docker CLI，因此没有在本地启动真实容器；Dockerfile、入口脚本、Compose 和 GitHub Actions 已完成静态及自动化验证。正式部署后应查看容器日志，确认 `/data` 和 `/media` 写权限检查通过。
