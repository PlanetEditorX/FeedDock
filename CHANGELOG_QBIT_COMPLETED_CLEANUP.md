# qBittorrent 下载完成记录延迟清理

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
