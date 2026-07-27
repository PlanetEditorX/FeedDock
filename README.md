# FeedDock

当前版本：`1.17.12`

FeedDock 是一个面向自托管/NAS 环境的 RSS 番剧订阅管理器。它负责发现番剧、解析集数、执行匹配规则、生成规范目录与文件名、把任务推送到 qBittorrent，并在下载完成后向媒体目录写入标准 NFO、海报和背景图。飞牛影视、Emby、Jellyfin 等媒体服务器仍负责扫描媒体目录并建立自身索引。

使用前请阅读 [`DISCLAIMER.md`](DISCLAIMER.md)。FeedDock 不提供、托管或审核第三方种子与媒体内容；使用者应自行确认来源、授权和用途合法。


## v1.17.12：配置备份与跨站 RSS 恢复

- 新增全系统 JSON 备份与恢复，覆盖网页有效配置、全部订阅和番剧隐藏偏好；
- 敏感值默认不导出，可选择包含 qBittorrent 密码、API Token、代理与通知私密地址；
- 继续支持仅订阅导入导出，格式升级为 v2 并加入导出时间；
- “更新 RSS”会按当前站点番剧 ID、Bangumi ID 和多个标题别名搜索 Mikan、ANI.BT、Anime Garden；
- 所有匹配字幕组 RSS 可填为主源、备用源，或直接保存并检查当前订阅；
- `主 RSS 没有条目` 在 INFO 日志中改为可操作提示，不再显示内部 Traceback。

详见 [`SYSTEM_BACKUP_AND_RSS_RECOVERY.md`](SYSTEM_BACKUP_AND_RSS_RECOVERY.md) 和 [`RSS_QUICK_UPDATE.md`](RSS_QUICK_UPDATE.md)。

## v1.17.11：免责声明与 RSS 快速更新

- 新增完整的 [`DISCLAIMER.md`](DISCLAIMER.md)，覆盖技术中立、用户义务、第三方风险、知识产权、安全、依法不得免责的情形和终止维护权；
- 系统设置内可直接阅读免责声明摘要与完整条款；
- 每张订阅卡片新增“更新 RSS”，直接打开 RSS 编辑区域；
- 编辑订阅时可“仅保存 RSS”或“保存 RSS 并立即检查”，无需重新提交其它配置；
- RSS 地址变化后自动重新识别来源和原站番剧 ID。

## v1.17.10：自动识别容器媒体挂载路径

- `MEDIA_LOCAL_ROOT` 未配置时默认使用容器内 `/media`；
- 自动修复数据库中误保存的飞牛宿主机 `/vol*` 路径；
- qBittorrent 路径与 FeedDock 本地挂载路径继续独立映射；
- 自定义 Compose 只要挂载 `/vol2/1000/影视:/media`，刮削会检查 `/media/...`。

详见 [MEDIA_PATH_DEFAULT_1.17.10.md](MEDIA_PATH_DEFAULT_1.17.10.md)。

## v1.17.9：媒体去重、孤儿元数据清理与静态版本清单

- 推送 qBittorrent 前检查目标媒体目录；规范命名后的目标视频已经存在时直接跳过。
- 启用“文件已下载自动跳过”后，还会使用 `SxxExx` 集数标记识别被其它媒体工具再次改名的视频。
- 自动或手动刷新订阅时，若已刮削目录只剩 NFO/海报而没有视频，会清理 FeedDock 生成的孤儿元数据。
- 版本检查优先读取并缓存 `update.json`，GitHub Release API 仅作为每天最多一次的备用检查。
- 系统设置会显示“在线更新”；真正更新 Docker 镜像仍通过 Watchtower HTTP API 安全执行。

详细说明见 [`MEDIA_LIBRARY_HYGIENE_AND_UPDATES.md`](MEDIA_LIBRARY_HYGIENE_AND_UPDATES.md)。

## v1.17.8：qBittorrent 临时标签自动清理

- `feeddock-item-*` 只在添加任务和确认真实 torrent hash 期间临时使用；
- qBittorrent 确认任务后立即移除任务标签，并删除标签定义；
- 后续下载进度、重命名、Tracker、完成检测和媒体刮削全部按 torrent hash 查询；
- 升级后后台自动清理历史 `feeddock-item-*` 标签，并先把可识别的 hash 回填到 SQLite；
- 仅清理 FeedDock 内部前缀，不修改用户创建的 qBittorrent 标签。

详细说明见 [`QBITTORRENT_TEMPORARY_TAGS.md`](QBITTORRENT_TEMPORARY_TAGS.md)。

