# FeedDock 在飞牛 OS 上部署

## 一、目录

在飞牛文件管理器中创建：

```text
/vol1/1000/应用/feeddock/data
```

## 二、Compose

把项目中的 `docker-compose.fnos.yml` 完整粘贴到飞牛 Docker Compose 项目中并部署。

镜像：

```text
ghcr.io/planeteditorx/feeddock:latest
```

端口：

```text
7789:8000
```

## 三、首次登录

访问：

```text
http://飞牛IP:7789
```

首次账号：

```text
用户名：admin
密码：password
```

登录后系统会强制修改密码。新密码写入 `/data/feeddock.db`，之后 Compose 中的 `password` 不会覆盖新密码。

## 四、外部 qBittorrent

登录后在“qBittorrent 下载器”区域填写并测试。

同一台飞牛 OS：

```text
http://host.docker.internal:8080
```

局域网其他设备：

```text
http://192.168.1.20:8080
```

## 五、Mikan 目录过滤

1. 选择年份和季度；
2. 点击“读取目录”；
3. 在任意星期标题右侧点击“编辑过滤”；
4. 勾选需要隐藏的番剧；
5. 点击“保存过滤”。

隐藏设置写入同一个 SQLite 数据库。不要删除：

```text
/vol1/1000/应用/feeddock/data
```

## 六、更新

GitHub Actions 成功构建后，在飞牛 Compose 项目中重新拉取并部署 `latest`。数据目录不会被镜像更新覆盖。浏览器可按 `Ctrl + F5` 强制刷新静态文件。
