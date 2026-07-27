# FeedDock 1.17.8 qBittorrent 临时标签

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
