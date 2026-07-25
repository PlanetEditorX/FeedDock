# FeedDock

自托管 RSS 规则处理与 qBittorrent 自动化服务。

FeedDock 定时读取用户自行添加的 RSS / Atom，按关键词或正则过滤，去重后推送到 qBittorrent，并通过中文 Web 页面管理订阅、任务、日志和应用更新。

> 本项目不提供、存储或分发任何媒体资源。请只处理你有权访问和下载的内容，并遵守所在地区法律、源站条款及版权要求。

## 功能

- 应用内登录页，使用 HttpOnly 签名会话 Cookie
- 首次登录后强制修改初始密码，完成前锁定业务 API
- PBKDF2-SHA256 密码哈希，修改密码后旧会话自动失效
- RSS / Atom 定时轮询与手动刷新
- 包含词、排除词、集数正则、指纹去重和任务重试
- qBittorrent Web API 登录、连通性测试与任务推送
- 可在 Web 页面保存、测试和恢复 qBittorrent 配置
- 支持外部 qBittorrent，不要求与 FeedDock 部署在同一主机
- 可选 Compose 内置 qBittorrent
- GitHub Release 版本检查
- 可选 Watchtower 网页一键更新
- GitHub Actions 多架构镜像构建与 GHCR 推送

当前版本号：`1.3.2`

### v1.3.2 修复

- 修复添加订阅成功后，页面提示 `Cannot read properties of null (reading 'reset')` 的问题。
- 为前端静态资源加入版本参数，更新镜像后浏览器会加载新版 JavaScript。



## 飞牛 OS（fnOS）部署

项目提供飞牛 OS 专用文件：

- `docker-compose.fnos.yml`：直接使用 `ghcr.io/planeteditorx/feeddock:latest`，无需在 NAS 上构建镜像。
- `.env.fnos.example`：飞牛环境变量模板。
- `FNOS_DEPLOY.md`：从创建 Compose 项目到登录、外部 qBittorrent 和更新验证的完整步骤。

飞牛专用 Compose 只为 FeedDock 挂载 `/vol1/1000/应用/feeddock/data:/data`。外部 qBittorrent 的下载目录不会映射给 FeedDock，`DOWNLOAD_PATH` 只作为保存路径发送给 qBittorrent。

同一台飞牛 OS 上的 qBittorrent 可以使用：

```dotenv
QBIT_URL=http://host.docker.internal:8080
```

专用 Compose 已配置 `host.docker.internal:host-gateway`。详细步骤见 [FNOS_DEPLOY.md](FNOS_DEPLOY.md)。

## 1. 快速部署

```bash
cp .env.example .env
```

至少修改以下配置：

```dotenv
ADMIN_PASSWORD=首次登录使用的强密码
QBIT_URL=http://你的qBittorrent地址:8080
QBIT_USERNAME=admin
QBIT_PASSWORD=qBittorrent的WebUI密码
UPDATE_REPOSITORY=planeteditorx/feeddock
```

### 使用外部 qBittorrent

这是推荐的默认方式，不需要启动项目附带的 qBittorrent：

```bash
docker compose up -d --build
```

打开 `http://服务器IP:7789`。

容器启动脚本会修正 `./data` 的写入权限，然后以 `PUID` / `PGID`（默认 `1000:1000`）运行主程序，避免首次启动时 SQLite 因宿主机目录权限而失败。

`QBIT_URL` 可以是局域网地址、Docker 宿主机地址或受 HTTPS 保护的远程地址，例如：

```dotenv
QBIT_URL=http://192.168.1.20:8080
```

FeedDock 不依赖 qBittorrent 容器，也没有 `depends_on`。网页中的“测试下载器”会实际执行登录并读取 qBittorrent 版本。

### 同时启动附带的 qBittorrent

把 `.env` 改为：

```dotenv
QBIT_URL=http://qbittorrent:8080
```

然后运行：

```bash
docker compose --profile with-qbit up -d --build
```

打开：

- FeedDock：`http://服务器IP:7789`
- qBittorrent：`http://服务器IP:8080`

查看 qBittorrent 首次临时密码：

```bash
docker logs feeddock-qbittorrent
```

## 2. 登录与首次改密

首次启动时，FeedDock 会在 SQLite 中创建管理员账户：

```dotenv
ADMIN_USER=admin
ADMIN_PASSWORD=change-this-to-a-strong-password
```

登录流程：

1. 打开 FeedDock 登录页。
2. 使用 `.env` 中的初始账号和密码登录。
3. 系统自动跳转到“修改初始密码”页面。
4. 完成修改前，订阅、日志、下载器和更新 API 返回 `428 PASSWORD_CHANGE_REQUIRED`。
5. 修改成功后，新密码以哈希形式保存到 `data/feeddock.db`，旧会话立即失效。

后续重启不会使用 `.env` 覆盖已经保存的密码。因此，`ADMIN_PASSWORD` 只负责数据库首次初始化。

建议：

- 新密码至少 10 个字符。
- 通过 HTTPS 反向代理访问时设置 `COOKIE_SECURE=true`。
- 备份 `data/feeddock.db`，其中包含管理员密码哈希与订阅数据。

## 3. 外部 qBittorrent

登录后可直接在首页的“qBittorrent 下载器”区域配置，无需修改 Compose。网页配置存入 SQLite，并优先于环境变量；密码留空表示保留现有密码。飞牛 OS 同机服务可使用 `http://host.docker.internal:8080`。


