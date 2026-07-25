# FeedDock 1.2.0 功能验证报告

## 飞牛 OS 部署适配

- 新增 `docker-compose.fnos.yml`，直接拉取 `ghcr.io/planeteditorx/feeddock:latest`，没有本地 `build`。
- 新增 `.env.fnos.example` 和 `FNOS_DEPLOY.md`。
- FeedDock 仅挂载 `./data:/data`，外部 qBittorrent 场景不挂载下载目录。
- 同一台飞牛 OS 上的 qBittorrent 可通过 `host.docker.internal` 访问。
- 容器入口支持 `PUID`、`PGID`、`UMASK`，并在权限调整失败时给出飞牛目录检查提示。
- 飞牛专用 Compose 包含可选的一键更新支撑服务；FeedDock 与更新器仅通过内部 Compose 网络通信。

## 更新链路修复

旧配置曾通过 `.env` 在运行时覆盖 `APP_VERSION`。镜像升级后，这可能导致页面继续显示旧版本。

1.2.0 已改为：

- Docker 镜像构建时写入版本号；
- Compose 不再向容器传入 `APP_VERSION`；
- `FEEDDOCK_IMAGE` 仅用于显示当前部署镜像；
- 推送 `v*.*.*` 标签后，GitHub Actions 同时创建 GitHub Release；
- 网页更新检查以该 Release 为版本来源，以 GHCR `latest` 为更新镜像。

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
- 飞牛 Compose 不包含本地构建和下载目录挂载；
- 运行时版本不被 `.env` 固定。

执行命令：

```bash
python -m unittest discover -s tests -v
python -m compileall -q app docker-entrypoint.py
node --check app/static/app.js
```

当前环境没有 Docker Engine，因此无法实际连接飞牛 OS Docker 服务进行镜像拉取和容器重建。Compose 文件、应用 HTTP 流程和外部服务协议均通过本地自动化验证。

## HTTP 冒烟测试

使用飞牛部署等价环境变量启动应用后：

```text
GET  /health             -> 200，version=1.2.0
POST /api/auth/login     -> 200，must_change_password=true
GET  /api/dashboard      -> 428 PASSWORD_CHANGE_REQUIRED
```

这确认镜像内置版本生效，且首次登录改密门禁未被飞牛适配改动破坏。
