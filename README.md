# FeedDock

FeedDock 是面向自托管环境的 RSS 订阅、qBittorrent 下载编排、规范命名、元数据旁车文件和通知管理工具。运行版本由容器镜像元数据提供。

使用前请阅读 [免责声明](DISCLAIMER.md)。完整文档见 [docs/README.md](docs/README.md)，版本变化见 [CHANGELOG.md](CHANGELOG.md)。

## 主要能力

- Mikan、ANI.BT、Anime Garden 和自定义 RSS 订阅；
- 主备 RSS、标题规则、集数解析、遗漏与停更监控；
- qBittorrent 推送、hash 跟踪、下载完成检查和可选延迟清理；
- TMDB、Bangumi、AniList 元数据及 NFO、海报、背景图；
- Telegram、Bark 和通用 Webhook 通知模板与预览；
- 配置备份、订阅迁移、网络诊断和容器在线更新。

## 快速部署

### 通用 Docker Compose

```bash
cp .env.example .env
# 编辑管理员密码、qBittorrent 和媒体路径
docker compose pull feeddock
docker compose up -d --build
```

需要内置 qBittorrent：

```bash
docker compose --profile with-qbit up -d
```

管理页面默认地址：`http://服务器地址:7789`。首次登录后必须修改初始密码。

### 飞牛 OS

```bash
cp .env.fnos.example .env
docker compose -f docker-compose.fnos.yml pull feeddock
docker compose -f docker-compose.fnos.yml up -d --build
```

宿主机目录、权限和路径映射见 [飞牛 OS 部署说明](docs/deployment/FNOS_DEPLOY.md)。

## 在线更新

两份 Compose 都内置 FeedDock 专用 updater sidecar。它不是通用容器监控器，只接受带授权的 `/v1/update` 请求，并固定执行：

```text
docker compose pull feeddock
docker compose up -d --no-deps feeddock
```

因此只会更新 FeedDock，不会扫描或更新 qBittorrent 等其他容器。Updater 默认随 `docker compose up -d` 启动，8090 仅在 Docker 内部网络可见，不映射到宿主机。

共享 Token 默认由 updater 首次启动时自动生成到 `feeddock-updater-state` named volume，FeedDock 只读挂载该 Token，无需手工生成。需要固定 Token 时可在 `.env` 设置：

```dotenv
FEEDDOCK_UPDATER_TOKEN=至少32位随机字符串
```

“检查镜像更新”仍直接读取 `FEEDDOCK_IMAGE` 的远端 OCI 元数据；点击“在线更新”后由专用 updater 拉取新镜像并重建 FeedDock。

## 容器镜像自动发布

向 `main` 或 `master` 推送后，GitHub Actions 会检查本次提交中的重要文件变化，并直接读取远端 `ghcr.io/planeteditorx/feeddock:latest` 镜像的 OCI 版本与 revision。发现新代码时自动递增补丁版本并推送镜像，不需要手动执行 `git tag`，也不会自动提交版本文件。

FeedDock 的“检查镜像更新”直接比较当前镜像内置 revision 与远端镜像 revision，不依赖静态版本文件或 GitHub Release。GitHub Release 仅作为可选发布记录。

仅修改 `docs/**` 或 `tests/**` 时不会发布镜像。发布路径可在 [`.github/release-paths.txt`](.github/release-paths.txt) 中调整，完整机制见 [容器镜像自动发布说明](docs/deployment/AUTOMATIC_RELEASES.md)。

## 常用文档

- [设置说明](docs/guides/SETTINGS_REFERENCE.md)
- [qBittorrent 集成](docs/guides/QBITTORRENT.md)
- [通知与监控](docs/guides/NOTIFICATIONS_AND_MONITORING.md)
- [元数据、命名与媒体目录](docs/guides/METADATA_AND_MEDIA.md)
- [配置备份与 RSS 恢复](docs/guides/SYSTEM_BACKUP_AND_RSS_RECOVERY.md)
- [网络与 DNS 排障](docs/deployment/NETWORK_TROUBLESHOOTING.md)
- [调试日志](docs/reference/DEBUG_LOGGING.md)

## 数据与安全边界

- `/data` 保存 SQLite、设置、缓存和日志，升级时不得删除。
- FeedDock 不提供、托管或审核第三方种子与媒体内容。
- qBittorrent 延迟清理固定保留下载文件。
- 只有专用 updater 挂载 Docker Socket；FeedDock 主容器不挂载 Docker Socket。
- 修改 Compose 的 DNS、环境变量、标签或卷后，应重新创建容器，而不是只重启进程。