## v1.17.7：下载器路径映射与单订阅刮削

- qBittorrent 保存路径与 FeedDock 容器内媒体挂载路径不再要求字符串完全一致；
- 按两个根目录的相对路径自动映射，例如 `/vol2/1000/影视/番剧` 映射到 `/media/番剧`；
- 旧版被强制保存成 qBittorrent 路径的 `media_local_root` 会在升级时恢复为 Compose 的 `MEDIA_LOCAL_ROOT`；
- 每张订阅卡片新增“刮削”按钮，只处理该订阅已经完成的下载条目；
- 路径错误会同时显示 qBittorrent 路径、下载根目录、FeedDock 本地根目录和最终映射路径。

详细说明见 [`MEDIA_PATH_MAPPING_1.17.7.md`](MEDIA_PATH_MAPPING_1.17.7.md)。


## v1.17.6：默认目录使用名称与年份

默认生成的电影和剧集目录不再附加 `[tmdbid=...]`，统一使用 `名称 (年份)`。TMDB ID 仍写入 NFO 元数据，并继续支持用户在自定义模板中显式使用 `{tmdb_id}`。已有目录不会自动改名，避免影响 qBittorrent 做种和媒体库索引。

## v1.17.5：本地媒体库 NFO 与图片刮削

- 修正 1.17.4 中“自动刮削”仅同步数据库、没有写入媒体库的问题；
- 下载完成后默认先同步 TMDB、Bangumi 或 AniList 元数据，再写入标准旁车文件；
- 电视番剧写入 `tvshow.nfo`、`season.nfo`、与视频同名的剧集 NFO、`poster`、`fanart` 和季海报；
- 电影写入 `movie.nfo`、与视频同名的 NFO、`poster` 和 `fanart`；
- 新增“刷新 → 刮削已完成媒体”，可为历史下载批量补写；
- 1.17.4 及更早版本的已完成条目会在升级时一次性进入刮削补写队列；
- 所有写入路径必须位于 qBittorrent 与 FeedDock 共用的媒体根目录内；
- 媒体服务器仍需扫描媒体目录，FeedDock 不直接修改 Emby/Jellyfin/飞牛影视数据库。

详细说明见 [`LOCAL_MEDIA_SCRAPING.md`](LOCAL_MEDIA_SCRAPING.md)。

## v1.17.3：qBittorrent 任务确认与种子文件直传

- “刷新全部订阅”点击后直接执行，不再显示二次确认；
- qBittorrent 添加接口返回 `Ok.` 后，必须按唯一任务标签回查任务列表；
- 只有查到实际任务名称、状态和哈希后，才记录“qBittorrent 已确认任务”；
- HTTP/HTTPS `.torrent` 由 FeedDock 使用当前代理下载并上传原始文件，不再让 qBittorrent 自行抓取远程 URL；
- 添加接口成功但任务列表不可见时，条目进入错误状态并可重试；
- 旧版假成功记录若持续找不到 qBittorrent 任务，会自动转为可重试错误；
- 日志保存任务标签、实际任务名称、状态和哈希，不输出 magnet、Torrent URL 或 passkey。

详细说明见 [`QBITTORRENT_PUSH_VERIFICATION.md`](QBITTORRENT_PUSH_VERIFICATION.md)。

## v1.17.1：容器 DNS 修复与网络诊断

- Compose 为 FeedDock 容器设置三个可轮换外部 DNS，修复 NAS Docker 继承不可达解析器的问题；
- 普通 Compose 可通过 `FEEDDOCK_DNS_PRIMARY`、`FEEDDOCK_DNS_SECONDARY` 和 `FEEDDOCK_DNS_TERTIARY` 覆盖；
- 新增“设置 → 代理设置 → 诊断 DNS”，显示容器 nameserver 和各原站域名解析结果；
- 外部请求测试会同时返回 DNS 状态，便于区分解析失败与 HTTPS/代理失败；
- DNS 修改后必须重新创建容器，普通重启不会更新 `/etc/resolv.conf`。

完整排障步骤见 [`NETWORK_TROUBLESHOOTING.md`](NETWORK_TROUBLESHOOTING.md)。

## v1.17.0：原站番剧目录与跨站状态

