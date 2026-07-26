# FeedDock

当前版本：`1.10.2`

FeedDock 是一个 Docker 化的 RSS 番剧订阅管理器，负责：Mikan 番剧目录、RSS 过滤、集数识别、元数据匹配、qBittorrent 推送和规范重命名。

**FeedDock 不再执行任何媒体刮削。** 海报、简介、NFO、演员信息和媒体库扫描请交给飞牛影视、Emby、Jellyfin、Plex 或其他外部媒体库。FeedDock 只负责把目录和文件名整理得便于识别。

## v1.10.2 变更

- 从 Mikan 选择订阅时自动填入元数据搜索词并立即搜索，便于快速修正不规范标题。
- 订阅卡片的详细配置默认收起，按“订阅详情”展开查看。
- Mikan 番剧目录会标出已通过 RSS 订阅的项目。
- 移除页面中的文件日志路径与 500 错误定位提示。

## v1.10.1 变更

- 删除 tinyMediaManager、Emby 刷新和本地 NFO/图片刮削代码。
- 删除所有刮削页面、API、定时任务和媒体目录写入。
- FeedDock 容器不再挂载 `/media`，只持久化 `/data`。
- 保留 TMDB、Bangumi、AniList 元数据搜索，用于标题、年份、季号、总集数、海报和简介展示。
- 保留 qBittorrent 内部文件重命名和下载进度检查。
- 保留统一下载时间、代理、Mikan 缓存、详细 DEBUG 日志和更新功能。
- 旧数据库的刮削字段仅为兼容保留，运行时不再读取；旧 TMM/Emby 配置会在启动迁移时清除。

## 核心流程

```text
Mikan 目录或手动 RSS
→ 规则过滤与集数识别
→ TMDB/Bangumi/AniList 元数据确认（可跳过）
→ 生成规范目录和 SxxExx 文件名
→ 推送 qBittorrent
→ 通过 qBittorrent API 重命名
→ 飞牛影视/Emby/Jellyfin 自动刮削
```

## 推荐命名

电视剧目录：

```text
从0位居民开始的边境领主大人 (2026) [tmdbid=296437]/
└── Season 01/
    └── 从0位居民开始的边境领主大人 (2026) - S01E01.mkv
```

默认保存路径模板：

```text
{base}/{media_folder}/Season {season:02}
```

默认文件名模板：

```text
{title} - S{season:02}E{episode:02}
```

`{base}` 是 qBittorrent 能看到的保存根目录，例如 `/media`。FeedDock 自身不需要访问该目录。

## 飞牛 OS 部署

使用 `docker-compose.fnos.yml`：

```yaml
services:
  feeddock:
    image: ghcr.io/planeteditorx/feeddock:latest
    container_name: feeddock
    restart: unless-stopped
    pull_policy: always
    ports:
      - "7789:8000"
    extra_hosts:
      - "host.docker.internal:host-gateway"
    environment:
      TZ: "Asia/Shanghai"
      PUID: "0"
      PGID: "0"
      ADMIN_USER: "admin"
      ADMIN_PASSWORD: "password"
      LOG_LEVEL: "INFO"
      QBIT_URL: ""
      QBIT_USERNAME: ""
      QBIT_PASSWORD: ""
      QBIT_CATEGORY: "rss"
      DOWNLOAD_PATH: "/media"
      TMDB_READ_ACCESS_TOKEN: ""
      BANGUMI_ACCESS_TOKEN: ""
    volumes:
      - "/vol1/1000/应用/feeddock/data:/data"
```

FeedDock 不再需要：

```yaml
- "/vol2/1000/影视:/media"
```

但 qBittorrent 仍必须把影视目录挂载为它能识别的路径，例如：

```yaml
volumes:
  - "/vol2/1000/影视:/media"
```

FeedDock 页面中的 `DOWNLOAD_PATH` 应填写 `/media`，因为这个路径会原样发送给 qBittorrent。

## 外部元数据

- **TMDB**：推荐用于媒体服务器识别、年份、季度和 `[tmdbid=...]`。
- **Bangumi**：适合中文/日文标题、放送日期和动漫总集数。
- **AniList**：作为动漫专用候选来源。

元数据只用于命名和页面展示，不会写入影视目录。

## qBittorrent 重命名

当 RSS 标题能够识别集数且订阅启用了规范命名时，FeedDock 会：

1. 给任务添加唯一标签；
2. 等待 qBittorrent 获取文件列表；
3. 对单视频种子调用 qBittorrent `renameFile`；
4. 同步重命名同名前缀字幕；
5. 多视频合集标记为需要手动处理，不猜测集数。

## 统一下载时间

可以选择让发现的下载任务等到每天固定时间再推送。下载完成检查与重命名仍每两分钟进行，不涉及刮削。

## 代理

代理可用于 Mikan、RSS、TMDB、Bangumi、AniList、海报和 GitHub 更新检查。默认排除本机地址和 `host.docker.internal`，避免 qBittorrent 走外部代理。

## 日志调试

在“系统日志”板块将级别切换到 `DEBUG`，可查看：

- API 请求路径、状态码和耗时；
- 订阅保存阶段；
- RSS、Mikan、元数据和 qBittorrent 异常；
- 请求编号、异常类型和完整 traceback。

日志文件：

```text
/data/logs/feeddock.log
```

飞牛宿主机：

```text
/vol1/1000/应用/feeddock/data/logs/feeddock.log
```

## 升级

覆盖源码后：

```bash
git add -A
git commit -m "refactor: remove built-in scraping and keep external media matching"
git push
```

Actions 构建成功后，在飞牛重新拉取镜像并部署。不要删除 `/vol1/1000/应用/feeddock/data`。

部署后执行一次 `Ctrl + F5`，避免浏览器继续使用旧前端。
