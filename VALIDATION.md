# FeedDock 1.14.0 验证报告

## 结论

FeedDock 1.14.0 已完成页面、刮削、下载、RSS 和 Tracker 设置的实现与回归验证。

- **117 项 pytest 测试全部通过，另有 6 个 unittest subtests 通过**；
- Python 全项目编译通过；
- 5 个前端 JavaScript 文件语法检查通过；
- Docker Compose、飞牛 Compose 和 GitHub Actions YAML 解析通过；
- 主页面 111 个 HTML ID 均唯一；
- FastAPI 应用可正常导入，运行版本为 `1.14.0`；
- `git diff --check` 通过；
- 真实 1.13.0 SQLite 数据库增量升级通过，历史订阅和 RSS 指纹保留。

## 功能覆盖

### 页面设置

- 五种主题色写入服务器并同步浏览器本地缓存；
- 订阅支持按评分、拼音和更新时间排序；
- 元数据评分持久化并在订阅卡片显示；
- 页面加载前应用主题，避免明显闪烁。

### 刮削设置

- 全局自动元数据同步和 14 天追更窗口；
- TMDB API 与图片根地址可配置，并兼容带或不带 `/3`、`/t/p`；
- TMDB 同时支持 32 位 v3 API Key 和 v4 Read Access Token；
- 下载完成后安全生成 `bangumi.ini`；
- 开启功能时，符合条件的历史完成任务进入一次性补写队列；
- 写入目录必须位于统一媒体根目录内部。

### 下载设置

- qBittorrent 创建任务失败重试；
- 同时下载限制和后台空位重试；
- 并发等待与成功推送分开统计；
- 单任务做种时长传递到 qBittorrent；
- 所有任务继续使用唯一 `feeddock-item-{id}` Tag 跟踪。

### RSS 设置

- 全局 RSS 开关；
- 轮询间隔和请求超时；
- 规范目标文件已存在时自动跳过；
- 自动跳过对自动重命名和统一路径映射进行前后端双重约束；
- 创建、编辑、导入和批量启用均不能绕过该约束；
- 根据 Bangumi 总集数判断整季完成并自动停用；
- `.5` 特别篇不计入整数正片完成条件。

### Trackers

- 更新地址校验；
- Tracker 文本协议过滤、去重和数量限制；
- SQLite 缓存和更新时间；
- qBittorrent 返回任务哈希后追加 Tracker；
- Tracker 处理状态持久化，失败不会撤销下载任务。

## 数据库迁移

使用基线 Git 提交 `ee05b33` 创建真实 1.13.0 SQLite 数据库，写入一条订阅和一条带历史指纹的下载条目，再由 1.14.0 执行 `ensure_schema()`。

确认新增列：

```text
subscriptions.metadata_rating
subscriptions.total_episodes_checked_at
feed_items.trackers_status
feed_items.trackers_message
feed_items.trackers_applied_at
```

迁移后确认：

- 历史订阅名称仍为“迁移测试”；
- 历史 RSS 指纹仍为 `legacy-fingerprint`；
- 不删除或重建原表。

## 执行命令

```bash
PYTHONPATH=. pytest -q
python -m compileall -q app tests

for file in app/static/*.js; do
  node --check "$file"
done

python - <<'PY'
from pathlib import Path
import yaml

for name in (
    "docker-compose.yml",
    "docker-compose.fnos.yml",
    ".github/workflows/docker-publish.yml",
):
    yaml.safe_load(Path(name).read_text(encoding="utf-8"))
PY

PYTHONPATH=. python - <<'PY'
from app.main import app
from app.config import settings
assert settings.app_version == "1.14.0"
assert app.title == "FeedDock"
PY

git diff --check
```

## 重点测试文件

```text
tests/test_settings_features.py
tests/test_deployment_files.py
tests/test_subscription_management.py
tests/test_metadata_naming.py
tests/test_rss_service.py
tests/test_subscription_monitor.py
```

新增测试覆盖：

- 设置持久化和默认值；
- Tracker 过滤、去重与缓存；
- 自动跳过对重命名的依赖；
- 批量启用时的服务端约束；
- qBittorrent 做种时长参数；
- 并发满时等待与统计；
- 目标文件存在时跳过；
- 全局完结自动停用；
- `bangumi.ini` 写入位置和历史补写；
- TMDB v3 API Key 与 v4 Token 认证方式；
- 前端设置字段和后端执行入口的端到端静态连线。

## 环境限制

当前环境没有 Docker CLI，因此未实际构建或启动容器。也没有连接真实 qBittorrent、TMDB、Bangumi 或 Tracker 服务；外部交互使用测试替身验证请求参数、状态更新和错误隔离。

Chromium 可执行文件存在，但沙箱策略限制本地 HTTP 浏览器联调。本次界面通过 HTML 结构、Hash 路由测试、脚本语法检查和后端 API 测试验证。部署后仍建议执行一次主题切换、设置保存、Tracker 手动更新和 qBittorrent 推送的浏览器冒烟测试。