- Mikan 继续读取 Mikan 原站季度目录和字幕组；
- ANI.BT 直接读取原站 `api/seasons/anime` 和 `api/anime/groups`；
- Anime Garden 直接读取原站 `subjects` 和 `resources`；
- 三个站点的目录和详情缓存完全隔离，单站失败不会显示其它站点数据；
- 删除 `bangumi-data`、GitHub Raw、jsDelivr 和 Mikan 目录回退依赖；
- 订阅持久化 `source_type`、`source_anime_id` 和 `canonical_key`；
- 通过 Bangumi ID、原站 ID 和标题别名显示跨站订阅来源；
- 支持 `✓ 已订阅`、`Mikan 已订阅`、`✓ 已订阅 · Mikan 也已订阅`；
- 隐藏不喜欢的番剧会跨站生效，并兼容旧版 Mikan 星期过滤；
- Nyaa、SubsPlease 等没有稳定原生星期目录的来源继续作为“其它 RSS”使用。

完整设计见 [`MULTI_SOURCE_WEEKLY_CATALOG.md`](MULTI_SOURCE_WEEKLY_CATALOG.md)，站点说明见 [`SUBSCRIPTION_SOURCES.md`](SUBSCRIPTION_SOURCES.md)。

## v1.15.0：订阅站点入口

- “添加订阅”明确区分 Mikan、ANI.BT、Anime Garden（AG）和其它 RSS；
- Mikan 继续使用季度目录选番和字幕组；
- ANI.BT 与 Anime Garden 显示官方站点、RSS 文档、正确地址格式和全站流风险提示；
- 可在确认后填入站点全站 RSS，但默认不会自动填入，避免误下载大量资源；
- 后端按主机名边界识别订阅来源，防止相似恶意域名伪装；
- Mikan/AniBT URL 中的 `bangumiId` 或 `bgmId` 会自动写入订阅元数据；
- 订阅列表由后端返回稳定的 `source_type` 和 `source_label`。

详细说明见 [`SUBSCRIPTION_SOURCES.md`](SUBSCRIPTION_SOURCES.md)。

## v1.14.0：设置与自动化策略

本版本在 1.13.0 的订阅优先控制台基础上，补齐页面、刮削、下载、RSS 和 Tracker 设置，并接入真实执行流程：

- 新增五种主题色，以及按评分、拼音或更新时间排列订阅；
- 新增全局自动元数据同步、14 天追更窗口、可自定义 TMDB API/图片地址；
- TMDB 同时支持 32 位 v3 API Key 与 v4 Read Access Token；
- 下载完成后可安全生成 `bangumi.ini`，开启时会为符合条件的历史完成任务安排一次补写；
- 新增 qBittorrent 推送失败重试、同时下载限制和做种时长；
- 新增全局 RSS 开关、20 秒超时、已下载文件自动跳过和 Bangumi 总集数完结停用；
- 新增 Tracker 列表下载、去重缓存和任务哈希可用后的自动追加；
- 自动跳过所依赖的“自动重命名”条件在创建、编辑、导入和批量启用路径中均由后端强制校验；
- 新增 SQLite 增量字段，用于评分、Bangumi 总集数检查时间和 Tracker 处理状态。

完整行为、依赖条件与安全边界见 [`SETTINGS_REFERENCE.md`](SETTINGS_REFERENCE.md)。

## v1.13.0：订阅优先的任务式控制台

- 默认首页改为订阅统计、搜索、状态筛选和订阅卡片；
- 顶部依次提供“添加、下载、刷新、管理、设置、日志”；
- 添加入口支持 Mikan、ANI.BT、Anime Garden、其它 RSS 和批量合集；
- 管理视图支持批量启动、禁用、删除，以及 JSON 导入和导出；
- 下载、设置和日志使用独立 Hash 路由；
- 登录密码可随时修改，系统重启和关闭默认禁用。

界面结构见 [`UI_NAVIGATION.md`](UI_NAVIGATION.md)。

## v1.12.0：通知中心与订阅健康监控

本版本在分析 `wushuo894/ani-rss` 的订阅生命周期、通知和下载完成机制后，选择了最适合 FeedDock 当前架构的高价值功能：

- 新增 Telegram、Bark、通用 Webhook 通知中心；
- 可按事件启用：开始下载、下载完成、遗漏集数、订阅完结、RSS/推送错误、长期未更新；
- 新增“全部下载完成后自动停用订阅”；
- 新增按订阅设置的“连续未更新告警天数”；
- 遗漏和长期未更新通知具有持久化去重，重启后不会重复轰炸；
- 所有 qBittorrent 任务都写入唯一标签，未开启规范命名时也可检测下载完成；
- 通知失败仅记录 WARNING 日志，不阻断 RSS、任务推送或完成状态更新；
- 新增 SQLite 增量迁移和专用单元测试。

