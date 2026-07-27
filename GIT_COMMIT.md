# FeedDock 1.17.12 Git 提交说明

建议提交：

```text
feat(backup): 增加系统备份与跨站 RSS 恢复

导出和恢复网页有效配置、订阅与番剧隐藏偏好；更新 RSS 按当前番剧身份搜索 Mikan、ANI.BT 和 Anime Garden，并把空源错误改为可操作提示。
```

## 主要改动

- 新增 `app/backup_service.py`：
  - 导出当前有效网页配置，而不只导出 SQLite 中显式保存的值；
  - 默认省略密码、Token、代理和通知私密地址；
  - 支持合并或替换恢复；
  - 不含敏感值的替换备份会保留当前实例已有密钥；
  - 同时迁移订阅和番剧隐藏偏好。
- 订阅导入导出格式升级为 v2，保留独立迁移入口。
- 新增 `app/rss_candidates.py`：
  - 使用当前站点番剧 ID、Bangumi Subject ID 和标题别名；
  - 搜索 Mikan、ANI.BT 与 Anime Garden；
  - 列出匹配番剧下全部可用字幕组 RSS；
  - 支持填入主源、备用源或保存后检查当前订阅。
- `主 RSS 没有条目` 和 `备用 RSS 没有条目` 作为可恢复业务错误处理：
  - INFO 日志不显示内部 JSON、RSS 私密地址和 Python Traceback；
  - DEBUG 日志继续保留完整堆栈。
- 新增系统备份导入弹窗、RSS 候选窗口、文档和回归测试。

## 主要文件

- `app/backup_service.py`
- `app/rss_candidates.py`
- `app/main.py`
- `app/rss_service.py`
- `app/schemas.py`
- `app/static/index.html`
- `app/static/app.js`
- `app/static/styles.css`
- `tests/test_backup_and_rss_candidates.py`
- `SYSTEM_BACKUP_AND_RSS_RECOVERY.md`
- `RSS_QUICK_UPDATE.md`
