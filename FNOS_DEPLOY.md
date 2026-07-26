# FeedDock v1.10.1 飞牛 OS 部署

## 1. FeedDock 只挂载数据目录

```yaml
volumes:
  - "/vol1/1000/应用/feeddock/data:/data"
```

不再把影视目录挂载给 FeedDock。FeedDock 不写 NFO、不下载海报到影视目录，也不调用 tinyMediaManager 或 Emby。

## 2. qBittorrent 负责访问影视目录

qBittorrent 应把宿主机影视目录映射为 `/media`：

```yaml
volumes:
  - "/vol2/1000/影视:/media"
```

FeedDock 中设置：

```text
下载保存根目录：/media
```

这是发给 qBittorrent 的路径，并不是 FeedDock 本地路径。

## 3. 首次登录

```text
用户名：admin
初始密码：password
```

首次登录后必须修改密码。新密码保存在 `/vol1/1000/应用/feeddock/data/feeddock.db`，重新部署不会被初始密码覆盖。

## 4. 配置下载器

qBittorrent 与 FeedDock 在同一台飞牛：

```text
http://host.docker.internal:8080
```

局域网其他设备：

```text
http://192.168.1.20:8080
```

保存并测试连接后，再配置订阅。

## 5. 媒体库自动识别

建议使用 TMDB 选择正确条目，并采用：

```text
剧名 (年份) [tmdbid=123456]/Season 01/剧名 (年份) - S01E01.mkv
```

飞牛影视、Emby、Jellyfin 等外部媒体库随后自行扫描和刮削。FeedDock 不参与媒体库刮削。

## 6. 权限

FeedDock 只需要 `/data` 可写。默认：

```yaml
PUID: "0"
PGID: "0"
UMASK: "002"
```

入口脚本只测试 `/data`，不会触碰 `/vol2/1000/影视`。

## 7. 更新

GitHub Actions 变绿后，在飞牛 Docker 的 Compose 项目中重新部署并拉取：

```text
ghcr.io/planeteditorx/feeddock:latest
```

不要删除数据目录。完成后浏览器执行 `Ctrl + F5`。

## 8. 排错

网页开启 DEBUG，或查看：

```bash
docker logs --tail 300 feeddock
docker logs -f feeddock
```

本地日志：

```text
/vol1/1000/应用/feeddock/data/logs/feeddock.log
```
