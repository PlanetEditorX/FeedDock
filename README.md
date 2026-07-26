# FeedDock

当前版本：`1.10.0`

## v1.10.0：季度识别、规范命名、定时窗口与代理

### 登录与密钥显示

- “首次成功登录后强制修改密码”提示只在管理员仍使用初始密码时显示；密码修改完成后，后续登录页不再显示。
- 登录、修改密码以及管理页面中的 qBittorrent 密码、TMDB/Bangumi Token、代理地址均提供小眼睛按钮。
- 已保存密钥默认不回传到页面，只有管理员主动点击小眼睛时才通过受保护接口读取。

### TMDB 季度识别

每个订阅支持三种季度模式：

- `title`：从“第二季”“第2期”“Season 2”“S02”等标题文字识别；这是新订阅默认值。
- `latest`：选择 TMDB 返回的最高且已播出的正季，自动排除 Season 0 特别篇。
- `manual`：始终使用手动填写的季编号。

TMDB 详情会返回全部季度、每季首播日期和集数。选择结果后，FeedDock 会把最终采用的季度写回订阅。

### 元数据人工确认

新增订阅时，如果尚未在表单中确认元数据，会自动打开确认窗口。窗口可切换：

1. TMDB：最适合 Emby 识别及季度结构；
2. Bangumi：适合中文名、日文名、简介和动画话数；
3. AniList：公开动漫 API，可作为 TMDB/Bangumi 匹配不准时的备选；
4. 完全跳过：保留手动标题，仅使用本地命名，不再强制匹配。

### 外部媒体库识别

FeedDock 不再写入本地 NFO/图片，也不再调用 tinyMediaManager。它只负责把下载目录和文件名规范化，例如保留 `标题 (年份)`、季度目录和 `[tmdbid=...]`，后续识别交给飞牛影视、Emby、Jellyfin 或其他外部媒体库完成。

### 每日统一执行时间

可开启下载等待：RSS 先记录为“等待定时推送”，每天指定时间统一发送给 qBittorrent。

默认时间为 `02:00`，时区默认 `Asia/Shanghai`。管理页面提供“立即执行一次”按钮。

### 全局代理

支持：

- `http://`、`https://`；
- `socks5://`、`socks5h://`；
- 带用户名密码的代理 URL；
- `NO_PROXY` 风格的排除列表。

代理应用于 RSS、Mikan、封面、TMDB、Bangumi、AniList、GitHub 更新检查等外部请求。qBittorrent 等本地服务建议加入排除列表。

# FeedDock

FeedDock 是一个自托管的 RSS 番剧订阅管理器。它读取你配置的 RSS，将匹配条目推送给 qBittorrent，并提供 Mikan 季度目录、持久过滤、封面缓存、TMDB/Bangumi 元数据匹配、规范目录和文件名、总集数同步。

当前版本：`1.10.0`

## v1.10.0 修正与增强

- 选择 TMDB/Bangumi 条目后，订阅名称、来源标题和卡片统一显示 `标题 (年份)`。
- 无法从示例标题识别集数时，预览使用明确标注的 `S01E01` 演示值，不再生成 `Eunknown`；真实下载仍必须识别到真实集数才自动改名。
- qBittorrent 下载根目录和订阅根目录强制使用同一个容器路径，默认 `/media`；子目录结构只由模板控制。
- 订阅卡片显示元数据海报、简介、来源 ID、总集数和最终媒体目录。
- qBittorrent 报告 100% 下载完成后只更新完成状态，不再执行本地 NFO/图片生成或 TMM 调用。
- 最近条目支持安全清理（保留去重指纹），系统日志支持清空。
- 新订阅和本次升级后的旧订阅默认关闭 FeedDock 刮削，由外部媒体库识别。
- 飞牛默认以 `PUID=0`、`PGID=0` 运行，并在启动时实际检查 `/data`、`/media` 可写性。
- 保留手动/TMDB/Bangumi/自动命名、板块折叠记忆、总集数锁定、Mikan 本地缩略图缓存等现有功能。

## 工作流程

