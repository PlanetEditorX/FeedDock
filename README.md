# FeedDock

当前版本：`1.10.2`

FeedDock 是一个自托管的 RSS 番剧订阅管理器。它读取 RSS、执行关键词和集数匹配、将下载链接推送到 qBittorrent，并可通过 qBittorrent API 将单视频任务规范命名为 `SxxExx` 格式。

## v1.10.2 重点修复

- **媒体刮削功能已完全移除**：不生成 NFO、不调用 tinyMediaManager、不通知 Emby、不写入媒体目录。
- 修复“新增任意订阅可能返回 500”时缺少诊断信息的问题。
- 新增 INFO/DEBUG 日志开关。
- 每个 API 请求生成 `X-Request-ID`，500 页面会显示同一请求编号。
- 订阅保存按 `prepare → build-values → insert → serialize → commit` 分阶段记录。
- 检测到 SQLite 订阅表缺少新增字段时，会自动执行一次兼容迁移并重试。
- 错误日志包含异常类型、失败阶段、请求上下文、数据库字段列表及完整 traceback。
- 日志同时保存到网页、`/data/logs/feeddock.log` 和 Docker 标准输出。
- 日志写入使用独立数据库事务，日志系统异常不会再导致订阅保存失败。

## 功能

- 首次登录强制修改初始密码。
- 密码、Token 和代理输入框支持小眼睛显示。
- Mikan 季度目录、星期过滤、封面本地缩略图缓存。
- TMDB、Bangumi、AniList 元数据匹配，仅用于标题、年份、季度、总集数、简介和海报展示。
- TMDB 支持从标题识别季度、选择最新已播季或手动指定季度。
- RSS 关键词、排除词、正则集数、集数偏移、只下载最新集。
- qBittorrent 推送、统一下载根目录、单视频及同名字幕规范重命名。
- 可设置每天固定时间统一推送下载。
- HTTP/HTTPS/SOCKS5/SOCKS5H 外部请求代理。
- 每个页面板块和 Mikan 星期板块可收起，并记住状态。
- 最近条目和系统日志可清理。

## 不再包含的功能

以下功能已从运行代码、页面、API 和 Docker 配置中移除：

- 本地 NFO 生成；
- 海报或背景图写入媒体目录；
- tinyMediaManager 调用；
- Emby 媒体库刷新；
- 下载完成后的媒体刮削；
- FeedDock 媒体目录挂载。

数据库中可能仍保留少量旧字段，仅用于旧数据库兼容，它们始终保持关闭，不会触发任何媒体处理。

## 飞牛 OS 快速部署

```yaml
services:
  feeddock:
    image: ghcr.io/planeteditorx/feeddock:latest
    container_name: feeddock
    restart: unless-stopped
    ports:
      - "7789:8000"
    environment:
      TZ: "Asia/Shanghai"
      PUID: "0"
      PGID: "0"
      UMASK: "002"
      ADMIN_USER: "admin"
      ADMIN_PASSWORD: "password"
      LOG_LEVEL: "INFO"
      QBIT_URL: ""
      QBIT_USERNAME: ""
      QBIT_PASSWORD: ""
      QBIT_CATEGORY: "rss"
      DOWNLOAD_PATH: "/media"
    volumes:
      - "/vol1/1000/应用/feeddock/data:/data"
```

FeedDock 不需要挂载 `/vol2/1000/影视`。`DOWNLOAD_PATH=/media` 是发送给 qBittorrent 的容器内保存路径，qBittorrent 自己需要将影视目录挂载到 `/media`。

## 新增订阅出现 500 时

1. 打开“系统日志与调试”。
2. 将记录级别切换为 `DEBUG`。
3. 再次保存订阅。
4. 复制页面错误中的请求编号，例如：

```text
保存订阅失败 [a1b2c3d4e5f6]：OperationalError: ...
```

5. 将编号粘贴到“请求编号”筛选框。
6. 展开“详细内容 / traceback”。

还可以查看：

```bash
cd /你的/Compose目录
docker logs --tail 300 feeddock
```

持续查看：

```bash
cd /你的/Compose目录
docker logs -f feeddock
```

宿主机日志文件：

```text
/vol1/1000/应用/feeddock/data/logs/feeddock.log
```

容器内路径：

```text
/data/logs/feeddock.log
```

日志文件最大 5 MB，保留 5 个轮转备份。密码、Token、API Key、Cookie 和 Authorization 字段会自动脱敏。

详见 [DEBUG_LOGGING.md](DEBUG_LOGGING.md)。

## 下载路径说明

FeedDock 页面中的下载根目录必须填写 qBittorrent 容器可见路径，例如：

```text
/media
```

qBittorrent Compose 示例：

```yaml
volumes:
  - "/vol2/1000/影视:/media"
```

FeedDock 只把 `/media/番剧目录/Season 01` 作为 `savepath` 传递给 qBittorrent，本身不会访问该目录。

## 更新

```bash
cd /你的/FeedDock仓库目录
git add -A
git commit -m "fix: remove scraping and add detailed debug logging"
git push
```

飞牛重新拉取：

```bash
cd /你的/Compose目录
docker compose -f docker-compose.fnos.yml pull
docker compose -f docker-compose.fnos.yml up -d
```

升级不会删除订阅、配置、Mikan 缓存或 RSS 去重指纹。
