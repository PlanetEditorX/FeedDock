# FeedDock 1.16.1 Git 提交说明

## 推荐提交标题

```text
fix(discovery): 为多站点周历增加 DNS 回退
```

## 提交正文

```text
- 将 bangumi-data 周历从单一 GitHub Raw 地址改为多镜像顺序回退
- 默认尝试 jsDelivr CDN、Fastly 节点和 GitHub Raw
- DNS 解析失败后在当前刷新周期熔断对应镜像，避免每个月重复超时
- 所有周历镜像失败时复用 Mikan 季度目录和持久化缓存
- ANI.BT 回退模式使用官方兼容的 Mikan bangumiId 参数
- 前端显示周历回退状态，并向资源详情传递独立 mikan_id
- 增加镜像切换、全 DNS 失败、Mikan 缓存回退和字段保真测试
- 增加 ANIME_CATALOG_BASE_URLS 部署配置
- 版本升级至 1.16.1
```

## 主要文件

```text
app/anime_catalog.py
app/config.py
app/main.py
app/static/app.js
tests/test_catalog_weekly_sources.py
tests/test_deployment_files.py
.env.example
.env.fnos.example
docker-compose.fnos.yml
MULTI_SOURCE_WEEKLY_CATALOG.md
README.md
VALIDATION.md
```

## 数据库

不新增表或字段。原有订阅、下载记录、Mikan 缓存和共享周历缓存均保持兼容。

## 提交命令

```bash
git add .
git commit -m "fix(discovery): 为多站点周历增加 DNS 回退" \
  -m "多镜像失败时自动复用 Mikan 季度目录，避免 ANI.BT、Anime Garden、Nyaa 和 SubsPlease 同时不可用。"
```
