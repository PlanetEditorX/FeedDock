# 飞牛 OS 部署

本文对应仓库根目录的 `docker-compose.fnos.yml`。默认使用已发布镜像，并通过 `.env` 覆盖宿主机路径、账号、DNS、qBittorrent 等参数；在线更新由专用 updater sidecar 完成。

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
docker compose -f docker-compose.fnos.yml up -d --build
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

## 4. 在线更新

`docker-compose.fnos.yml` 默认启动 `updater` 服务，无需 `--profile updater`。Updater 只在 Docker 内部网络监听 8090，不映射宿主机端口，并固定只更新 `feeddock` 服务。

首次启动时会在 `feeddock-updater-state` named volume 自动生成共享 Token，FeedDock 以只读方式读取，因此通常无需在 `.env` 手工配置 Token。若需要固定 Token，可设置：

```dotenv
FEEDDOCK_UPDATER_TOKEN=至少32位随机字符串
```

启动或重建：

```bash
docker compose -f docker-compose.fnos.yml up -d --build
```

检查状态：

```bash
docker compose -f docker-compose.fnos.yml ps
docker compose -f docker-compose.fnos.yml logs --tail=100 updater
```

只有 updater 挂载 `/var/run/docker.sock`；FeedDock 主容器不直接获得 Docker Engine 权限。

## 5. DNS 与网络

Compose 默认为 FeedDock 设置：

```text
223.5.5.5
119.29.29.29
1.1.1.1
```

修改 DNS、环境变量、卷、标签或服务定义后，必须重新创建容器：

```bash
docker compose -f docker-compose.fnos.yml up -d --build --force-recreate
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
docker compose -f docker-compose.fnos.yml pull feeddock
docker compose -f docker-compose.fnos.yml up -d --build
```

迁移实例前，可在“设置 → 系统管理 → 配置备份与恢复”导出 JSON。该备份不包含 Compose 的端口、卷、DNS、PUID/PGID、专用 updater 和 Docker Socket 权限，这些内容仍需单独迁移。

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

1. `updater` 容器处于 healthy；
2. FeedDock 已挂载 `feeddock-updater-state:/run/feeddock-updater:ro`；
3. updater 已挂载同一状态卷到 `/state`；
4. 如手工设置了 `FEEDDOCK_UPDATER_TOKEN`，两边读取的是同一值。

### 在线更新返回 401

如手工固定 Token，FeedDock 与 updater 的 Token 不一致。重新创建两个容器并确保读取同一个 `FEEDDOCK_UPDATER_TOKEN`；未手工设置时应让两边使用共享状态卷中的自动 Token。
