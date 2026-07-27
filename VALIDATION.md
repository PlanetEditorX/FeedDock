# FeedDock 1.15.0 验证报告

## 结论

FeedDock 1.15.0 已完成 Mikan、ANI.BT、Anime Garden（AG）和其它 RSS 四类订阅站点入口的实现与回归验证。

- **125 项 unittest 测试全部通过**；
- Python 全项目编译通过；
- 6 个前端 JavaScript 文件语法检查通过；
- Docker Compose、飞牛 Compose 和 GitHub Actions YAML 解析通过；
- 主页面 119 个、登录页 3 个、改密页 7 个 HTML ID 均唯一；
- FastAPI 应用可正常导入，运行版本为 `1.15.0`；
- 从 1.14.0 升级不新增数据库字段，不需要手工迁移。

## 功能覆盖

### 四类添加入口

- Mikan：继续进入季度番剧目录，可选择番剧与字幕组；
- ANI.BT：显示官方站点、RSS 帮助、单番剧地址示例和全站磁力流警告；
- Anime Garden：显示官方站点、帮助入口、过滤 RSS 示例和全站资源流警告；
- 其它 RSS：保持通用 RSS、Atom、RDF 输入模式。

### 站点目录与识别

- 后端集中维护订阅站点目录，前端通过认证 API 获取；
- 按 URL 主机名识别 `source_type` 和 `source_label`；
- 主机名使用边界匹配，`anibt.net.example.com` 不会被误识别为 ANI.BT；
- 未知站点归类为“其它 RSS”，订阅卡片仍优先保留用户填写的 RSS 名称；
- Mikan/AniBT 地址中的 `bangumiId` 或 `bgmId` 可自动补入订阅元数据。

### 安全默认值

- ANI.BT 和 Anime Garden 的全站 RSS 不自动写入表单；
- 用户点击“使用全站 RSS”时必须确认；
- 界面明确提示先配置包含、排除或字幕组规则，降低误下载大量资源的风险；
- 站点识别不信任用户可编辑的显示名称。

### 前端模块化

- 新增独立纯函数模块 `app/static/subscription-sources.js`；
- 负责目录规范化、来源查找、URL 来源识别和默认 Feed 可用性判断；
- 模块支持浏览器和 Node.js 测试环境；
- GitHub Actions 已加入该脚本的 `node --check`。

## 数据库升级

1.15.0 没有新增表或字段。来源类型由订阅主 RSS URL 动态识别，因此：

- 1.14.0 数据库可直接启动；
- 不修改历史订阅、条目、RSS 指纹或通知去重状态；
- 不需要手工 SQL；
- 导入导出格式保持兼容。

## 执行命令

```bash
PYTHONPATH=. python -m unittest discover -s tests
python -m compileall -q app tests

for file in \
  app/static/mikan-subscription-state.js \
  app/static/subscription-sources.js \
  app/static/navigation.js \
  app/static/app.js \
  app/static/login.js \
  app/static/change-password.js; do
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
assert settings.app_version == "1.15.0"
assert app.title == "FeedDock"
PY
```

## 重点测试文件

```text
tests/test_subscription_sources.py
tests/test_deployment_files.py
tests/test_subscription_management.py
tests/test_auth_flow.py
```

新增测试覆盖：

- 站点目录顺序和默认配置；
- Mikan、ANI.BT、Anime Garden 与未知 RSS 的来源识别；
- 主机名边界与相似恶意域名；
- `bangumiId`、`bgmId` 提取和自动写入；
- 订阅输出中的稳定来源字段；
- 认证后的站点目录 API；
- 前端来源模块的 Node.js 纯函数测试；
- 四类添加菜单、来源说明面板和全站 RSS 风险确认；
- 静态资源加载顺序与缓存版本。

## 环境限制

当前验证聚焦于应用代码、静态界面和配置文件，没有连接真实 Mikan、ANI.BT 或 Anime Garden 服务执行外部端到端订阅拉取。站点地址和接口格式通过官方公开文档核对，应用侧通过测试替身和纯函数测试验证分类、表单行为与持久化结果。
