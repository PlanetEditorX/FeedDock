# FeedDock 在飞牛 OS（fnOS）上的部署

本说明使用已经发布到 GHCR 的镜像：

```text
ghcr.io/planeteditorx/feeddock:latest
```

不需要在飞牛 OS 上编译 Python 项目，也不强制部署 qBittorrent。

## 一、准备目录

在飞牛 OS 文件管理器中创建一个目录，例如：

```text
Docker/feeddock
```

把以下两个文件放入该目录：

```text
docker-compose.fnos.yml
.env
```

`.env` 可以由项目中的 `.env.fnos.example` 复制后修改。

Compose 首次启动后会在同一目录创建：

```text
data/
```

这里保存管理员账户、订阅、任务记录和会话密钥。升级时不要删除。

## 二、配置外部 qBittorrent

### qBittorrent 在同一台飞牛 OS

假设 qBittorrent WebUI 已映射到飞牛主机的 `8080` 端口：

```dotenv
QBIT_URL=http://host.docker.internal:8080
QBIT_USERNAME=admin
QBIT_PASSWORD=你的WebUI密码
```

专用 Compose 已加入：

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

因此 FeedDock 不需要与 qBittorrent 加入同一个 Docker 网络。

### qBittorrent 在局域网其他设备

直接填写设备的局域网地址：

```dotenv
QBIT_URL=http://192.168.1.20:8080
```

### 下载路径

`DOWNLOAD_PATH` 会原样发送给 qBittorrent。例如 qBittorrent 容器内的下载目录是 `/downloads`，可以配置：

```dotenv
DOWNLOAD_PATH=/downloads/rss
```

FeedDock 不直接写入下载目录，因此使用外部 qBittorrent 时不需要映射媒体文件夹。

## 三、在飞牛 Docker 中创建 Compose 项目

1. 打开飞牛 OS 的 **Docker** 应用。
2. 进入 **Compose** 或 **项目** 页面。
3. 新建项目，项目名填写 `feeddock`。
4. 选择 `Docker/feeddock` 作为项目目录。
5. 使用 `docker-compose.fnos.yml` 的内容创建项目。
6. 确认 `.env` 已保存到同一个目录。
7. 点击部署。

启动后访问：

```text
http://飞牛IP:7789
```

首次登录使用 `.env` 中的 `ADMIN_USER` 和 `ADMIN_PASSWORD`。系统会立即要求修改密码。

## 四、验证

### 查看健康状态

浏览器打开：

```text
http://飞牛IP:7789/health
```

应返回类似：

```json
{"status":"ok","version":"1.2.0"}
```

### 验证 qBittorrent

登录 FeedDock 后，在下载器区域点击 **测试下载器**。成功时会显示 qBittorrent 地址和版本。

若失败：

- 不要把 `QBIT_URL` 写成 `127.0.0.1` 或 `localhost`，它们只代表 FeedDock 容器自身。
- 同机使用 `host.docker.internal`；其他设备使用局域网 IP。
- 检查 qBittorrent WebUI 用户名、密码和“绕过本地主机认证”等安全设置。
- 检查飞牛防火墙和 qBittorrent WebUI 监听地址。

## 五、更新

Compose 中默认包含 Watchtower，仅响应 FeedDock 网页主动发起的更新请求，不定时扫描其他容器。

在 `.env` 中设置随机令牌：

```dotenv
WATCHTOWER_TOKEN=至少32位随机字符串
```

FeedDock 的“系统与更新”页面可以：

1. 查询 `planeteditorx/feeddock` 的最新 GitHub Release；
2. 发现新镜像后调用同一 Compose 网络中的 Watchtower；
3. 拉取 `ghcr.io/planeteditorx/feeddock:latest` 并重建 FeedDock；
4. 保留 `./data` 中的数据库和登录信息。

Watchtower 挂载了 `/var/run/docker.sock`。不接受这项权限时，删除 `docker-compose.fnos.yml` 中整个 `watchtower` 服务，并清空 FeedDock 的 `WATCHTOWER_URL` 和 `WATCHTOWER_TOKEN`。之后可在飞牛 Docker 项目页面手动执行“拉取/重建”。

## 六、权限问题

镜像启动时会把 `/data` 所有权调整为 `.env` 中的 `PUID:PGID`，然后降权运行。

默认值：

```dotenv
PUID=1000
PGID=1000
UMASK=022
```

若日志出现 `Permission denied`：

1. 在飞牛文件管理器确认 `Docker/feeddock/data` 可读写；
2. 通过 SSH 执行 `id 用户名`，把得到的 UID/GID 填入 `.env`；
3. 重新创建 FeedDock 容器，但不要删除 `data` 目录。

## 七、备份

至少备份：

```text
Docker/feeddock/data/feeddock.db
Docker/feeddock/data/session-secret.key
Docker/feeddock/.env
```
