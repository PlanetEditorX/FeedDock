# ani-rss 深度对比与 FeedDock 功能补齐

分析日期：2026-07-27
FeedDock 目标版本：1.12.0
参考项目：`wushuo894/ani-rss`（分析时最新版本 v3.2.2）

## 1. 分析范围

本次不是把 ani-rss 原样移植到 FeedDock，而是从以下维度分析：

1. 订阅生命周期；
2. RSS 拉取、主备源和集数状态；
3. 下载器适配与下载完成判断；
4. 通知事件和通知渠道；
5. 自动停用、遗漏和长期未更新监控；
6. 元数据、命名、刮削和洗版；
7. 前后端模块边界、持久化和测试策略。

主要参考：

- https://github.com/wushuo894/ani-rss
- https://docs.wushuo.top/config/notification
- https://docs.wushuo.top/config/basic/rss
- https://docs.wushuo.top/config/download

## 2. 架构差异

| 项目 | ani-rss | FeedDock |
|---|---|---|
| 后端 | Java 17、Spring Boot，多 Maven 模块 | Python、FastAPI、SQLAlchemy |
| 前端 | 独立 Vue/Vite UI 模块 | 原生 HTML/CSS/JavaScript |
| 下载器 | qBittorrent、Transmission、Aria2、OpenList | qBittorrent |
| 主要定位 | 全链路追番、刮削、洗版、上传 | 轻量 RSS 管理、Mikan 发现、规范命名 |
| 数据迁移 | Java 应用内部升级逻辑 | SQLite 启动时增量 `ALTER TABLE` |
| 媒体处理 | 包含刮削、移动、洗版等高权限操作 | 明确交给外部媒体库，避免直接移动做种文件 |

因此不能直接复制 ani-rss 的 Controller、Service、Vue 页面或下载器实现。FeedDock 需要保留轻量部署、单数据库、可审计和低破坏性的特征。

许可证也要求保持实现边界清晰：ani-rss 仓库标注为 GPL-2.0，FeedDock 当前为 MIT。本次只参考公开功能行为和文档重新设计接口、数据模型与测试，没有复制 ani-rss 源码、页面或资源文件。

## 3. 已有能力对比

FeedDock 在本次改动前已经具备：

| 能力 | FeedDock 状态 |
|---|---|
| RSS 自动轮询 | 已有，可网页调整间隔 |
| 主 RSS / 备用 RSS | 已有，主源失败或空时使用备用源 |
| 匹配、排除、全局排除 | 已有 |
| 自定义集数规则和偏移 | 已有 |
| 总集数与锁定 | 已有 |
| 只下载最新集 | 已有 |
| 遗漏集数计算 | 已有，但没有事件通知和持久去重 |
| Mikan 目录与订阅标识 | 已有 |
| qBittorrent 推送 | 已有 |
| 下载后规范命名 | 已有 |
| 下载完成轮询 | 已有，但过去仅对启用规范命名的任务可靠 |
| TMDB/Bangumi/AniList | 已有 |
| 统一执行时间与代理 | 已有 |

## 4. 发现的主要缺口

### P0：本次已实现

#### 4.1 事件通知中心

ani-rss 把开始下载、下载完成、缺集、错误、订阅完结和“摸鱼检测”作为明确事件，并支持多种通知方式。FeedDock 原先只有网页日志，无法主动提醒。

FeedDock 1.12.0 新增：

- Telegram；
- Bark；
- 通用 JSON Webhook；
- 六种事件独立开关；
- 密钥遮蔽、单独清除、受保护的主动读取；
- 渠道失败隔离、凭据脱敏和 WARNING 日志。

没有照搬复杂模板语言。首版采用稳定的结构化事件数据，Webhook 接收方可自行格式化，Telegram/Bark 使用可读文本。

#### 4.2 下载完成与规范命名解耦

旧 FeedDock 仅在生成 `desired_name` 时写入 qBittorrent Tag。关闭规范命名的任务无法进入完成检查队列，从而无法可靠触发完成通知或完结判断。

现在每个任务都分配 `feeddock-item-{id}` 唯一 Tag。`desired_name` 为空时只读取任务和文件状态，不执行重命名。

#### 4.3 完结自动停用

新增订阅级开关 `auto_disable_when_complete`：

- 必须存在明确的 `total_episodes`；
- 第 `1..total_episodes` 集都必须被 qBittorrent 确认完成；
- `.5` 等非整数特别集不参与满足整季条件；
- 满足后关闭 `enabled`；
- 使用 `completion_notified_at` 去重；
- 发送“订阅完结”通知；总集数或监控开关变更时正确失效旧去重状态。

与基于本地文件扫描的方案相比，这种实现不会误删、移动或扫描用户媒体库，但只能识别由 FeedDock 推送且仍可通过 qBittorrent Tag 找到的任务。

#### 4.4 长期未更新检测

新增 `stale_days`：

- `0` 关闭；
- 以最近一次发现“新的、匹配规则的 RSS 条目”为活跃时间；
- 达到阈值通知一次；
- 新条目出现时清空通知状态；
- 状态持久化，重启不会重复提醒；旧数据库没有活跃时间时使用最近检查时间作为升级兼容基准。

#### 4.5 遗漏通知去重

原有遗漏列表升级为事件：

- 已推送和等待定时推送都视为已跟踪；
- 缺失集合变化时才通知；
- 缺失超过 10 集时只展示不通知，降低新建订阅和总集数配置错误造成的噪声；
- 签名保存在订阅表中，重启后继续去重。

