# FeedDock 在飞牛 OS（fnOS）上的部署

本文按以下目录部署：

```text
/vol1/1000/应用/feeddock
```

使用已经发布到 GHCR 的镜像：

```text
ghcr.io/planeteditorx/feeddock:latest
```

不需要在飞牛 OS 上编译源码，也不需要同时部署 qBittorrent。

## 一、准备目录

在飞牛文件管理器中确认下面的目录存在：

```text
/vol1/1000/应用/feeddock
/vol1/1000/应用/feeddock/data
```

`data` 目录用于保存：

- 管理员新密码；
- 登录会话密钥；
- RSS 订阅；
- 下载任务记录；
- 应用数据库。

升级或重建容器时不要删除这个目录。

## 二、默认 Compose

在飞牛 Docker 的 Compose 项目中使用项目根目录的 `docker-compose.fnos.yml`。

默认配置为：

- 访问端口：`7789`；
- 首次用户名：`admin`；
- 首次密码：`password`；
- qBittorrent：暂不配置；
- 更新检查仓库：`planeteditorx/feeddock`；
- 网页一键更新：暂时关闭。

部署完成后访问：

```text
http://飞牛IP:7789
```

首次登录：

```text
用户名：admin
密码：password
```

登录后系统会强制进入修改密码页面。新密码至少需要 10 个字符。

> `ADMIN_PASSWORD: "password"` 只用于数据库第一次初始化。修改密码后，新密码保存在 `/vol1/1000/应用/feeddock/data` 中。以后重启、拉取镜像或重新创建容器，都不会重新改回 `password`。

## 三、验证登录

完成修改密码后，退出并使用新密码重新登录。

也可以打开健康检查地址：

```text
http://飞牛IP:7789/health
```

正常时会返回：

```json
{"status":"ok","version":"当前版本号"}
```

## 四、后续配置 qBittorrent

现在 Compose 中保留为空：

```yaml
QBIT_URL: ""
QBIT_USERNAME: ""
QBIT_PASSWORD: ""
```

因此 FeedDock 可以在没有 qBittorrent 的情况下正常启动和登录。

准备好 qBittorrent 后，再修改这三项。例如 qBittorrent 在局域网地址 `192.168.1.20`：

```yaml
QBIT_URL: "http://192.168.1.20:8080"
QBIT_USERNAME: "admin"
QBIT_PASSWORD: "你的qBittorrent密码"
```

保存 Compose 并重新部署，然后在 FeedDock 页面点击“测试下载器”。

## 五、更新

当前默认配置支持在 FeedDock 页面检查 GitHub Release 是否有新版本：

```yaml
UPDATE_REPOSITORY: "planeteditorx/feeddock"
UPDATE_API_URL: "https://api.github.com"
```

默认暂时关闭网页一键更新：

```yaml
WATCHTOWER_URL: ""
WATCHTOWER_TOKEN: ""
```

需要更新时，先在飞牛 Docker 的 Compose 项目中执行：

1. 拉取最新镜像；
2. 重新创建或重新部署项目。

数据保存在宿主机 `data` 目录中，不会因容器重建而丢失。

## 六、忘记密码

不要直接修改 Compose 中的 `ADMIN_PASSWORD`，因为数据库已经初始化后，它不会覆盖现有密码。

若确实需要完全重置：

1. 停止 FeedDock；
2. 备份 `/vol1/1000/应用/feeddock/data`；
3. 删除其中的 `feeddock.db`；
4. 重新部署。

这样会重新使用 `admin / password` 初始化，但同时会清空订阅和任务记录。
