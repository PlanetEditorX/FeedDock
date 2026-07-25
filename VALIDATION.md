# FeedDock 1.2.1 功能验证报告

## 飞牛 OS 默认部署配置

`docker-compose.fnos.yml` 已调整为适合当前飞牛目录的最小可运行配置：

```text
/vol1/1000/应用/feeddock/data:/data
```

默认值：

- 镜像：`ghcr.io/planeteditorx/feeddock:latest`；
- 端口：`7789:8000`；
- 首次用户名：`admin`；
- 首次密码：`password`；
- qBittorrent：留空，不影响 FeedDock 启动；
- GitHub Release 更新检查：启用；
- Watchtower 网页一键更新：暂时关闭。

首次登录后，应用会强制要求设置至少 10 个字符的新密码。新密码哈希保存在持久化数据库中，数据库初始化完成后，Compose 中的 `ADMIN_PASSWORD` 不再覆盖它。

## 功能回归

自动化测试覆盖：

- 登录成功和登录失败；
- 首次登录强制修改密码；
- 改密前业务 API 锁定，改密后恢复；
- 会话注销；
- 外部 qBittorrent 登录、读取版本和推送 Magnet；
- GitHub Release 版本比较和检查；
- Watchtower Bearer Token 更新触发；
- RSS、Atom、关键词、集数解析和路径越界保护；
- 飞牛 Compose 使用 GHCR 镜像，无本地构建；
- 飞牛默认初始账号、空 qBittorrent 和绝对数据目录；
- 运行时版本不被 `.env` 固定。

执行命令：

```bash
python -m unittest discover -s tests -v
python -m compileall -q app docker-entrypoint.py
node --check app/static/app.js
```

当前环境没有连接用户的飞牛 OS Docker 服务，因此无法代替用户执行 NAS 上的实际镜像拉取和容器重建。应用 HTTP 流程和相关协议通过本地自动化验证。

## HTTP 冒烟测试

使用飞牛默认部署等价环境变量启动应用后：

```text
GET  /health             -> 200，version=1.2.1
POST /api/auth/login     -> 200，must_change_password=true
GET  /api/dashboard      -> 428 PASSWORD_CHANGE_REQUIRED
```

这确认默认 `admin / password` 只用于首次登录，并且首次改密门禁正常生效。
