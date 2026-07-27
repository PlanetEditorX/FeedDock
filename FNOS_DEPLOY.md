# FeedDock v1.17.11 飞牛 OS 部署

## 新增可选配置

```yaml
environment:
  TMDB_API_BASE: "https://api.themoviedb.org"
  TMDB_IMAGE_BASE: "https://image.tmdb.org"
  ANILIST_API_URL: "https://graphql.anilist.co"
  AUTOMATION_TIME: "02:00"
  AUTOMATION_TIMEZONE: "Asia/Shanghai"
  OUTBOUND_PROXY_URL: ""
  OUTBOUND_NO_PROXY: "localhost,127.0.0.1,host.docker.internal"
  FEEDDOCK_ALLOW_SYSTEM_ACTIONS: "false"
```

网页保存的设置优先于 Compose。FeedDock 会在统一媒体根目录写入 NFO、海报和背景图；可选的 `bangumi.ini` 额外写入 Bangumi ID。当前不调用 tinyMediaManager。代理只用于外部请求，本地服务应放入不使用代理列表。

# FeedDock 飞牛 OS 部署说明

## 1. 宿主机目录

默认 Compose 使用：

```text
/vol1/1000/应用/feeddock/data  → /data
/vol2/1000/影视                → /media
```

`/data` 保存数据库、Mikan 目录缓存和封面缓存；升级时不要删除。`/media` 必须挂载 qBittorrent 实际使用的同一份宿主机影视目录，但 qBittorrent 自己看到的路径可以不同。

宿主机影视目录不是 `/vol2/1000/影视` 时，只修改 Compose 左侧路径，容器内仍建议保持 `/media`：

```yaml
volumes:
  - "/你的/影视目录:/media"
```

## 2. 权限设置

飞牛默认配置：

```yaml
PUID: "0"
PGID: "0"
UMASK: "002"
TAKE_OWNERSHIP: "false"
```

这会让 FeedDock 以 root 身份运行，解决共享目录 UID/GID 不一致导致下载目录访问失败的问题。入口脚本不会递归 `chown` 整个影视库，只会创建并删除探针文件来确认 `/data` 和 `/media` 可写。

希望改为普通用户时，可以设置实际 UID/GID，但要先确保两个宿主机目录对该用户可读写。启动失败时查看容器日志，日志会明确指出哪个目录不可写。

## 3. 基础部署

使用项目中的 `docker-compose.fnos.yml`：

```bash
cd /你的/Compose目录
docker compose -f docker-compose.fnos.yml pull
docker compose -f docker-compose.fnos.yml up -d
```

默认访问地址：

```text
http://飞牛地址:7789
```

首次账号：

```text
admin / password
```

首次登录后必须修改密码。

## 4. qBittorrent 路径

FeedDock 网页“刮削设置”中的“FeedDock 本地媒体挂载目录”建议填写：

```text
/media
```

qBittorrent 可以把同一个宿主机影视目录挂载到 `/media`，也可以使用飞牛宿主机路径，例如 `/vol2/1000/影视`。网页“下载设置”填写 qBittorrent 实际使用的根目录，FeedDock 会把相对目录映射到 `/media`：

```text
qBittorrent：/vol2/1000/影视/番剧名称 (2026)/Season 01
FeedDock：   /media/番剧名称 (2026)/Season 01
```

番剧名、年份、季度等子目录通过订阅中的路径模板生成。qBittorrent 根目录必须填写它自己实际使用的路径；FeedDock 本地根目录必须填写 FeedDock 容器真实挂载路径。

默认模板：

```text
{base}/{media_folder}/Season {season:02}
```

启用“文件已下载自动跳过”前，所有启用订阅都必须开启自动重命名。FeedDock 会在后端阻止不符合条件的创建、编辑、导入或批量启用操作。

## 5. TMDB 与 Bangumi

网页打开“设置 → 刮削设置”：

- TMDB API 默认 `https://api.themoviedb.org`；
- TMDB Image 默认 `https://image.tmdb.org`；
- 密钥支持 32 位 v3 API Key 或 v4 Read Access Token；
- Bangumi Token 公开读取通常可留空；
- 自动刮削会同步标题、简介、评分和总集数，并在统一媒体目录写入 NFO、海报与背景图；
- 本地媒体挂载目录默认来自 `MEDIA_LOCAL_ROOT=/media`，可以在网页中单独修改，不再被 qBittorrent 保存路径覆盖。

选择搜索结果后，订阅名称会自动写成：

```text
从0位居民开始的边境领主大人 (2026)
```

订阅卡片会显示海报、简介、TMDB/Bangumi ID、总集数和媒体目录。

## 6. 下载完成后本地刮削与媒体库识别

默认开启本地刮削。工作流程：

