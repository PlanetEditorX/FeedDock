# FeedDock

当前版本：`1.13.0`

FeedDock 是一个面向自托管/NAS 环境的 RSS 番剧订阅管理器。它负责发现番剧、解析集数、执行匹配规则、生成规范目录与文件名，并把任务推送到 qBittorrent。媒体文件识别和刮削交由飞牛影视、Emby、Jellyfin 等外部媒体库完成。

## v1.13.0：订阅优先的任务式控制台

本版本参考 ani-rss 的任务导航思路，将 FeedDock 首页重构为订阅列表，并按使用频率和风险重新组织右上角操作：

- 首页只展示订阅统计、搜索、状态筛选和订阅卡片；
- 顶部依次提供“添加、下载、刷新、管理、设置、日志”；
- “添加”支持 Mikan、ANI.BT、Anime Garden、其它 RSS 和批量合集；
- 下载条目、各类设置和日志进入独立视图，刷新页面后仍保留当前 Hash 路由；
- 管理视图支持批量启动、禁用、删除，以及 JSON 导入和导出；
- 登录密码不再仅限首次登录时修改，可随时从登录设置进入；
- 系统重启和关闭默认禁用，必须通过环境变量显式开启；
- 本次没有新增数据库字段，从 1.12.0 升级无需迁移。

界面结构、排序依据、导入格式和安全边界见 [`UI_NAVIGATION.md`](UI_NAVIGATION.md)。

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

- Mikan 季度番剧目录、标题搜索、持久缓存和本地 WebP 封面；
- 目录中标记 `✓ 已订阅`，保存、编辑、删除订阅后即时同步；
- 主 RSS 与备用 RSS；
- 包含、排除、全局排除规则；
- 自定义集数正则、捕获组和集数偏移；
- 总集数、总集数锁定、只下载最新集和遗漏检测；
- TMDB、Bangumi、AniList 元数据搜索和人工确认。

### 下载与命名

- 推送 qBittorrent；
- 自定义下载根目录、媒体目录模板和文件名模板；
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
Mikan / RSS
    ↓
标题、规则和集数解析
    ↓
写入条目并生成保存路径 / 目标文件名
    ↓
即时或定时推送 qBittorrent（唯一 Tag）
    ↓
每 2 分钟检查任务元数据、进度和完成状态
    ↓
可选：发送完成通知、判断整季完成并自动停用
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
```

`DOWNLOAD_PATH` 必须是 qBittorrent 能识别的路径。Docker 部署时，FeedDock 和 qBittorrent 应把同一个宿主机目录挂载到相同容器路径，推荐统一为 `/media`。

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
└── 番剧名称 (2026) [tmdbid=123456]/
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
FEEDDOCK_BUILD_VERSION=1.13.0
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

启动时会对 SQLite 执行仅新增字段的兼容迁移，不删除订阅、条目或历史指纹。v1.12.0 新增：

- `auto_disable_when_complete`；
- `stale_days`；
- `last_new_item_at`；
- `last_stale_notified_at`；
- `completion_notified_at`；
- `last_missing_signature`。

网页通知配置保存在 `app_settings` 表。升级不需要手工 SQL。v1.13.0 不增加数据库字段，只新增导航、批量管理和订阅导入导出能力。

## 安全说明

- 密码、Token、Device Key、Webhook 地址和请求头默认不回传；
- DEBUG 日志对密码、Token、API Key、Authorization、Cookie 和 Webhook 配置做脱敏；
- Webhook 可向任意配置地址发送订阅和条目元数据，请只使用可信 HTTPS 服务；
- 通知发送失败只记录日志，不会改变下载任务结果。

## 开发与验证

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m compileall -q app
node --check app/static/app.js
node --check app/static/mikan-subscription-state.js
node --check app/static/navigation.js
```

完整验证结果见 [`VALIDATION.md`](VALIDATION.md)。

## 相关文档

- [`UI_NAVIGATION.md`](UI_NAVIGATION.md)：订阅优先界面、菜单排序、批量管理与导入导出；
- [`ANI_RSS_GAP_ANALYSIS.md`](ANI_RSS_GAP_ANALYSIS.md)：上游功能差异、优先级和未采纳项；
- [`NOTIFICATIONS_AND_MONITORING.md`](NOTIFICATIONS_AND_MONITORING.md)：通知、去重、完结与长期未更新规则；
- [`MIKAN_SUBSCRIPTION_STATUS.md`](MIKAN_SUBSCRIPTION_STATUS.md)：Mikan 已订阅标识模块；
- [`METADATA_NAMING.md`](METADATA_NAMING.md)：元数据与命名规则；
- [`FNOS_DEPLOY.md`](FNOS_DEPLOY.md)：飞牛 OS 部署；
- [`DEBUG_LOGGING.md`](DEBUG_LOGGING.md)：DEBUG 日志使用方法。

## License

项目许可证见 [`LICENSE`](LICENSE)。请只处理你有权访问的 RSS 与媒体文件。
