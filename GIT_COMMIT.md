# FeedDock 1.15.0 Git 提交说明

## 推荐提交标题

```text
feat(subscriptions): 增加 Mikan、ANI.BT 与 Anime Garden 站点入口
```

## 提交正文

```text
- 将添加订阅拆分为 Mikan、ANI.BT、Anime Garden 和其它 RSS
- 为 ANI.BT 与 Anime Garden 显示官方地址、RSS 文档和安全提示
- 全站 RSS 仅在用户确认后填入，避免误处理大量资源
- 新增后端订阅站点目录与 URL 来源识别模块
- 订阅 API 返回稳定的 source_type 和 source_label
- 自动从 Mikan/AniBT URL 提取 bangumiId 或 bgmId
- 使用严格主机边界匹配，避免相似恶意域名伪装
- 新增独立前端 subscription-sources 模块
- 增加站点目录、来源检测、UI 结构和自动 ID 测试
- 版本升级至 1.15.0
```

## 主要文件

```text
app/subscription_sources.py
app/static/subscription-sources.js
app/static/app.js
app/static/index.html
app/static/styles.css
app/main.py
app/schemas.py
tests/test_subscription_sources.py
tests/test_deployment_files.py
SUBSCRIPTION_SOURCES.md
README.md
UI_NAVIGATION.md
```

## 数据库

本次不增加数据库字段，不需要手工迁移。`source_type` 与 `source_label` 根据现有 `rss_url` 动态生成。

## 提交命令

```bash
git add .
git commit -m "feat(subscriptions): 增加 Mikan、ANI.BT 与 Anime Garden 站点入口" \
  -m "为不同订阅站点提供专用入口、官方 RSS 指引、安全提示和稳定来源识别。"
```
