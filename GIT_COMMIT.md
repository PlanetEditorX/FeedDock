# FeedDock 1.17.0 Git 提交说明

## 推荐提交标题

```text
feat(discovery): 使用原站目录并支持跨站订阅状态
```

## 提交正文

```text
- ANI.BT 直接读取原站季度周历和字幕组 API
- Anime Garden 直接读取原站活跃番剧和资源 API
- 移除非 Mikan 目录对 bangumi-data/CDN/Mikan 回退的依赖
- 目录与详情缓存按站点隔离，失败时仅回退当前站点旧缓存
- 为订阅增加 source_type、source_anime_id 和 canonical_key
- 使用 Bangumi ID、站点 ID 和标题别名关联跨站番剧
- 显示“已订阅”“Mikan 已订阅”等来源徽标
- 增加跨站隐藏偏好并兼容旧版 Mikan 星期过滤
- 从添加订阅菜单移除没有原生周历的 Nyaa 和 SubsPlease
- 增加原站适配器、缓存、身份和隐藏状态测试
```

## 主要文件

```text
app/catalog_providers.py
app/anime_catalog.py
app/anime_identity.py
app/main.py
app/models.py
app/schemas.py
app/static/app.js
app/static/index.html
app/subscription_sources.py
tests/test_catalog_weekly_sources.py
```

## 提交命令

```bash
git add -A
git commit -m "feat(discovery): 使用原站目录并支持跨站订阅状态" \
  -m "ANI.BT 与 Anime Garden 改为直接请求原站，增加独立缓存、跨站订阅徽标和统一隐藏偏好。"
```

## 数据库

升级自动增加三个订阅身份字段和 `anime_preferences` 表，无需手工 SQL。