深入对比和取舍见 [`ANI_RSS_GAP_ANALYSIS.md`](ANI_RSS_GAP_ANALYSIS.md)，配置细节见 [`NOTIFICATIONS_AND_MONITORING.md`](NOTIFICATIONS_AND_MONITORING.md)。

## 主要能力

### 订阅与发现

- Mikan、ANI.BT、Anime Garden 各自读取原站番剧目录、标题搜索和独立缓存；
- 展开番剧后按需加载目标站点字幕组、最近资源和专用 RSS；
- 目录显示 `✓ 已订阅` 或 `Mikan 已订阅` 等跨站来源徽标；
- 隐藏偏好按统一番剧身份跨站生效；
- 主 RSS 与备用 RSS；
- 包含、排除、全局排除规则；
- 自定义集数正则、捕获组和集数偏移；
- 总集数、总集数锁定、只下载最新集和遗漏检测；
- TMDB、Bangumi、AniList 元数据搜索和人工确认。

### 下载与命名

- 推送 qBittorrent，并支持失败重试、并发空位等待和单任务做种时限；
- 自定义下载根目录、媒体目录模板和文件名模板；
- 可按规范目标文件名跳过已经存在的媒体文件；
- 可缓存并向新任务追加 Tracker 列表；
- 通过唯一 qBittorrent Tag 跟踪磁力元数据、进度和完成状态；
- 单视频任务可规范化视频名及同名字幕；
- 多视频合集不猜测文件对应关系，保留原名并提示手动处理；
- RSS 可即时推送，也可等待每日统一时间执行。

### 通知与监控

- Telegram Bot；
- Bark 官方服务或自建 Bark Server；
- 通用 JSON Webhook，可配置自定义请求头；
- 通知密钥默认不返回浏览器，管理员主动点击“小眼睛”时才读取；
- 下载完成通知与规范命名相互独立；
- 完结自动停用以 qBittorrent 已确认 `100%` 的整数集数为准；
- 长期未更新以“最近一次发现新的匹配 RSS 条目”为基准；
- 遗漏集数超过 10 集时仍在页面显示，但不主动通知，以降低初始配置误报。

## 工作流程

```text
多站点番剧周历 / RSS
    ↓
标题、规则和集数解析
    ↓
写入条目并生成保存路径 / 目标文件名
    ↓
即时或定时推送 qBittorrent（唯一 Tag、重试、并发限制、做种时限）
    ↓
每 2 分钟检查任务哈希、Tracker、进度和完成状态
    ↓
可选：生成 bangumi.ini、发送完成通知、判断整季完成并自动停用
    ↓
外部媒体库识别规范目录和文件名
```

FeedDock 不提供、存储或分发任何媒体资源，也不会绕过 qBittorrent 直接移动正在做种的文件。

## 快速启动

### 1. 准备配置

```bash
cp .env.example .env
```

至少修改：

```dotenv
ADMIN_PASSWORD=替换为强密码
QBIT_URL=http://你的-qBittorrent:8080
QBIT_USERNAME=admin
QBIT_PASSWORD=替换为真实密码
DOWNLOAD_PATH=/media
MEDIA_LOCAL_ROOT=/media
```

`DOWNLOAD_PATH` 是 qBittorrent 能识别的保存根目录；`MEDIA_LOCAL_ROOT` 是 FeedDock 容器中实际可见的媒体挂载目录。二者可以不同，但必须指向同一个宿主机目录。统一使用 `/media` 最简单；飞牛宿主机 qBittorrent 使用 `/vol2/1000/影视` 时，也可以让 FeedDock 使用 `/media` 并自动映射。

### 2. 启动

使用外部 qBittorrent：

```bash
docker compose up -d --build
```

同时启动示例 qBittorrent：

```bash
docker compose --profile with-qbit up -d --build
```

管理页面默认地址：`http://服务器地址:7789`。

首次成功登录后必须修改初始密码。新密码和网页保存的配置位于 `/data/feeddock.db`。

## 通知中心配置

管理页面的“通知中心”支持三个渠道，可同时启用：

### Telegram

1. 创建 Bot 并取得 Bot Token；
2. 获取目标用户、群组或频道的 Chat ID；
3. 填写 Token 和 Chat ID；
4. 勾选 Telegram 和需要的事件；
5. 点击“保存并测试”。

### Bark

- 默认服务地址：`https://api.day.app`；
- 自建 Bark Server 时替换服务地址；
- 填写 Device Key 后测试。

