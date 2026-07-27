# FeedDock 1.13.0 验证报告

## 1. 验证结论

FeedDock 1.13.0 已完成订阅优先界面、任务导航、批量管理、导入导出、常规密码修改和安全系统操作的全量回归。

- **105 项自动化测试全部通过**；
- Python 全项目编译通过；
- 5 个前端 JavaScript 文件语法检查通过；
- Docker Compose、飞牛 Compose 和 GitHub Actions YAML 解析通过；
- FastAPI 应用可正常导入，运行版本为 `1.13.0`；
- Git 差异执行 `git diff --check` 通过；
- 静态页面不存在重复 HTML ID，默认可见视图仅为订阅首页和全局页脚；
- 从 1.12.0 升级不增加数据库字段，不需要手工迁移；
- 系统重启与关闭默认禁用，未开启环境变量时 API 和按钮均不可用。

## 2. 新界面与导航覆盖

### 默认订阅首页

- 登录后默认显示订阅统计、搜索、状态筛选和订阅卡片；
- 下载、添加编辑器、设置和日志默认隐藏；
- 订阅列表在最近下载条目之前；
- 订阅卡片仍保留单项编辑、启停、刷新和删除能力；
- Mikan 目录中的“已订阅”状态同步保持有效。

### 顶部任务导航

覆盖以下入口和路由：

```text
添加
  Mikan
  ANI.BT
  Anime Garden
  其它 RSS
  添加合集
下载
刷新全部订阅
管理
  查看订阅状态
  批量管理
  导入订阅
  导出订阅
设置
  下载设置
  基本设置
  代理设置
  登录设置
  通知
  系统管理
日志
```

`navigation.js` 对未知 Hash 回退到订阅首页，并在切换视图时同步标题、说明、激活状态和 URL Hash。

### 批量管理与导入导出

- 批量启动、禁用和删除；
- 搜索与状态筛选后的“全选当前结果”；
- 批量删除二次确认；
- 未选择项目时“导出所选”不会错误导出全部；
- 导出数据不包含数据库 ID；
- 导入支持主 RSS 地址冲突的“跳过”与“更新”；
- 单次导入上限 500 条，批量操作上限 1000 个订阅 ID；
- 订阅创建、更新、跳过、启停和删除生命周期均有数据库测试。

### 登录与系统管理

- 首次登录仍强制修改初始密码；
- 完成初始化后 `/change-password` 仍可访问；
- 常规修改密码后返回 `/#settings-login`；
- 修改密码会更新当前会话并使旧会话失效；
- `FEEDDOCK_ALLOW_SYSTEM_ACTIONS=false` 时系统状态明确返回默认禁用；
- 重启和关闭接口只有在显式启用后才接受请求；
- 文档说明了 Docker 重启策略对“关闭”行为的影响。

## 3. 原有功能回归

105 项测试同时覆盖：

- RSS/Atom 解析、关键词和正则过滤、集数偏移、路径安全；
- Mikan 目录解析、缓存、封面代理、星期过滤和已订阅标识；
- qBittorrent 推送、保存配置、任务 Tag、下载进度和规范命名；
- TMDB、Bangumi、AniList 元数据和季度识别；
- Telegram、Bark、Webhook 通知及敏感信息脱敏；
- 完结自动停用、遗漏去重和长期未更新检测；
- 登录流程、静态资源缓存参数、部署配置和更新检查。

## 4. 执行结果

```text
Ran 105 tests in 1.709s

OK
compileall: OK
app/static/app.js: OK
app/static/navigation.js: OK
app/static/mikan-subscription-state.js: OK
app/static/login.js: OK
app/static/change-password.js: OK
docker-compose.yml: OK
docker-compose.fnos.yml: OK
.github/workflows/docker-publish.yml: OK
FastAPI import/version: OK
git diff HEAD --check: OK
```

原始主验证日志见发布包外附的 `FeedDock-1.13.0-validation.log`。

## 5. 执行命令

```bash
python -m unittest discover -s tests -v
python -m compileall -q app

node --check app/static/app.js
node --check app/static/navigation.js
node --check app/static/mikan-subscription-state.js
node --check app/static/login.js
node --check app/static/change-password.js

python - <<'PY'
from pathlib import Path
import yaml

for filename in (
    "docker-compose.yml",
    "docker-compose.fnos.yml",
    ".github/workflows/docker-publish.yml",
):
    yaml.safe_load(Path(filename).read_text(encoding="utf-8"))
    print(filename, "OK")
PY

DATA_DIR="$(mktemp -d)" APP_VERSION=1.13.0 python - <<'PY'
from app.main import app
from app.config import settings
assert settings.app_version == "1.13.0"
assert app.version == "1.13.0"
print("FastAPI import/version: OK")
PY

git diff HEAD --check
```

## 6. 数据库升级

1.13.0 不增加数据库列。启动时仍保留之前版本的增量迁移逻辑，因此：

- 1.12.0 数据库可以直接使用；
- 从 1.10.1 或更早兼容版本直接升级时，旧的监控字段仍会自动补齐；
- 不删除订阅、下载条目、RSS 指纹、通知配置或 Mikan 缓存；
- 导入订阅只处理配置字段，不导入历史条目和内部去重状态。

## 7. 发布物复验

- 最终 ZIP 解压后再次运行 105 项测试、Python 编译、JavaScript 语法、YAML 和 FastAPI 版本检查；
- 从 1.12.0 发布包生成的 Git 补丁执行 `git apply --check` 和实际应用；
- 应用补丁后的目录与最终 ZIP 内容逐文件比较；
- ZIP 排除 `.git`、`__pycache__`、`.pyc`、SQLite 数据库和运行时 `data/`；
- SHA-256 校验值写入 `FeedDock-1.13.0-SHA256SUMS.txt`。

## 8. 环境限制

当前环境没有 Docker CLI，因此未实际构建或启动容器，也未连接真实 qBittorrent、Telegram、Bark 服务。

环境虽然提供 Chromium 可执行文件，但安全策略阻止浏览器访问本地 HTTP 服务（`ERR_BLOCKED_BY_ADMINISTRATOR`），因此没有完成真实浏览器点击录制。界面行为改用以下方式验证：

- Hash 路由模块的 Node 测试；
- HTML 结构、默认可见视图和 ID 唯一性测试；
- FastAPI 认证与页面路由测试；
- 前端脚本语法检查；
- 后端管理 API 和数据库生命周期测试。

部署后建议在实际浏览器中执行一次首次登录、顶部菜单切换、批量启停和导入导出冒烟测试。
