# FeedDock 1.16.0 验证报告

## 结论

FeedDock 1.16.0 已完成多站点番剧周历：Mikan、ANI.BT、Anime Garden、Nyaa 和 SubsPlease 均可按星期浏览，并具备标题搜索、缓存读取、强制更新、资源详情缓存和已订阅标识。

验证结果：

- **133 项 pytest 测试通过，另有 19 个子测试通过**；
- Python 全项目编译通过；
- 6 个前端 JavaScript 文件语法检查通过；
- Docker Compose、飞牛 Compose 和 GitHub Actions YAML 解析通过；
- 主页面 124 个、登录页 3 个、改密页 7 个 HTML ID 均唯一；
- FastAPI 应用可导入，运行版本为 `1.16.0`；
- 从 1.15.0 升级不新增数据库字段；
- 完整发布包解压回归与 Git 补丁升级回归均通过。

## 功能覆盖

### 统一周历

- Mikan 继续使用自身季度目录；
- ANI.BT、Anime Garden、Nyaa 和 SubsPlease 使用共享 `bangumi-data` 周历；
- 月度数据解析为 Asia/Tokyo 星期和播出时间；
- 中文、原始标题和英文标题组成搜索别名；
- 页面显示 `bangumi-data（CC BY 4.0）` 来源说明；
- 标题搜索在本地缓存中执行，不会产生额外外部请求。

### 站点 RSS 适配

- ANI.BT：按 Bangumi ID 生成全部发布、1080p 和 720p RSS；
- Anime Garden：生成标题过滤 RSS；
- Nyaa：生成英文字幕动画、可信发布和日文原盘 RSS；
- SubsPlease：生成 1080p、720p、SD 和全部分辨率 Feed，并自动设置标题包含规则；
- 不满足站点必要条件的条目会禁用，不生成伪造 RSS。

### 缓存和更新

- 共享周历复用 SQLite `mikan_cache_entries` 表；
- 普通读取命中持久化缓存；
- 强制更新失败时回退旧缓存并保留错误信息；
- 已浏览季度按 `MIKAN_CACHE_HOURS` 后台刷新；
- 失败缓存最多每小时重试一次；
- 资源详情会读取每一个 RSS 预设，而不只读取第一个；
- 第二次打开资源详情只读缓存；
- 周历和 RSS 请求都传入 FeedDock 代理配置。

### 前端

- “添加”菜单新增 Nyaa 和 SubsPlease；
- 五个站点都进入 `#add-catalog` 周历视图；
- 周历顶部可直接切换站点；
- 共用年份、季度、搜索、读取缓存和强制更新控件；
- Mikan 保留每星期隐藏过滤；
- 非 Mikan 站点显示站点专用 RSS 和最近资源预览；
- 保存、编辑或删除订阅后，当前周历的“已订阅”标识即时更新。

## 自动化测试

重点测试文件：

```text
tests/test_catalog_weekly_sources.py
tests/test_subscription_sources.py
tests/test_deployment_files.py
tests/test_mikan_cache.py
tests/test_mikan_subscription_state.py
```

新增测试覆盖：

- 月度数据转按星期周历；
- 中文、原始和英文标题别名；
- Bangumi 与 Mikan ID 提取；
- 四个共享周历站点的 RSS 预设；
- ANI.BT 已订阅识别；
- 本地标题搜索；
- 首次拉取、普通缓存读取和强制更新失败回退；
- 后台刷新已知过期季度；
- 每个资源 RSS 预设均被读取；
- 资源详情二次打开不重复请求；
- 代理数据库会话传入外部请求；
- 菜单、站点标签、通用 API 路径和静态资源版本。

## 执行命令

```bash
python -m pytest -q
python -m compileall -q app

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

python - <<'PY'
from app.config import settings
from app.main import app
assert settings.app_version == "1.16.0"
assert app.title == "FeedDock"
PY
```

## 旧数据库升级

使用原始 1.15.0 代码创建 SQLite 数据库和历史订阅，再使用 1.16.0 的 `ensure_schema()` 打开同一数据库。验证：

- 历史订阅仍存在；
- RSS URL、名称和启用状态保持不变；
- 现有缓存表可直接写入新的 `anime_catalog` 和 `source_detail` 类型；
- 不需要手工 SQL。

## 外部接口核对与环境限制

站点参数依据官方公开文档核对：ANI.BT 的 `bgmId` 和分辨率参数、Anime Garden 的过滤 RSS、SubsPlease 的 SD/720p/1080p/全部 Feed，以及 `bangumi-data` 的 CC BY 4.0 署名要求。

当前容器环境 DNS 解析被隔离，真实外部请求返回 `Temporary failure in name resolution`，因此没有在容器内执行站点端到端拉取。应用侧使用模拟响应验证 HTTP、RSS 解析、缓存、代理传递和错误回退；外部服务的实时可用性不在本报告保证范围内。

当前环境也没有 Docker CLI，因此未实际构建镜像；Compose 与 Dockerfile 已完成静态检查。
