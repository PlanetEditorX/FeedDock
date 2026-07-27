# FeedDock 1.17.0 验证报告

## 范围

本次验证覆盖：

- ANI.BT 原站季度目录与字幕组 API 适配；
- Anime Garden 原站活跃番剧与资源 API 适配；
- Mikan 现有原站目录兼容；
- 目录和详情的站点独立缓存；
- Bangumi ID、原站 ID 和标题别名身份匹配；
- 跨站订阅来源徽标；
- 跨站隐藏与取消隐藏；
- 旧版 Mikan 星期隐藏兼容；
- 1.16.1 SQLite 数据库增量升级；
- 静态资源、Compose 和 GitHub Actions 配置。

## 自动化测试

执行：

```bash
PYTHONPATH=. pytest -q
```

结果：

```text
134 passed, 15 subtests passed
```

核心覆盖：

- ANI.BT 请求 `https://anibt.net/api/seasons/anime`；
- ANI.BT 请求 `https://anibt.net/api/anime/groups`；
- Anime Garden 请求 `https://api.animes.garden/subjects`；
- Anime Garden 请求 `https://api.animes.garden/resources`；
- ANI.BT 和 Anime Garden 缓存键互不复用；
- 更新失败只使用当前站点旧缓存；
- 没有当前站点缓存时错误不会被其它站点数据掩盖；
- Mikan 订阅可在 ANI.BT 列表显示 `Mikan 已订阅`；
- 当前站和其它站都已订阅时显示组合徽标；
- 相同站点 ID 在标题变化后仍可识别；
- 隐藏偏好可以通过另一站点的 Bangumi/标题身份取消；
- 订阅保存后前端即时重算跨站来源徽标；
- 添加订阅菜单只包含 Mikan、ANI.BT、Anime Garden 和其它 RSS。

## 静态检查

全部通过：

```text
python -m compileall -q app tests
node --check app/static/app.js
node --check app/static/change-password.js
node --check app/static/login.js
node --check app/static/mikan-subscription-state.js
node --check app/static/navigation.js
node --check app/static/subscription-sources.js
```

YAML 解析通过：

```text
docker-compose.yml
docker-compose.fnos.yml
.github/workflows/docker-publish.yml
```

页面结构：

```text
124 个 HTML id
0 个重复 id
```

应用导入与版本：

```text
FeedDock 1.17.0
```

## 旧数据库迁移

使用原始 1.16.1 代码创建 SQLite 数据库和一条 ANI.BT 订阅，再由 1.17.0 执行：

```text
Base.metadata.create_all
ensure_schema
backfill_subscription_identities
```

验证结果：

```text
source_type      = anibt
source_anime_id  = 543360
bangumi_id       = 543360
canonical_key    = bgm:543360
anime_preferences 表可正常写入
```

历史订阅名称、RSS URL 和启用状态保持不变。

## 网络测试边界

自动化测试使用与 ani-rss 源码字段一致的模拟原站响应，验证请求地址、参数和响应转换。当前沙箱没有用于验证用户 Docker 网络路由的可靠外网环境，因此没有把真实 ANI.BT、Anime Garden 或 Mikan 请求作为通过条件。

部署后如遇原站 DNS 或连接错误：

- 当前站点有缓存：继续显示该站点旧缓存和刷新错误；
- 当前站点没有缓存：明确返回错误；
- 不会再显示 Mikan 或公共周历数据冒充目标站点。

当前环境没有 Docker CLI，因此没有实际构建镜像。
