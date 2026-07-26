# FeedDock v1.10.0 飞牛 OS 部署

## 新增可选配置

```yaml
environment:
  ANILIST_API_URL: "https://graphql.anilist.co"
  TMM_URL: "http://host.docker.internal:7878"
  TMM_API_KEY: ""
  AUTOMATION_TIME: "02:00"
  AUTOMATION_TIMEZONE: "Asia/Shanghai"
  OUTBOUND_PROXY_URL: ""
  OUTBOUND_NO_PROXY: "localhost,127.0.0.1,host.docker.internal"
```

网页保存的设置优先于 Compose。tinyMediaManager 需要启用 HTTP API，并与 FeedDock、qBittorrent 使用相同的 `/media` 路径。代理只用于外部请求，本地服务应放入不使用代理列表。

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

这会让 FeedDock 以 root 身份运行，解决共享目录 UID/GID 不一致导致 NFO、海报无法写入的问题。入口脚本不会递归 `chown` 整个影视库，只会创建并删除探针文件来确认 `/data` 和 `/media` 可写。

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

qBittorrent 容器也必须把同一个宿主机影视目录挂载到 `/media`，并将下载保存路径设在 `/media` 下。FeedDock 会自动让以下三处保持一致：

```text
qBittorrent 下载根目录
订阅统一下载根目录
FeedDock 本地刮削根目录
```

番剧名、年份、季度等子目录通过订阅中的路径模板生成，不要把宿主机路径 `/vol2/...` 填进容器页面。

默认模板：

```text
{base}/{media_folder}/Season {season:02}
```

## 5. TMDB 与 Bangumi

网页打开“元数据与刮削设置”：

- TMDB Read Access Token：用于搜索、简介、海报、年份和季度总集数；
- Bangumi Token：公开读取通常可留空；
- 元数据语言：建议 `zh-CN`；
- 本地媒体挂载目录会自动同步为 `/media`，不可单独修改。

选择搜索结果后，订阅名称会自动写成：

```text
从0位居民开始的边境领主大人 (2026)
```

订阅卡片会显示海报、简介、TMDB/Bangumi ID、总集数和媒体目录。

## 6. 下载完成后自动刮削

新订阅默认开启“允许生成本地 NFO 与图片”。工作流程：

```text
推送 qBittorrent
→ 获取种子文件列表并安全规范文件名
→ 等待 qBittorrent 进度达到 100%
→ 写入 tvshow.nfo / season.nfo / movie.nfo
→ 下载 poster.jpg / backdrop.jpg
→ 已配置 Emby 时通知媒体库刷新
```

多视频合集不会自动猜测每个文件对应的集数，但任务完成后仍可写入剧集级 NFO 和图片。顶部“检查下载完成/刮削”可以立即执行一次检查，后台默认每 2 分钟检查一次。

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

更新后浏览器执行一次强制刷新。v1.10.0 会把旧订阅的下载根目录同步到当前 qBittorrent 根目录，并默认开启本地刮削；不会删除历史指纹和订阅数据。

## 9. 故障排查

### 容器提示 `/media` 不可写

确认：

1. Compose 左侧宿主机目录真实存在；
2. `PUID`、`PGID` 是否为 `0`；
3. 挂载不是只读；
4. 飞牛共享目录权限允许容器访问。

### 最终下载路径仍不正确

网页只填写容器路径 `/media`，不要填写 `/vol2/1000/影视`。目录结构通过模板设置。保存 qBittorrent 配置后，全部订阅根目录会自动同步。

### 预览显示 E01 示例

表示当前粘贴的是番剧名称而不是实际 RSS 发布标题。E01 仅用于展示路径和文件名；实际下载时仍会从 RSS 标题读取真实集数。

### 文件一直等待完成

FeedDock 已经找到任务，但 qBittorrent 尚未达到 100%。可以在最近条目查看进度，或点击“检查下载完成/刮削”。

### 显示 `manual_required`

种子包含多个视频文件，FeedDock 不会把合集全部改成同一集数名称，需要人工确认文件对应关系。

### Emby 没有刷新

检查 Emby 地址、API Key 和网络连通性。即使通知失败，本地 NFO 和图片仍会保留。