配置示例：

```dotenv
QBIT_URL=https://qb.example.com
QBIT_USERNAME=admin
QBIT_PASSWORD=你的密码
QBIT_CATEGORY=rss
DOWNLOAD_PATH=/data/downloads/rss
```

注意：

- `DOWNLOAD_PATH` 是发送给 qBittorrent 的保存路径，应以 qBittorrent 所在主机或容器看到的路径为准。
- 当 qBittorrent 在另一台主机上时，FeedDock 本地无需实际存在同名目录；但 qBittorrent 必须能写入该路径。
- qBittorrent WebUI 必须启用认证，网络策略必须允许 FeedDock 访问。
- HTTPS 使用私有证书时，应在系统层正确配置受信任证书，不建议关闭证书验证。

## 4. 更新功能

FeedDock 提供两层更新能力。

### 4.1 检查 GitHub Release

配置仓库：

```dotenv
UPDATE_REPOSITORY=planeteditorx/feeddock
UPDATE_API_URL=https://api.github.com
```

网页“系统与更新”区域会显示：

- 当前版本
- GitHub 最新 Release
- 是否存在新版本
- 当前部署镜像
- 一键更新器是否启用

没有配置更新器时，仍然可以检查版本和打开发布说明，然后在服务器手动执行：

```bash
docker compose pull feeddock
docker compose up -d --no-build --remove-orphans
```

### 4.2 网页一键更新

一键更新通过可选 Watchtower 服务实现。它只处理带明确启用标签的 FeedDock 容器。

先确保使用可拉取的新镜像标签，例如：

```dotenv
FEEDDOCK_IMAGE=ghcr.io/planeteditorx/feeddock:latest
WATCHTOWER_URL=http://watchtower:8080
WATCHTOWER_TOKEN=替换为至少32位随机字符串
```

启动：

```bash
docker compose --profile updater up -d --no-build
```

同时启用内置 qBittorrent：

```bash
docker compose --profile updater --profile with-qbit up -d --no-build
```

网页发现新版本且更新器可用时，会显示“立即更新”。点击后 FeedDock 调用 Watchtower 的 `/v1/update`，Watchtower 拉取镜像、重建容器并清理旧镜像。

安全说明：

- Watchtower 需要挂载 `/var/run/docker.sock`，等同于拥有较高的 Docker 主机权限。
- `WATCHTOWER_TOKEN` 不应公开，也不要把 Watchtower 端口暴露到公网。
- 若不接受 Docker Socket 风险，不要启用 `updater` profile，使用手动升级即可。
- 固定版本标签如 `:1.3.2` 不会自动跳到后续版本；一键更新应使用 `:latest` 或其他持续更新的标签。

## 5. GitHub Actions 构建与发布镜像

项目包含 `.github/workflows/docker-publish.yml`：

- Pull Request：运行测试并构建 `linux/amd64`、`linux/arm64`，不推送。
- 默认分支：推送分支标签、SHA 标签和 `latest`。
- `v1.2.3` 标签：推送 `1.2.3`、`1.2`、`1` 和正式版 `latest`。
- 手动运行：可选择是否推送并指定额外标签。
- 镜像构建时把发布版本写入 `APP_VERSION`。

发布版本：

```bash
git tag v1.3.2
git push origin v1.3.2
```

镜像地址：

```text
ghcr.io/<GitHub所有者>/<仓库名>:latest
```

## 6. RSS 规则

- 包含词：逗号、中文逗号或换行分隔；命中任意一个即可。
- 排除词：命中任意一个即跳过，优先级高于包含词。
- 自定义集数正则：第一捕获组作为集数，例如 `S\d+E(\d+)`。
- 下载链接选择顺序：torrent enclosure、torrent/magnet link、正文中的 magnet。
- 保存路径变量：`{base}`、`{subscription}`、`{episode}`。
- 路径会被限制在 `DOWNLOAD_PATH` 之下，防止 `..` 越界。

## 7. 运维

查看日志：

```bash
docker compose logs -f feeddock
```

健康检查：

```bash
curl http://127.0.0.1:7789/health
```

返回示例：

```json
{"status":"ok","version":"1.3.2"}
```

备份：

```text
data/feeddock.db
data/session-secret.key
.env
```

## 8. 本地开发与测试

Python 3.10+：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export DATA_DIR="$PWD/.dev-data"
export ADMIN_PASSWORD=dev-initial-password
uvicorn app.main:app --reload
```

运行测试：

```bash
python -m unittest discover -s tests -v
```

测试覆盖：

- 未登录跳转
- 登录失败和成功
- 首次登录强制改密页面
- 改密前业务 API 锁定
- 改密后解锁与注销
- 外部 qBittorrent 登录、版本读取和任务推送
- GitHub Release 版本比较
- Watchtower 更新触发与令牌认证
- RSS、Atom、关键词、集数和路径安全

## 9. 安全建议

- FeedDock 和 qBittorrent 不应直接暴露到公网。
- 推荐使用 HTTPS 反向代理、访问控制和请求限速。
- 不要把 `.env`、SQLite 数据库或 Watchtower 令牌提交到 Git。
- Watchtower 的 Docker Socket 权限很高，只在理解风险后启用。
- RSS 内容是不可信输入；FeedDock 不执行条目脚本或命令。

## License

MIT
