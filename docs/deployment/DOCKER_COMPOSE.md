# Docker Compose 部署

仓库提供两份部署文件：

| 文件 | 用途 |
|---|---|
| `docker-compose.yml` | 通用 Docker / Linux / NAS |
| `docker-compose.fnos.yml` | 飞牛 OS 默认路径和权限 |

两份 Compose 都使用 `ghcr.io/planeteditorx/feeddock:latest`，并默认启动 FeedDock 专用 updater sidecar。Updater 只允许更新 `feeddock` 服务，不扫描其他容器。

## 通用部署

```bash
cp .env.example .env
docker compose pull feeddock
docker compose up -d --build
```

启用示例 qBittorrent：

```bash
docker compose --profile with-qbit up -d
```

在线更新默认已经启用；无需额外 profile。启用内置 qBittorrent 时仍使用：

```bash
docker compose --profile with-qbit up -d
```

## 飞牛部署

```bash
cp .env.fnos.example .env
docker compose -f docker-compose.fnos.yml up -d --build
```

在线更新默认随 FeedDock 一起启动，无需额外 profile。

详细说明见 [飞牛 OS 部署](FNOS_DEPLOY.md)。

## 专用 updater

默认内部地址：

```dotenv
FEEDDOCK_UPDATER_URL=http://updater:8090
```

默认 Token 由 updater 自动生成并保存在 named volume `feeddock-updater-state`。如需固定 Token，可设置：

```dotenv
FEEDDOCK_UPDATER_TOKEN=至少32位随机字符串
```

Updater 不映射宿主机端口，只挂载 Docker Socket、当前 Compose 目录的只读副本以及 Token 状态卷。更新请求固定只针对 `feeddock` 服务执行 `pull` 和 `up -d --no-deps`。

## 本地开发镜像

本地构建时：

```bash
docker build -t feeddock:local .
```

然后在 `.env` 设置：

```dotenv
FEEDDOCK_IMAGE=feeddock:local
FEEDDOCK_UPDATER_TOKEN=
```

本地镜像没有远程仓库来源，网页在线更新应视为不可用。

## 应用配置变化

修改以下内容后需要重新创建容器：

- DNS；
- 环境变量；
- 卷挂载；
- 专用 updater Token（仅在手工固定 Token 时）；
- 容器标签；
- profile 或服务定义。

```bash
docker compose up -d --build --force-recreate
```