```text
推送 qBittorrent（可配置重试、并发和做种时长）
→ 获取任务哈希并追加已缓存 Tracker
→ 获取种子文件列表并安全规范文件名
→ 等待 qBittorrent 进度达到 100%
→ 同步外部元数据
→ 写入 tvshow/movie/season/episode NFO、poster 和 fanart
→ 可选写入 bangumi.ini
→ 飞牛影视/Emby/Jellyfin 扫描同一媒体目录
```

多视频合集不会自动猜测每个文件对应的集数，因此只写入剧集根目录与季级元数据，单集 NFO 会跳过。“下载”页面的“检查下载完成”可以立即执行一次检查，后台默认每 2 分钟检查一次。历史下载可使用“刷新 → 刮削已完成媒体”补写。

## 7. 清理界面记录

- “清理条目”：隐藏最近条目，但保留 RSS 去重指纹，不会导致旧内容重复下载；
- “清理日志”：删除当前系统日志；
- 新产生的条目和日志会继续显示。

## 8. 更新

GitHub Actions 发布新镜像后执行：

```bash
cd /你的/Compose目录
docker compose -f docker-compose.fnos.yml pull
docker compose -f docker-compose.fnos.yml up -d
```



升级后建议强制刷新一次浏览器，并确认首页只显示订阅列表。下载、设置和日志现在通过顶部菜单进入。网页“系统管理”中的重启与关闭默认不可用；需要远程控制进程时，在 Compose 中显式设置：

```yaml
environment:
  FEEDDOCK_ALLOW_SYSTEM_ACTIONS: "true"
```

启用前请检查 Compose 的 `restart` 策略：`restart: unless-stopped` 或 `always` 可能会在“关闭”后重新拉起容器。普通部署建议保持 `false`，继续使用飞牛或 Docker 管理界面执行容器操作。

从更旧版本直接升级时，v1.12.0 的订阅监控字段仍会在启动时自动增量补齐，不会删除历史订阅、条目或指纹。部署后可在网页“通知”中配置 Telegram、Bark 或 Webhook；所有通知默认关闭。

## 1.17.1 DNS 修复

飞牛 Docker 在部分网络中会把不可达的宿主机或嵌入式 DNS 写入容器，表现为所有外部站点同时出现 `[Errno -3] Temporary failure in name resolution`。新版 Compose 已为 `feeddock` 服务指定 223.5.5.5、119.29.29.29 和 1.1.1.1，并设置短超时和轮换。

升级后必须选择“重新创建容器”，仅重启旧容器不会更新 `/etc/resolv.conf`。部署完成后可在“设置 → 代理设置 → 诊断 DNS”确认解析结果。完整步骤见 `NETWORK_TROUBLESHOOTING.md`。


## 1.17.0 原站目录说明

ANI.BT 和 Anime Garden 现在直接访问各自原站 API，不再需要 `ANIME_CATALOG_BASE_URLS`。飞牛容器必须能够解析并访问：

```text
anibt.net
api.animes.garden
Mikan 配置的主站或镜像
```

每个站点使用独立缓存。原站暂时不可用时，只会显示该站点的旧缓存，不会用 Mikan 或其它站点内容替代。升级会自动增加订阅身份字段和 `anime_preferences` 表。

## 9. 故障排查

### 容器提示 `/media` 不可写

确认：

1. Compose 左侧宿主机目录真实存在；
2. `PUID`、`PGID` 是否为 `0`；
3. 挂载不是只读；
4. 飞牛共享目录权限允许容器访问。

### ANI.BT 或 Anime Garden 提示 DNS 解析失败

1.17.0 会直接访问目标站点，不再访问公共周历镜像。请在 FeedDock 容器内确认对应域名可解析：

```bash
getent hosts anibt.net
getent hosts api.animes.garden
```

如果原站暂时不可用但曾成功缓存过，页面会继续显示该站点旧缓存并附带刷新错误；没有缓存时会明确报错，不会用其它站点目录代替。代理用户应在网页“代理设置”中配置可访问这些域名的代理。

### 最终下载路径仍不正确

网页只填写容器路径 `/media`，不要填写 `/vol2/1000/影视`。目录结构通过模板设置。保存 qBittorrent 配置后，全部订阅根目录会自动同步。

### 预览显示 E01 示例

表示当前粘贴的是番剧名称而不是实际 RSS 发布标题。E01 仅用于展示路径和文件名；实际下载时仍会从 RSS 标题读取真实集数。

### 文件一直等待完成

FeedDock 已经找到任务，但 qBittorrent 尚未达到 100%。可以在最近条目查看进度，或点击“检查下载完成”。

### 显示 `manual_required`

种子包含多个视频文件，FeedDock 不会把合集全部改成同一集数名称，需要人工确认文件对应关系。

### 外部媒体库没有识别

先检查媒体目录内是否已经生成 `tvshow.nfo`/`movie.nfo`、海报和背景图，再确认飞牛影视、Emby 或 Jellyfin 已扫描同一个宿主机影视目录。若没有生成文件，请在日志中查找“媒体库元数据写入失败”，重点检查 `/media` 是否可写及容器路径是否一致。
