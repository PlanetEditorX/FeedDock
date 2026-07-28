# qBittorrent 集成指南

本文合并 FeedDock 的下载推送、任务确认、临时标签、hash 跟踪、下载完成检查和延迟清理说明。

## 安全边界

- FeedDock 通过 qBittorrent Web API 创建和查询任务。
- 延迟清理固定使用 `deleteFiles=false`，只移除 qBittorrent 任务记录，不删除下载文件。
- 日志不会输出完整 Torrent URL、magnet 或私有 RSS passkey。

## 下载推送、任务确认与日志

## 新订阅首次刷新

创建新订阅成功后，API 会把单订阅刷新任务加入 FastAPI `BackgroundTasks`：

```text
保存订阅
  → 提交 SQLite
  → 返回订阅数据
  → 后台刷新刚创建的订阅
  → 解析 RSS
  → 创建 FeedItem
  → 按规则跳过、等待或推送 qBittorrent
```

首次刷新只检查新建的订阅，不会刷新其它订阅。停用状态的新订阅会记录跳过日志，不执行 RSS 请求。

## 手动刷新全部订阅

点击顶部“刷新 → 刷新全部订阅”后，浏览器会直接调用后端运行 `refresh_all()`，不再显示二次确认。日志会记录：

- 开始刷新全部订阅；
- 每条订阅开始检查；
- RSS 加载错误；
- 下载器推送过程；
- 每条订阅检查汇总；
- 全部订阅刷新汇总。

重复点击时，如果已有刷新任务运行，会记录“刷新全部订阅未启动”。

## 下载器推送日志

每个需要下载的 RSS 条目会记录以下阶段：

```text
准备推送到下载器
下载器推送失败，准备重试
qBittorrent 已确认任务
最终未能推送到下载器
下载任务等待并发空位
下载任务等待定时推送
跳过下载器推送
```

日志详细内容包含：

- 订阅 ID；
- 条目 ID；
- 集数；
- RSS 标题；
- 保存目录；
- 临时 qBittorrent 关联标签（确认后自动删除）；
- 规范任务名称；
- 重试次数和下载器返回结果。

为防止泄漏私有 RSS passkey，日志不会输出完整 RSS 下载地址、Torrent URL 或 magnet 链接。

## 日志位置

日志会同时写入：

```text
网页：日志 → 系统日志
文件：/data/logs/feeddock.log
```

网页日志适合快速查看状态；文件日志适合容器排障和长期留存。

## 常见状态

### qBittorrent 已确认任务

FeedDock 已在 qBittorrent 任务列表中按临时标签查到任务，保存实际任务名称、状态和 hash，并立即清理该标签。仅收到添加接口的 `Ok.` 不再视为成功。

### 等待下载并发空位

当前活动下载数达到“同时下载限制”。条目保持 `scheduled`，后台会重新尝试。

### 等待定时推送

启用了“下载任务等待统一时间再推送”。RSS 刷新只发现条目，实际推送在配置的每日时间执行。

### 新增 0，推送 0

通常表示 RSS 条目已经处理过，没有新的指纹。可在下载列表查看历史条目及跳过原因。

### 新增大于 0，但推送 0

检查下载列表中的原因，常见情况包括：

- 未命中包含规则；
- 命中排除规则；
- 只下载最新集导致旧条目跳过；
- 没有 Torrent 或 magnet；
- 等待定时推送；
- 等待下载并发空位；
- 目标视频文件已经存在。

## 临时标签与 hash 跟踪

## 为什么之前会出现大量标签

FeedDock 1.17.3—1.17.7 为每个 RSS 条目创建唯一标签：

```text
feeddock-item-<条目 ID>
```

标签用于在 qBittorrent 接受添加请求后回查真实任务，防止仅收到 `Ok.` 就误报成功。旧实现后续也依赖标签检查下载进度，因此标签会永久保留并持续增加。

## 1.17.8 的处理方式

标签现在只是一把短期关联钥匙：

