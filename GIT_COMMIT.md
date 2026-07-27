# FeedDock 1.12.0 Git 提交说明

## 推荐提交标题

```text
feat(monitoring): 增加通知中心与订阅健康监控
```

## 推荐提交正文

```text
- 新增 Telegram、Bark 和通用 JSON Webhook 通知渠道
- 支持开始下载、下载完成、遗漏、完结、RSS 错误和长期未更新事件
- 新增订阅完结自动停用与长期未更新阈值
- 为遗漏、完结和停更通知增加数据库持久化去重
- 所有 qBittorrent 任务写入唯一 Tag，关闭规范命名时仍可检测完成
- 对通知密钥、Webhook 地址和请求头进行遮蔽与错误脱敏
- 使用 SQLite 增量迁移兼容旧数据库
- 新增通知、订阅监控、安全脱敏和部署回归测试
- 更新 README、飞牛部署、功能差异和验证文档
- 版本升级至 1.12.0
```

## 建议分拆提交

希望保持 Git 历史更清晰时，可拆为三个提交：

```text
feat(notifications): 增加 Telegram、Bark 与 Webhook 通知中心
feat(subscriptions): 增加完结停用、遗漏去重和停更监控
test(docs): 补齐迁移回归测试与使用说明
```

## 主要文件

```text
app/notification_config.py
app/notifications.py
app/subscription_monitor.py
app/rss_service.py
app/postprocess.py
app/main.py
app/models.py
app/database.py
app/schemas.py
app/static/index.html
app/static/app.js
tests/test_notifications.py
tests/test_subscription_monitor.py
tests/test_debug_logging.py
tests/test_deployment_files.py
ANI_RSS_GAP_ANALYSIS.md
NOTIFICATIONS_AND_MONITORING.md
README.md
VALIDATION.md
```

## 提交命令

```bash
git add \
  VERSION Dockerfile docker-compose.yml .env.example \
  app tests README.md ANI_RSS_GAP_ANALYSIS.md \
  NOTIFICATIONS_AND_MONITORING.md FNOS_DEPLOY.md VALIDATION.md GIT_COMMIT.md

git commit -m "feat(monitoring): 增加通知中心与订阅健康监控" \
  -m "补齐多渠道事件通知、下载完成跟踪、完结自动停用、遗漏去重和长期未更新检测，并保持旧 SQLite 数据兼容。"
```

## 升级影响

- 无需手工执行 SQL；启动时自动增加六个订阅监控字段。
- 不删除订阅、历史条目或指纹。
- 通知默认关闭，升级后不会自动向外发送数据。
- 完结自动停用和长期未更新检测均为订阅级显式开关。
