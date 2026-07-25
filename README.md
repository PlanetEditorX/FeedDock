# FeedDock

FeedDock 是一个自托管的 RSS 番剧订阅管理器。它读取你配置的 RSS，将匹配条目推送给 qBittorrent，并提供 Mikan 季度目录、持久过滤、封面缓存、TMDB/Bangumi 元数据匹配、Emby 规范命名、总集数同步和可选本地 NFO 刮削。

当前版本：`1.9.0`

## v1.9.0 新增

- 手动、TMDB、Bangumi、自动四种命名模式。
- Emby 友好目录：`标题 (年份) [tmdbid=ID]/Season 01`。
- Emby 友好文件名：`标题 - S01E01.mkv`，字幕同步改名。
- TMDB/Bangumi 搜索、详情读取、首播年份、简介、海报和总集数同步。
- 总集数手动锁定；锁定后第三方同步不会覆盖。
- 所有主板块可收起/展开，浏览器自动记住状态。
- 可选生成 `tvshow.nfo`、`season.nfo`、`movie.nfo`、`poster.jpg`、`backdrop.jpg`。
- 可选通知 Emby 扫描媒体库。
- Mikan 240×320 WebP 封面本地优先缓存。

## 工作流程

```text
Mikan/RSS
   ↓
标题与集数识别
   ↓
TMDB 或 Bangumi 元数据匹配
   ↓
生成 Emby 目录和文件名
   ↓
推送 qBittorrent（savepath + rename + 唯一 tag）
   ↓
qBittorrent 获取磁力元数据后，通过 WebUI API 重命名视频和同名字幕
   ↓
可选写入本地 NFO/海报，并通知 Emby 刷新
```

FeedDock 不提供媒体资源，也不会绕过 qBittorrent 直接移动正在做种的文件。

## 推荐目录结构

电视剧/季度番剧：

```text
/downloads/rss/
└── 金牌得主 (2025) [tmdbid=123456]/
    └── Season 02/
        ├── 金牌得主 - S02E01.mkv
        ├── 金牌得主 - S02E01.zh-CN.ass
        └── season.nfo
```

剧场版/电影：

```text
/downloads/rss/
└── 电影标题 (2026) [tmdbid=123456]/
    ├── 电影标题 (2026).mkv
    ├── movie.nfo
    ├── poster.jpg
    └── backdrop.jpg
```

## 快速启动

```bash
cd /你的/FeedDock目录
cp .env.example .env
docker compose up -d --build
```

打开：`http://服务器地址:7789`

首次账号由环境变量决定。飞牛默认 Compose 使用：

```text
用户名：admin
密码：password
```

首次登录后必须修改密码，密码保存在 `/data/feeddock.db`。

## 元数据配置

网页打开“元数据与刮削设置”。

### TMDB

填写 TMDB API Read Access Token。TMDB 用于：

- Emby 最稳定的名称和外部 ID；
- 电视剧季度详情；
- 当前季度总集数；
- 中文简介、海报和背景图。

### Bangumi

Bangumi 公开读取通常不要求 Token，可直接搜索。它用于：

- 中文名和日文原名；
- 动画条目、放送日期和话数；
- 动漫专属简介与封面。

### 推荐匹配顺序

1. 先用 Bangumi 找到准确动漫条目。
2. 再用 TMDB 搜索并选择正确电视剧/电影条目。
3. 命名来源选择 `TMDB` 或 `自动`。
4. 保存前点击“预览规则和命名”。

自动模式的名称优先级：

```text
手动规范标题 > TMDB 标题 > Bangumi 标题 > 原订阅名称
```

## 自动获取总集数

选择元数据搜索结果时，FeedDock 会立即读取详情：

- TMDB 电视剧：读取指定 `Season N` 的 episode 列表数量；
- TMDB 电影：总数为 1；
- Bangumi：优先读取条目话数，缺失时读取 episode API 总数。

勾选“锁定总集数”后，任何自动同步都不会覆盖手动值。

勾选“定期自动同步元数据”后，RSS 轮询时会按照 `METADATA_AUTO_SYNC_HOURS` 检查是否需要更新，第三方网站临时故障不会阻断 RSS 下载。

## qBittorrent 规范重命名

默认文件模板：

```text
{title} - S{season:02}E{episode:02}
```

默认保存路径模板：

```text
{base}/{media_folder}/Season {season:02}
```

可用变量：