### 通用 Webhook

FeedDock 使用 `POST application/json`，基础结构如下：

```json
{
  "event": "download_completed",
  "title": "下载完成：示例番剧",
  "message": "第 3 集下载完成。",
  "subscription": {
    "id": 1,
    "name": "示例番剧",
    "enabled": true,
    "total_episodes": 12
  },
  "item": {
    "id": 10,
    "title": "原始 RSS 标题",
    "episode": "3",
    "status": "queued",
    "save_path": "/media/示例番剧/Season 01"
  },
  "details": {},
  "timestamp": "2026-07-27T00:00:00+00:00"
}
```

自定义请求头使用 JSON 对象，例如：

```json
{"Authorization":"Bearer your-token"}
```

## 订阅健康设置

每个订阅新增两个选项：

- **全部下载完成后自动停用**：需要已知且大于 0 的总集数。只有第 `1..总集数` 的整数集均被 qBittorrent 确认完成时才停用；`.5` 特别集不用于满足整季完成条件。
- **连续未更新告警（天）**：`0` 表示关闭。达到阈值后通知一次；发现新的匹配条目后重置，之后再次达到阈值才会再次通知。

“遗漏检测”会把已推送和等待定时推送的集数视为已跟踪。缺失集合发生变化时才通知；超过 10 集的缺失集合只展示不推送，避免刚创建订阅时把尚未播出的整季当作异常。

## 元数据与规范命名

推荐命名：

```text
/media/
└── 番剧名称 (2026)/
    └── Season 01/
        ├── 番剧名称 - S01E01.mkv
        └── 番剧名称 - S01E01.zh-CN.ass
```

默认目录模板：

```text
{base}/{media_folder}/Season {season:02}
```

默认文件名模板：

```text
{title} - S{season:02}E{episode:02}
```

可用变量包括 `{base}`、`{media_folder}`、`{title}`、`{season}`、`{episode}`、`{year}` 和 `{tmdb_id}`。

## 调度与代理

- RSS 轮询间隔可在网页设置，最小 5 分钟；
- 下载完成状态每 2 分钟检查一次；
- 可把下载任务推迟到每天指定时间统一推送；
- 外部请求代理支持 HTTP、HTTPS、SOCKS5/SOCKS5H 和 `NO_PROXY` 风格排除列表；
- RSS、Mikan、元数据、GitHub 更新检查和通知渠道均使用统一代理策略；qBittorrent 局域网地址建议加入排除列表。

## 重要环境变量

```dotenv
FEEDDOCK_BUILD_VERSION=1.17.12
APP_PORT=7789
ADMIN_USER=admin
ADMIN_PASSWORD=change-this-to-a-strong-password
POLL_INTERVAL_MINUTES=30
REQUEST_TIMEOUT_SECONDS=20
QBIT_URL=http://192.168.1.20:8080
QBIT_USERNAME=admin
QBIT_PASSWORD=
QBIT_CATEGORY=rss
DOWNLOAD_PATH=/media
METADATA_LANGUAGE=zh-CN
TMDB_API_BASE=https://api.themoviedb.org
TMDB_IMAGE_BASE=https://image.tmdb.org
TMDB_READ_ACCESS_TOKEN=
BANGUMI_ACCESS_TOKEN=
MEDIA_LOCAL_ROOT=/media
AUTOMATION_TIME=02:00
AUTOMATION_TIMEZONE=Asia/Shanghai
OUTBOUND_PROXY_URL=
OUTBOUND_NO_PROXY=localhost,127.0.0.1,host.docker.internal
LOG_LEVEL=INFO
FEEDDOCK_ALLOW_SYSTEM_ACTIONS=false
```

通知配置当前保存在网页数据库中，不需要写入 `.env`。`FEEDDOCK_ALLOW_SYSTEM_ACTIONS` 默认为 `false`，仅在明确需要网页重启/关闭服务时开启。

## 数据库升级

启动时会对 SQLite 执行仅新增字段和表的兼容迁移，不删除订阅、条目、RSS 指纹、通知配置或旧缓存。1.17.0 新增：

- `subscriptions.source_type`：订阅来源类型；
- `subscriptions.source_anime_id`：目标站点番剧 ID；
- `subscriptions.canonical_key`：统一番剧身份；
- `anime_preferences`：跨站隐藏偏好。

程序启动时会为旧订阅回填来源和身份。更早版本的增量迁移仍会按顺序执行，无需手工 SQL。
