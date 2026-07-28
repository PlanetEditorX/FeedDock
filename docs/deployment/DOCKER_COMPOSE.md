# Docker Compose 部署

仓库提供两份部署文件：

| 文件 | 用途 |
|---|---|
| `docker-compose.yml` | 通用 Docker / Linux / NAS |
| `docker-compose.fnos.yml` | 飞牛 OS 默认路径和权限 |

两份 Compose 都使用 `ghcr.io/planeteditorx/feeddock:latest`，都包含可选的 Watchtower HTTP API，并使用 `updater` profile 控制是否启动更新服务。

## 通用部署

```bash
cp .env.example .env
docker compose pull
docker compose up -d
```

启用示例 qBittorrent：

```bash
docker compose --profile with-qbit up -d
```

启用在线更新：

```bash
openssl rand -hex 32
# 将输出写入 .env 的 WATCHTOWER_TOKEN
docker compose --profile updater up -d
```

同时启用 qBittorrent 和在线更新：

```bash
docker compose --profile with-qbit --profile updater up -d
```

## 飞牛部署

```bash
cp .env.fnos.example .env
docker compose -f docker-compose.fnos.yml up -d
```

启用在线更新：

```bash
docker compose -f docker-compose.fnos.yml --profile updater up -d
```

详细说明见 [飞牛 OS 部署](FNOS_DEPLOY.md)。

## Watchtower 参数

```dotenv
FEEDDOCK_IMAGE=ghcr.io/planeteditorx/feeddock:latest
WATCHTOWER_URL=http://watchtower:8080
WATCHTOWER_TOKEN=随机共享Token
# 公开 GHCR 镜像无需填写；私有包才需要 packages:read 凭据
UPDATE_REGISTRY_USERNAME=
UPDATE_REGISTRY_TOKEN=
```

FeedDock 的“检查镜像更新”会直接读取 `FEEDDOCK_IMAGE` 标签的 OCI manifest。公开镜像可匿名查询；私有镜像需要填写 Registry 用户名与 Token。

`WATCHTOWER_URL` 是 Docker 内部服务地址。两份 Compose 都没有给 Watchtower 配置 `ports`，外部浏览器无法直接访问该 API。

Watchtower 只处理带有以下标签的 FeedDock 容器：

```yaml
com.centurylinklabs.watchtower.enable: "true"
```

qBittorrent 和 Watchtower 自身的标签为 `false`。

## 本地开发镜像

本地构建时：

```bash
docker build -t feeddock:local .
```

然后在 `.env` 设置：

```dotenv
FEEDDOCK_IMAGE=feeddock:local
WATCHTOWER_TOKEN=
```

本地镜像没有远程仓库来源，网页在线更新应视为不可用。

## 应用配置变化

修改以下内容后需要重新创建容器：

- DNS；
- 环境变量；
- 卷挂载；
- Watchtower Token；
- 容器标签；
- profile 或服务定义。

```bash
docker compose --profile updater up -d --force-recreate
```
