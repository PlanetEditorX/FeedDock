# FeedDock

FeedDock 是面向自托管环境的 RSS 订阅、qBittorrent 下载编排、规范命名、元数据旁车文件和通知管理工具。当前版本：`1.17.12`。

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
docker compose pull
docker compose up -d
```

需要内置 qBittorrent：

```bash
docker compose --profile with-qbit up -d
```

管理页面默认地址：`http://服务器地址:7789`。首次登录后必须修改初始密码。

### 飞牛 OS

```bash
cp .env.fnos.example .env
docker compose -f docker-compose.fnos.yml pull
docker compose -f docker-compose.fnos.yml up -d
```

宿主机目录、权限和路径映射见 [飞牛 OS 部署说明](docs/deployment/FNOS_DEPLOY.md)。

## 在线更新

两个 Compose 文件都内置可选 Watchtower HTTP API。先生成 Token：

```bash
openssl rand -hex 32
```

将结果写入 `.env`：

```dotenv
FEEDDOCK_IMAGE=ghcr.io/planeteditorx/feeddock:latest
WATCHTOWER_URL=http://watchtower:8080
WATCHTOWER_TOKEN=替换为生成的Token
```

启动更新服务：

```bash
# 通用 Compose
docker compose --profile updater up -d

# 飞牛 Compose
docker compose -f docker-compose.fnos.yml --profile updater up -d
```

Watchtower 只在 Docker 内部网络监听，Compose 没有把 8080 端口映射到宿主机。FeedDock 容器标签允许更新，qBittorrent 和 Watchtower 自身默认不由该实例更新。

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
- Watchtower 挂载 Docker Socket，应只在受信任的内部网络使用。
- 修改 Compose 的 DNS、环境变量、标签或卷后，应重新创建容器，而不是只重启进程。
