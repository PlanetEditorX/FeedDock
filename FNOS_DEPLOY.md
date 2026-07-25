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

## 四、在网页配置外部 qBittorrent

现在 Compose 中的 qBittorrent 配置保持为空，FeedDock 可以先独立启动。登录并修改初始密码后，在首页找到 **qBittorrent 下载器**。

按下面填写：

1. qBittorrent 在同一台飞牛 OS：WebUI 地址先填 `http://host.docker.internal:8080`。
2. qBittorrent 在局域网其他设备：填写类似 `http://192.168.1.20:8080`。
3. 用户名和密码填写 qBittorrent WebUI 的登录信息。
4. 分类可保留 `rss`。
5. 下载保存路径填写 qBittorrent 能识别的路径，例如 `/downloads/rss`。
6. 点击“保存并测试连接”。

网页设置保存在：

```text
/vol1/1000/应用/feeddock/data/feeddock.db
```

配置在容器重启后仍然有效，并优先于 Compose 环境变量。页面不会回显密码；以后只修改地址、分类或下载路径时，密码输入框留空即可保留原密码。

需要改回 Compose 配置时，点击“恢复 Compose 默认”。如果 `host.docker.internal` 无法连接，可以改填飞牛 OS 的局域网 IP，例如 `http://192.168.1.10:8080`。

## 五、更新

GitHub Actions 在 Docker 镜像推送成功后，会自动读取 `VERSION`，创建对应的 Git 标签和 GitHub Release。例如 `VERSION` 为 `1.3.2` 时，会自动发布 `v1.3.2`。相同版本重复构建不会重复创建。

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