## 5. 暂未实现的功能及原因

### P1：建议后续实现

#### 5.1 下载器抽象层

ani-rss 支持 qBittorrent、Transmission、Aria2 和 OpenList。FeedDock 当前下载、Tag、文件列表和内部重命名逻辑与 qBittorrent API 紧密耦合。

正确的后续方式不是在现有类中增加大量 `if downloader == ...`，而是定义：

```text
DownloaderAdapter
├── test_connection
├── add_task
├── inspect_task
├── rename_files
└── completion_capabilities
```

再按能力降级。Transmission、Aria2 和 OpenList 并不提供完全相同的 Tag、文件重命名和完成状态语义，必须在 UI 中明确能力矩阵。

#### 5.2 本地文件自动跳过

ani-rss 可扫描季度目录判断某集是否已存在。FeedDock 目前不主动遍历媒体库，这是降低权限和避免路径误判的设计选择。

后续若实现，应满足：

- 显式启用；
- 限制在规范化媒体目录内部；
- 只读扫描；
- 支持预览将被跳过的文件；
- 处理多版本、特别篇、`.5` 集和媒体库软链接；
- 不因文件名误判而删除历史条目。

#### 5.3 更多通知渠道

可按现有 `send_notification` 渠道适配结构增加：

- SMTP 邮件；
- Server酱；
- Gotify / ntfy；
- 企业微信 / 飞书；
- Emby/Jellyfin 媒体库刷新。

需要先决定是否引入异步发送队列、重试次数和通知发送历史表。

### P2：高风险或不符合当前定位

#### 5.4 主备源自动洗版

ani-rss 的备用源可先下载，主源出现后覆盖或删除旧版本。该能力涉及文件身份、字幕组优先级、下载器做种状态和物理文件删除。

FeedDock 当前明确不直接移动或删除做种文件。贸然加入洗版会引入较高的数据损失风险，因此本次不实现。后续必须先具备：

- 下载版本模型；
- 源优先级；
- 文件哈希和媒体路径核验；
- dry-run 预览；
- 回收站而不是直接删除；
- 做种和硬链接检测。

#### 5.5 内置刮削、自动上传和文件移动

FeedDock 已选择“规范命名 + 外部媒体库识别”的边界。恢复 NFO、图片、OpenList 上传或下载完成后移动，会增加媒体库写权限、失败恢复和多平台路径映射复杂度，不适合作为本次补齐目标。

#### 5.6 Trackers 自动追加

这属于下载性能优化而非订阅生命周期。错误或不可信 Tracker 可能带来隐私、可用性和维护问题，建议由 qBittorrent 自身规则或专门工具管理。

## 6. 新模块边界

```text
app/notification_config.py
  └── 通知设置加载、验证、保存、重置和公开字段

app/notifications.py
  └── 事件负载、Telegram/Bark/Webhook 发送和错误隔离

app/subscription_monitor.py
  ├── 已跟踪/已完成集数集合
  ├── 遗漏计算与通知去重
  ├── 新 RSS 活跃时间记录
  ├── 长期未更新检测
  └── 完结自动停用

app/rss_service.py
  └── 只负责在 RSS 生命周期中的正确时点触发监控事件

app/postprocess.py
  └── 只负责 qBittorrent 完成状态，并在状态首次变为完成时触发事件
```

这样通知渠道与 RSS 解析、监控规则与下载器 API 不互相嵌套，便于独立测试和后续扩展。

## 7. 持久化设计

订阅表新增：

| 字段 | 用途 |
|---|---|
| `auto_disable_when_complete` | 完结自动停用开关 |
| `stale_days` | 长期未更新阈值 |
| `last_new_item_at` | 最近匹配到新条目的时间 |
| `last_stale_notified_at` | 长期未更新通知去重 |
| `completion_notified_at` | 完结通知去重 |
| `last_missing_signature` | 遗漏集合去重 |

通知渠道存入 `app_settings`，不新增独立表。升级使用仅新增字段的 SQLite 迁移，不改变旧数据。

## 8. 安全与可靠性取舍

- 不在普通设置 API 返回密钥原文；
- DEBUG 脱敏规则覆盖 Webhook；
- 外部通知使用现有统一代理与超时；
- 一个渠道失败不会阻断其他渠道；
- 通知整体失败不会回滚下载状态；
- 不启动额外消息队列，保持单容器部署；
- 事件去重状态与业务事务一起提交。

## 9. 测试覆盖

新增测试覆盖：

- 通知配置的密钥遮蔽；
- Telegram、Bark、Webhook 三渠道分发；
- 未勾选事件不访问网络；
- 不完整渠道、空事件集合和非法请求头验证；
- 遗漏集合及去重；
- 大范围遗漏静默；
- 整季完成与一次性通知；
- `.5` 集不满足整季完成；
- 长期未更新的去重与活动重置；
- Telegram Token、Bark Key、Webhook 地址与请求头在错误响应和日志中脱敏；
- 历史完成任务在普通 RSS 检查时补做完结判断；
- 旧版 SQLite 结构增量升级。

## 10. 结论

本次没有追求功能数量最大化，而是补齐了 FeedDock 最缺少的“主动可观测性”和“订阅生命周期闭环”：任务开始、完成、异常、遗漏、停更和完结都能被识别并主动通知。实现保持了 FeedDock 的轻量架构和低破坏性边界，同时为后续下载器适配、更多通知渠道和安全的本地文件扫描提供了清晰模块接口。
