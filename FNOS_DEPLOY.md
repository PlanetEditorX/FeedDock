# FeedDock v1.16.1 飞牛 OS 部署

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

网页保存的设置优先于 Compose。FeedDock 不再调用 tinyMediaManager 或写本地 NFO/海报；可选的 `bangumi.ini` 只写入 Bangumi ID。代理只用于外部请求，本地服务应放入不使用代理列表。

# FeedDock 飞牛 OS 部署说明

## 1. 宿主机目录

默认 Compose 使用：

```text
/vol1/1000/应用/feeddock/data  → /data
/vol2/1000/影视                → /media
```

`/data` 保存数据库、Mikan 目录缓存和封面缓存；升级时不要删除。`/media` 必须与 qBittorrent 使用同一份宿主机影视目录。

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

FeedDock 网页中的“统一媒体根目录”建议填写：

```text
/media
```

qBittorrent 容器也必须把同一个宿主机影视目录挂载到 `/media`，并将下载保存路径设在 `/media` 下。FeedDock 会自动让以下两处保持一致：

```text
qBittorrent 下载根目录
订阅统一下载根目录
```

番剧名、年份、季度等子目录通过订阅中的路径模板生成，不要把宿主机路径 `/vol2/...` 填进容器页面。

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
- 自动刮削表示同步标题、评分、海报地址和总集数，不会下载 NFO 或图片；
- 本地媒体挂载目录会自动同步为 `/media`，不可单独修改。

选择搜索结果后，订阅名称会自动写成：

```text
从0位居民开始的边境领主大人 (2026)
```

订阅卡片会显示海报、简介、TMDB/Bangumi ID、总集数和媒体目录。

## 6. 下载完成后外部识别

FeedDock 不再生成 NFO/图片，也不调用 tinyMediaManager。开启 `bangumi.ini` 后可在番剧根目录写入 Bangumi ID。工作流程：

```text
推送 qBittorrent（可配置重试、并发和做种时长）
→ 获取任务哈希并追加已缓存 Tracker
→ 获取种子文件列表并安全规范文件名
→ 等待 qBittorrent 进度达到 100%
→ 可选写入 bangumi.ini 并记录完成状态
→ 飞牛影视/Emby/Jellyfin 等外部媒体库自行识别
```

多视频合集不会自动猜测每个文件对应的集数。“下载”页面的“检查下载完成”可以立即执行一次检查，后台默认每 2 分钟检查一次。

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

v1.16.1 修复非 Mikan 周历对单一 GitHub Raw 域名的依赖：默认依次尝试多个 `bangumi-data` 镜像，全部失败时自动复用 Mikan 季度目录和缓存。升级不新增数据库字段，不需要手工 SQL。

升级后建议强制刷新一次浏览器，并确认首页只显示订阅列表。下载、设置和日志现在通过顶部菜单进入。网页“系统管理”中的重启与关闭默认不可用；需要远程控制进程时，在 Compose 中显式设置：

```yaml
environment:
  FEEDDOCK_ALLOW_SYSTEM_ACTIONS: "true"
```

启用前请检查 Compose 的 `restart` 策略：`restart: unless-stopped` 或 `always` 可能会在“关闭”后重新拉起容器。普通部署建议保持 `false`，继续使用飞牛或 Docker 管理界面执行容器操作。

从更旧版本直接升级时，v1.12.0 的订阅监控字段仍会在启动时自动增量补齐，不会删除历史订阅、条目或指纹。部署后可在网页“通知”中配置 Telegram、Bark 或 Webhook；所有通知默认关闭。

## 9. 故障排查

### 容器提示 `/media` 不可写

确认：

1. Compose 左侧宿主机目录真实存在；
2. `PUID`、`PGID` 是否为 `0`；
3. 挂载不是只读；
4. 飞牛共享目录权限允许容器访问。

### ANI.BT、Anime Garden、Nyaa、SubsPlease 提示 DNS 解析失败

1.16.1 会自动尝试多个周历镜像，并在全部失败时回退 Mikan。升级后先强制刷新浏览器，再点击“强制更新”。

需要自定义镜像时，在 Compose 中设置：

```yaml
environment:
  ANIME_CATALOG_BASE_URLS: "https://你的镜像/data/items,https://备用镜像/data/items"
```

该配置只影响番剧周历元数据，不改变各资源站 RSS 地址。

### 最终下载路径仍不正确

网页只填写容器路径 `/media`，不要填写 `/vol2/1000/影视`。目录结构通过模板设置。保存 qBittorrent 配置后，全部订阅根目录会自动同步。

### 预览显示 E01 示例

表示当前粘贴的是番剧名称而不是实际 RSS 发布标题。E01 仅用于展示路径和文件名；实际下载时仍会从 RSS 标题读取真实集数。

### 文件一直等待完成

FeedDock 已经找到任务，但 qBittorrent 尚未达到 100%。可以在最近条目查看进度，或点击“检查下载完成”。

### 显示 `manual_required`

种子包含多个视频文件，FeedDock 不会把合集全部改成同一集数名称，需要人工确认文件对应关系。

### 外部媒体库没有识别

确认飞牛影视、Emby 或 Jellyfin 已扫描同一个宿主机影视目录，并检查目录名、年份、季度目录和文件名是否符合媒体库识别习惯。
