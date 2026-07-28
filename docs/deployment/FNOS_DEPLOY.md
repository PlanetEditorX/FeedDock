# 飞牛 OS 部署

本文对应仓库根目录的 `docker-compose.fnos.yml`。默认使用已发布镜像，并通过 `.env` 覆盖宿主机路径、账号、DNS、qBittorrent 和 Watchtower Token。

## 1. 准备目录与配置

默认挂载关系：

```text
/vol1/1000/应用/feeddock/data  → /data
/vol2/1000/影视                → /media
```

`/data` 保存数据库、设置、缓存和日志，升级时不得删除。`/media` 必须指向 qBittorrent 使用的同一份宿主机媒体目录，但 qBittorrent 与 FeedDock 看到的容器路径可以不同。

复制配置：

```bash
cp .env.fnos.example .env
```

至少修改：

```dotenv
ADMIN_PASSWORD=替换为强密码
FEEDDOCK_DATA_PATH=/vol1/1000/应用/feeddock/data
FEEDDOCK_MEDIA_PATH=/vol2/1000/影视
```

默认以 `PUID=0`、`PGID=0` 运行，适合飞牛共享目录权限不一致的环境。改为普通 UID/GID 前，应确认数据目录和媒体目录都可读写。

## 2. 启动 FeedDock

```bash
docker compose -f docker-compose.fnos.yml pull
docker compose -f docker-compose.fnos.yml up -d
```

默认访问地址：

```text
http://飞牛地址:7789
```

首次账号取自 `.env`，示例默认用户名为 `admin`。首次登录后必须修改初始密码。

## 3. 配置 qBittorrent

可以先在 `.env` 留空，再通过网页“下载设置”填写：

```dotenv
QBIT_URL=http://qBittorrent地址:8080
QBIT_USERNAME=admin
QBIT_PASSWORD=真实密码
QBIT_CATEGORY=rss
```

路径规则：

- `DOWNLOAD_PATH`：qBittorrent 实际识别的下载根目录；
- `MEDIA_LOCAL_ROOT`：FeedDock 容器中实际可见的媒体根目录；
- 两者可不同，但必须指向同一宿主机目录。

示例：

```text
qBittorrent：/vol2/1000/影视/番剧名称 (2026)/Season 01
FeedDock：   /media/番剧名称 (2026)/Season 01
```

详细规则见 [元数据、命名与媒体目录](../guides/METADATA_AND_MEDIA.md)。

## 4. 配置在线更新

`docker-compose.fnos.yml` 已包含可选的 `watchtower` 服务，服务位于 `updater` profile，不会默认启动，也不会把 8080 端口映射到宿主机。

生成共享 Token：

```bash
openssl rand -hex 32
```

将结果写入 `.env`：

```dotenv
FEEDDOCK_IMAGE=ghcr.io/planeteditorx/feeddock:latest
WATCHTOWER_URL=http://watchtower:8080
WATCHTOWER_TOKEN=替换为生成的Token
# 公开 GHCR 镜像保持为空；私有包填写 packages:read 凭据
UPDATE_REGISTRY_USERNAME=
UPDATE_REGISTRY_TOKEN=
```

FeedDock 会直接查询 `FEEDDOCK_IMAGE` 的远端 manifest、revision 和 digest。私有 GHCR 包未配置凭据时只能执行 Watchtower 更新，页面无法读取远端镜像元数据。

启动 FeedDock 与更新服务：

```bash
docker compose -f docker-compose.fnos.yml --profile updater pull
docker compose -f docker-compose.fnos.yml --profile updater up -d
```

两边读取同一个 `WATCHTOWER_TOKEN`。Token 不一致时，在线更新会返回 HTTP 401。Watchtower 挂载 `/var/run/docker.sock`，因此只能运行在可信的内部 Docker 网络，禁止自行增加公网端口映射。

检查状态：

```bash
docker compose -f docker-compose.fnos.yml --profile updater ps
docker compose -f docker-compose.fnos.yml logs --tail=100 watchtower
```

## 5. DNS 与网络

Compose 默认为 FeedDock 和 Watchtower 设置：

```text
223.5.5.5
119.29.29.29
1.1.1.1
```

修改 DNS、环境变量、卷、标签或服务定义后，必须重新创建容器：

```bash
docker compose -f docker-compose.fnos.yml --profile updater up -d --force-recreate
```

普通重启不会更新容器的 `/etc/resolv.conf`。完整排障见 [网络与 DNS 排障](NETWORK_TROUBLESHOOTING.md)。

## 6. 元数据与媒体文件

网页“刮削设置”中通常保持：

```text
FeedDock 本地媒体挂载目录：/media
```

FeedDock 可写入 `tvshow.nfo`、`movie.nfo`、季和单集 NFO、海报、背景图及可选 `bangumi.ini`。多视频合集不会自动猜测文件与集数对应关系。

TMDB、Bangumi、AniList 和代理参数可以写入 `.env`，网页保存值优先于 Compose 默认值。

## 7. 升级与迁移

手动升级镜像：

```bash
docker compose -f docker-compose.fnos.yml --profile updater pull
docker compose -f docker-compose.fnos.yml --profile updater up -d
```

迁移实例前，可在“设置 → 系统管理 → 配置备份与恢复”导出 JSON。该备份不包含 Compose 的端口、卷、DNS、PUID/PGID、Watchtower 和 Docker Socket 权限，这些内容仍需单独迁移。

## 8. 常见问题

### `/media` 不可写

确认宿主机目录存在、挂载不是只读，并检查 `PUID`、`PGID` 和飞牛共享目录权限。

### 外部域名解析失败

在 FeedDock 容器中检查：

```bash
docker compose -f docker-compose.fnos.yml exec feeddock getent hosts api.push.apple.com
docker compose -f docker-compose.fnos.yml exec feeddock getent hosts anibt.net
```

### 在线更新提示未配置

确认：

1. `.env` 中的 `WATCHTOWER_TOKEN` 不是空值；
2. 使用 `--profile updater` 启动了 Watchtower；
3. FeedDock 容器已重新创建并读取新环境变量；
4. `FEEDDOCK_IMAGE` 是远程镜像，而不是 `feeddock:local`。

### 在线更新返回 401

FeedDock 与 Watchtower 使用的 Token 不一致。重新创建两个容器，确保它们读取同一个 `.env`。
