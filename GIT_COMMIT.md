# FeedDock 1.16.0 Git 提交说明

## 推荐提交标题

```text
feat(discovery): 增加多站点番剧周历与资源缓存
```

## 提交正文

```text
- 让 Mikan、ANI.BT、Anime Garden、Nyaa 和 SubsPlease 共用按星期选番入口
- ANI.BT、Anime Garden、Nyaa 和 SubsPlease 使用共享 bangumi-data 周历
- 所有站点支持标题搜索、读取缓存和手动强制更新
- 根据站点能力生成 Bangumi ID、标题过滤、分类搜索或分辨率 RSS
- 缓存每个 RSS 预设的最近资源，并支持强制更新资源详情
- 已订阅状态在当前站点周历中即时同步
- 已浏览共享季度按现有缓存周期后台刷新
- 共享周历与资源请求遵循 FeedDock 代理设置
- 增加周历解析、RSS 生成、缓存回退和后台刷新测试
- 版本升级至 1.16.0
```

## 主要文件

```text
app/anime_catalog.py
app/subscription_sources.py
app/main.py
app/scheduler.py
app/static/app.js
app/static/index.html
app/static/navigation.js
app/static/styles.css
tests/test_catalog_weekly_sources.py
tests/test_subscription_sources.py
tests/test_deployment_files.py
MULTI_SOURCE_WEEKLY_CATALOG.md
SUBSCRIPTION_SOURCES.md
README.md
UI_NAVIGATION.md
```

## 数据库

不新增表或字段。共享周历和资源详情复用现有 `mikan_cache_entries` 表。

## 提交命令

```bash
git add .
git commit -m "feat(discovery): 增加多站点番剧周历与资源缓存" \
  -m "统一 Mikan、ANI.BT、Anime Garden、Nyaa 和 SubsPlease 的按星期选番、缓存和站点 RSS 生成流程。"
```
