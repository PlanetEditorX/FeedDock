# FeedDock 1.17.2 Git 提交说明

## 推荐提交

```text
fix(rss): 新订阅自动刷新并记录下载器推送日志
```

## 提交正文

```text
- 新增订阅保存后自动检查该订阅一次
- 刷新全部订阅前增加确认弹窗
- 记录刷新开始、逐订阅检查和最终汇总
- 记录下载器准备、重试、成功、失败与等待状态
- 同时写入网页系统日志和文件日志
- 避免在日志中输出完整 RSS、Torrent 或 magnet 地址
- 移除日志页的 500 请求编号提示
- 版本更新为 1.17.2
```

## 主要文件

```text
app/main.py
app/rss_service.py
app/static/app.js
tests/test_auth_flow.py
tests/test_deployment_files.py
tests/test_rss_service.py
tests/test_settings_features.py
DOWNLOAD_REFRESH_LOGGING.md
```

## 数据库

本次不增加数据库字段，不需要执行手工迁移。