```text
Mikan/RSS
   ↓
标题与集数识别
   ↓
TMDB 或 Bangumi 元数据匹配
   ↓
生成规范目录和文件名
   ↓
推送 qBittorrent（savepath + rename + 唯一 tag）
   ↓
qBittorrent 获取磁力元数据后，通过 WebUI API 重命名视频和同名字幕
   ↓
qBittorrent 达到 100% 后记录完成状态，外部媒体库自行识别
```

FeedDock 不提供媒体资源，也不会绕过 qBittorrent 直接移动正在做种的文件。

## 推荐目录结构

电视剧/季度番剧：

```text
/media/
└── 金牌得主 (2025) [tmdbid=123456]/
    └── Season 02/
        ├── 金牌得主 - S02E01.mkv
        ├── 金牌得主 - S02E01.zh-CN.ass
        └── season.nfo
```

剧场版/电影：

```text
/media/
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

网页打开“元数据设置”。

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

## 外部媒体库识别

FeedDock 不再负责本地刮削。只要目录和文件名规范，飞牛影视、Emby、Jellyfin 等外部媒体库通常可以自行识别。

飞牛示例：

```yaml
volumes:
  - "/vol1/1000/应用/feeddock/data:/data"
  - "/vol2/1000/影视:/media"

environment:
  PUID: "0"
  PGID: "0"
  DOWNLOAD_PATH: "/media"
  MEDIA_LOCAL_ROOT: "/media"
```

qBittorrent 与 FeedDock 必须把同一宿主机目录挂载到相同容器路径，推荐统一使用 `/media`：

```yaml
DOWNLOAD_PATH: "/media"
MEDIA_LOCAL_ROOT: "/media"
```

然后订阅路径使用：

```text
{base}/{media_folder}/Season {season:02}
```

qBittorrent 报告任务 100% 完成后，FeedDock 只记录完成状态并保留规范命名结果。

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

## 清理最近条目与日志

- “清理条目”只把历史条目标记为隐藏，保留 RSS 指纹，因此同一旧条目不会再次下载。
- “清理日志”会删除全部系统日志。
- 新产生的条目和日志会继续正常显示。

## 飞牛权限

默认 Compose 使用：

```yaml
PUID: "0"
PGID: "0"
UMASK: "002"
TAKE_OWNERSHIP: "false"
```

容器以 root 运行可规避飞牛共享目录常见的 UID/GID 不一致问题。入口脚本不会递归修改整个影视库所有者，只会测试 `/data` 和 `/media` 是否可写；不可写时容器会直接输出明确错误。确认宿主机挂载目录正确后，也可改为普通 UID/GID，并自行授予目录读写权限。

## 重要环境变量

```dotenv
FEEDDOCK_BUILD_VERSION=1.10.0
METADATA_LANGUAGE=zh-CN
METADATA_AUTO_SYNC_HOURS=24
TMDB_READ_ACCESS_TOKEN=
BANGUMI_ACCESS_TOKEN=
MEDIA_LOCAL_ROOT=/media
EMBY_URL=
EMBY_API_KEY=
MIKAN_THUMBNAIL_WIDTH=240
MIKAN_THUMBNAIL_HEIGHT=320
```

敏感 Token 可以在网页中保存，数据库位于 `/data/feeddock.db`。接口返回只显示是否已配置，不返回密钥原文。

## 数据库升级

启动时会对 SQLite 执行兼容迁移，不删除旧订阅和下载去重指纹。旧订阅仍默认不开启自动重命名；FeedDock 刮削会迁移为关闭。所有订阅的下载根目录会同步为当前 qBittorrent 根目录。

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


## 清理最近条目与日志

- “清理条目”只隐藏历史显示，不删除 RSS 去重指纹，因此旧条目不会重新下载。
- “清理日志”会删除全部系统日志。
- 新产生的条目和日志会继续正常显示。

## DEBUG 调试日志

“系统日志”板块可以在 `INFO` 与 `DEBUG` 之间切换。DEBUG 会额外记录 API 请求、添加/编辑订阅的处理阶段、请求编号、异常类型和完整 Python traceback。500 错误会在页面中显示请求编号，展开对应 ERROR 日志即可查看具体失败位置。

日志同时写入网页、Docker 标准输出和 `/data/logs/feeddock.log`。敏感密码、Token、API Key、Cookie 和代理认证信息会自动隐藏。详细操作见 [DEBUG_LOGGING.md](DEBUG_LOGGING.md)。
