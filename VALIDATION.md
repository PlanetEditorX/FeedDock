# FeedDock 1.17.8 验证报告

## 功能验证

- 新任务仍使用唯一 `feeddock-item-*` 临时标签确认 qBittorrent 是否真正建立任务；
- 确认真实 torrent hash 后调用 `torrents/removeTags` 从任务移除标签；
- 随后调用 `torrents/deleteTags` 删除 qBittorrent 标签定义；
- 成功清理后 FeedDock 数据库中的 `qbit_tag` 置空；
- 下载进度、文件重命名、Tracker、完成检测和本地媒体刮削均可仅依赖 `torrent_hash`；
- 临时标签清理失败不会把已确认的下载任务标记为失败；
- 后台每小时重试清理历史 `feeddock-item-*` 标签；
- 历史清理只读取一次 qBittorrent 任务列表，再批量解析标签与 hash；
- 历史 FeedDock 条目缺少 hash 时可在删除标签前自动回填；
- 孤立的旧 FeedDock 标签也会被删除；
- 用户自建标签、分类和非 `feeddock-item-` 标签保持不变。

## 自动化与静态验证

- 158 项自动化测试通过；
- Python 全项目编译通过；
- 6 个 JavaScript 文件语法检查通过；
- Docker Compose、飞牛 Compose 和 GitHub Actions YAML 解析通过；
- 页面 128 个 HTML ID 唯一；
- FastAPI 配置运行版本 `1.17.8` 检查通过；
- Git diff 空白与冲突标记检查通过。

## 数据库兼容

本次不增加表或字段，不需要手工迁移。升级后后台维护会更新已有 `feed_items`：

```text
qbit_tag      → 成功清理后置空
torrent_hash  → 若为空且能从 qBittorrent 识别，则自动回填
```

订阅、RSS 指纹、下载状态、完成状态和刮削状态不会被删除。

## 环境限制

当前环境没有连接真实 qBittorrent 实例。WebAPI 登录、添加、按标签确认、按 hash 查询、`removeTags`、`deleteTags`、历史标签批量清理和失败回退通过模拟 qBittorrent 响应验证。
