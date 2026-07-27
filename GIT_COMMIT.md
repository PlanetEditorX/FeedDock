# FeedDock 1.17.8 Git 提交说明

## 推荐提交

```text
fix(qbittorrent): 清理临时 item 标签并改用 hash 跟踪
```

## 提交正文

```text
- 将 feeddock-item-* 改为仅用于添加确认的临时标签
- 确认任务并保存 torrent hash 后立即移除和删除标签
- 下载进度、重命名、Tracker、完成检测和刮削改为优先按 hash 查询
- 后台批量清理历史 FeedDock 标签并回填缺失 hash
- 仅处理 feeddock-item- 前缀，不修改用户自建标签
- 增加标签清理、hash 跟踪和升级兼容测试
```

## 主要文件

```text
app/downloader.py
app/postprocess.py
app/rss_service.py
app/scheduler.py
tests/test_metadata_naming.py
tests/test_settings_features.py
tests/test_deployment_files.py
QBITTORRENT_TEMPORARY_TAGS.md
QBITTORRENT_PUSH_VERIFICATION.md
```

## 数据库

不增加表或字段。清理历史标签时，如果 FeedDock 条目缺少 `torrent_hash`，会从 qBittorrent 当前任务列表回填；成功清理后将数据库中的 `qbit_tag` 置空。