```text
提交 Torrent/Magnet + 临时标签
  → 按标签确认 qBittorrent 中确实出现任务
  → 保存真实 torrent hash
  → 从任务移除临时标签
  → 删除 qBittorrent 标签定义
  → 后续全部按 hash 查询
```

用户自己的标签、分类和自动管理设置不会被修改。清理器只处理名称以 `feeddock-item-` 开头的标签。

## 历史标签迁移

后台调度器启动后会执行一次清理，之后每小时重试：

1. 读取 qBittorrent 全部标签；
2. 仅筛选 `feeddock-item-*`；
3. 按标签查询对应任务并回填缺失的 torrent hash；
4. 从所有任务移除这些临时标签；
5. 删除空标签定义；
6. 清空 FeedDock 数据库中的临时标签字段。

日志中会出现：

```text
qBittorrent 临时标签清理完成
```

并显示清理的标签数、更新的数据库条目数和补全的任务 hash 数。

## 失败策略

临时标签清理失败不会把已经确认的下载任务标记为失败。FeedDock 会保存真实 hash，并在后台下次维护时继续尝试清理。

如果 qBittorrent 版本不支持标签管理 API，下载仍可继续，但旧标签可能需要在 qBittorrent 中手动删除。

## 推送确认边界

## 推送成功的判断

`/api/v2/torrents/add` 返回 HTTP 200 或 `Ok.` 只代表 qBittorrent 接受请求。FeedDock 会为本次请求增加一个临时 `feeddock-item-*` 标签，再通过任务列表回查真实任务。

只有查到任务名称、状态和 torrent hash 后，条目才进入 `queued`。

## 临时标签生命周期

```text
添加请求
  → 临时标签回查
  → 保存 torrent hash
  → removeTags 从任务移除标签
  → deleteTags 删除标签定义
```

后续重命名、下载完成检查、Tracker 和刮削均使用 hash，不再依赖永久标签。历史标签由后台维护自动清理，详见本文“临时标签与 hash 跟踪”章节。

## HTTP/HTTPS Torrent

FeedDock 使用当前代理设置下载 `.torrent`，校验内容后上传原始字节到 qBittorrent。这样 qBittorrent 不需要自行访问私有 Torrent URL，也不会因为 DNS、代理、证书或 Passkey 问题产生假成功。

## 失败处理

添加接口返回成功但回查不到任务时，条目进入 `error`，下载列表显示“重试下载”。临时标签清理失败不会否定已经确认的任务，会在后台继续重试。

## 日志隐私

日志记录条目 ID、临时关联标识、实际任务名称、状态和 hash，不输出完整 magnet、Torrent URL 或私有站点 Passkey。

## 下载完成记录延迟清理

## 功能

下载设置新增：

- “下载完成后自动删除 qBittorrent 任务记录”开关，默认关闭；
- “完成后等待（分钟）”，默认 1 分钟；
- “检查到期清理”手动检查按钮。

后台约每 30 秒检查一次。等待时间优先从 qBittorrent 的 `completion_on` 实际完成时间计算；旧版本或缺失该字段时，使用 FeedDock 首次确认完成的时间。

## 文件安全

清理请求固定为：

```text
POST api/v2/torrents/delete
hashes=<torrent hash>
deleteFiles=false
```

因此只删除 qBittorrent WebUI 中的任务记录，不删除下载文件。FeedDock 保留任务哈希和清理时间用于审计，并记录“下载文件已保留”。

## 后处理保护

以下状态不会自动删除 qBittorrent 记录：

- 下载命名尚未完成；
- 本地 NFO/图片刮削正在等待、重试或失败；
- Tracker 添加失败。

处理恢复正常后，下一次到期检查会继续清理。

## 数据库升级

SQLite 启动时自动增加：

- `feed_items.qbit_record_removed_at`；
- `feed_items.qbit_record_remove_message`。

无需手工执行迁移。

## 验证

- Python：181 项通过；
- Node.js：`app/static/app.js` 语法检查通过；
- 覆盖设置持久化、等待时间、后处理阻塞、qBittorrent 删除参数和实际完成时间。