```text
{base}
{subscription}
{reference_title}
{tmdb_title}
{manual_title}
{title}
{media_folder}
{season}
{season:02}
{episode}
{episode:02}
{episode_pad}
{year}
{tmdb_id}
{bangumi_id}
{media_type}
```

处理逻辑：

1. 添加任务时传递 `savepath`、`rename` 和唯一标签 `feeddock-item-ID`。
2. 每 2 分钟查询一次等待规范化的任务。
3. 磁力元数据未完成时保持 `pending`。
4. 只有一个视频文件时，通过 qBittorrent `renameFile` 改名。
5. 同目录且与视频原文件同前缀的字幕同步改名。
6. 多视频合集不会猜测集数，状态标记为 `manual_required`。

顶部“规范化文件名”按钮可以立即执行一次检查。

## 本地刮削

仅让 Emby 在线识别时，不需要把媒体目录挂载给 FeedDock。目录包含 `[tmdbid=...]` 后，Emby 通常即可稳定识别。

需要 FeedDock 写入本地文件时，必须让 FeedDock 与 qBittorrent 看见同一份媒体目录。

飞牛示例：

```yaml
volumes:
  - "/vol1/1000/应用/feeddock/data:/data"
  - "/vol2/1000/影视:/media"

environment:
  DOWNLOAD_PATH: "/downloads/rss"
  MEDIA_LOCAL_ROOT: "/media"
```

这里要求 qBittorrent 的 `DOWNLOAD_PATH` 与 FeedDock 的本地挂载存在可映射关系。最简单的方式是两个容器都把同一宿主机目录挂载到相同容器路径，例如都使用 `/media`：

```yaml
DOWNLOAD_PATH: "/media"
MEDIA_LOCAL_ROOT: "/media"
```

然后订阅路径使用：

```text
{base}/{media_folder}/Season {season:02}
```

启用“允许生成本地 NFO 与图片”后，成功规范化文件时会自动：

- 写入 `tvshow.nfo` / `season.nfo` 或 `movie.nfo`；
- 保存 `poster.jpg` 和 `backdrop.jpg`；
- 本地图片已存在且有效时不重复下载；
- 已配置 Emby 地址和 API Key 时通知 Emby 刷新。

也可以在订阅卡片点击“刮削本地文件”。

## 板块收缩与记忆

所有主板块标题右侧都有“收起/展开”。状态保存在浏览器：

```text
localStorage: feeddock.panelState.v1
```

页面刷新、重新登录和容器重启不会丢失。同一账号在不同浏览器中分别保存状态。

## Mikan 缓存

目录缓存保存在 SQLite，封面缓存目录为：

```text
/data/mikan-image-cache
```

加载顺序：

```text
浏览器缓存 → FeedDock 本地图片 → Mikan 官网
```

只要本地图片有效，即使超过浏览器缓存时间也不会主动重新访问 Mikan。仅在文件缺失、为空、损坏或图片 URL 改变时重新获取。

## 重要环境变量

```dotenv
FEEDDOCK_BUILD_VERSION=1.9.0
METADATA_LANGUAGE=zh-CN
METADATA_AUTO_SYNC_HOURS=24
TMDB_READ_ACCESS_TOKEN=
BANGUMI_ACCESS_TOKEN=
MEDIA_LOCAL_ROOT=
EMBY_URL=
EMBY_API_KEY=
MIKAN_THUMBNAIL_WIDTH=240
MIKAN_THUMBNAIL_HEIGHT=320
```

敏感 Token 可以在网页中保存，数据库位于 `/data/feeddock.db`。接口返回只显示是否已配置，不返回密钥原文。

## 数据库升级

启动时会对 SQLite 执行仅新增字段的兼容迁移，不删除旧订阅和历史条目。旧订阅默认不开启重命名；编辑旧订阅后可主动勾选。

新增字段包括：

- `naming_mode`、`media_type`、`manual_title`；
- `tmdb_id`、`bangumi_id`、`metadata_year`；
- `total_episodes_locked`、`total_episodes_source`；
- `rename_enabled`、`file_name_template`、`scrape_enabled`；
- 下载条目的 `desired_name`、`qbit_tag`、`torrent_hash` 和规范化状态。

## 开发验证

```bash
cd /你的/FeedDock目录
python -m pip install -r requirements.txt
python -m pytest -q
python -m compileall -q app
node --check app/static/app.js
```

详细飞牛部署见 [FNOS_DEPLOY.md](FNOS_DEPLOY.md)，功能设计与限制见 [METADATA_NAMING.md](METADATA_NAMING.md)。
