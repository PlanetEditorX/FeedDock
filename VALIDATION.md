# FeedDock v1.3.1 功能验证

## 本次新增

- qBittorrent 可在 Web 页面配置，不再必须修改 Compose。
- 网页配置保存到 SQLite，容器重启后继续生效。
- 网页配置优先于 Compose 环境变量。
- 密码不会通过读取接口回显；密码输入框留空可保留原密码。
- 可清除保存的密码，或恢复 Compose 默认配置。
- 飞牛 OS Compose 增加 `host.docker.internal:host-gateway`，支持访问同机 qBittorrent WebUI。
- RSS 推送与保存路径读取网页中的最新 qBittorrent 配置。
- Docker 镜像推送成功后，自动按 `VERSION` 创建 Git 标签和 GitHub Release。

## 自动化验证

共 17 项测试通过：

- 首次登录与强制修改密码。
- 修改密码后重启持久化。
- qBittorrent 网页配置保存、读取和密码不回显。
- 留空密码时保留已保存密码。
- 网页配置在应用重启后仍存在。
- 默认下载器客户端实际使用网页配置。
- 外部 qBittorrent 登录、版本读取和 Magnet 推送。
- GitHub Release 更新检查和 Watchtower 更新触发。
- RSS、Atom、关键词、集数、去重和路径安全。
- 飞牛 OS Compose 镜像、端口、数据目录及宿主机网关检查。

执行命令：

```bash
python -m unittest discover -s tests -v
python -m compileall -q app tests
node --check app/static/app.js
```

结果：全部通过。

## 飞牛 OS 使用结果

更新到 v1.3.1 后，登录首页即可看到“qBittorrent 下载器”区域。推荐填写：

```text
同机 qBittorrent：http://host.docker.internal:8080
其他设备：http://设备局域网IP:WebUI端口
```

`download_path` 必须是 qBittorrent 所在主机或容器能够识别的路径。FeedDock 本身不需要挂载该下载目录。

## 未在当前环境执行

当前执行环境没有 Docker Engine，也无法连接用户的飞牛 OS，因此没有实际执行 GHCR 镜像构建和 NAS 容器重建。应用 API、数据库持久化、外部 qBittorrent 协议和部署文件已完成本地验证。
