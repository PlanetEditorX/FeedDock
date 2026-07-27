# FeedDock 1.14.0 Git 提交说明

## 推荐提交标题

```text
feat(settings): 增加下载、RSS、刮削与 Tracker 策略
```

## 推荐提交正文

```text
- 新增五种主题色和评分、拼音、更新时间订阅排序
- 持久化元数据评分并在订阅卡片展示
- 新增全局自动元数据同步、追更天数和 bangumi.ini
- 支持自定义 TMDB API/图片地址及 v3 API Key、v4 Token
- 新增 qBittorrent 推送重试、并发限制和做种时长
- 新增 RSS 总开关、超时和已下载文件自动跳过
- 根据 Bangumi 总集数自动判断整季完成并停用订阅
- 新增 Tracker 更新、去重缓存和任务哈希可用后的追加
- 强制校验自动跳过与自动重命名、统一路径的依赖关系
- 增加 SQLite 增量迁移、设置文档和自动化测试
- 版本升级至 1.14.0
```

## 建议分拆提交

```text
feat(settings): 增加页面与元数据设置
feat(download): 增加重试、并发、做种时长和文件跳过
feat(rss): 增加总开关与 Bangumi 完结自动停用
feat(trackers): 增加 Tracker 缓存和 qBittorrent 追加
feat(sidecar): 增加安全的 bangumi.ini 生成
test(docs): 补齐迁移、设置和执行链路验证
```

## 主要文件

```text
app/settings_config.py
app/media_sidecar.py
app/runtime_config.py
app/metadata_service.py
app/downloader.py
app/rss_service.py
app/postprocess.py
app/subscription_monitor.py
app/main.py
app/models.py
app/database.py
app/schemas.py
app/static/index.html
app/static/app.js
app/static/styles.css
app/static/navigation.js
tests/test_settings_features.py
tests/test_subscription_management.py
tests/test_deployment_files.py
SETTINGS_REFERENCE.md
README.md
FNOS_DEPLOY.md
VALIDATION.md
```

## 提交命令

```bash
git add \
  VERSION Dockerfile docker-compose.yml docker-compose.fnos.yml \
  .env.example .env.fnos.example \
  app tests \
  README.md UI_NAVIGATION.md FNOS_DEPLOY.md \
  SETTINGS_REFERENCE.md VALIDATION.md GIT_COMMIT.md

git commit -m "feat(settings): 增加下载、RSS、刮削与 Tracker 策略" \
  -m "补齐主题排序、自动元数据、bangumi.ini、下载重试并发做种、RSS 自动跳过与完结停用，以及 Tracker 缓存追加。"
```

## 升级影响

- 1.13.0 数据库会自动新增 5 个兼容字段，不需要手工 SQL；
- 网页设置保存在现有 `app_settings` 表；
- 开启文件自动跳过后，所有启用订阅必须开启自动重命名；
- TMDB 密钥字段兼容 v3 API Key 和 v4 Read Access Token；
- Tracker 更换更新地址后，需要手动执行一次“立即更新”；
- 开启 `bangumi.ini` 会为符合条件的历史完成任务安排一次补写；
- 静态资源版本升级为 `v=1.14.0`，升级后建议强制刷新浏览器。
