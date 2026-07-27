# FeedDock 1.12.0 验证报告

## 1. 验证结论

FeedDock 1.12.0 已完成通知中心、下载完成跟踪、完结自动停用、遗漏告警去重和长期未更新检测的全量回归。

- **102 项自动化测试全部通过**。
- Python 全项目编译通过。
- 4 个前端 JavaScript 文件语法检查通过。
- Docker Compose、飞牛 Compose 和 GitHub Actions YAML 解析通过。
- FastAPI 应用可正常导入，运行版本为 `1.12.0`。
- 使用 1.10.1 结构构造的旧 SQLite 数据库完成增量迁移，历史订阅、条目和指纹均保留。
- 通知密钥遮蔽、错误脱敏、通知失败不阻断主流程等安全边界已覆盖测试。

## 2. 自动化测试覆盖

### 通知中心

- Telegram、Bark、通用 JSON Webhook 的配置校验和分发。
- 未选择事件时不发起网络请求。
- 启用通知中心时至少需要一个事件和一个完整渠道。
- API 返回配置时隐藏 Token、设备 Key、Webhook URL 和请求头。
- 网络或渠道异常中的 Token、URL、请求头值会被脱敏。
- 通知渠道失败不会中断 RSS 检查或下载任务。

### 订阅监控

- 主 RSS 与备用 RSS 的 Mikan `bangumiId` 识别和目录订阅标识。
- 下载开始与完成状态跟踪。
- 开启或关闭规范命名时均为 qBittorrent 任务写入唯一 Tag。
- 仅当 `1..总集数` 的整数集全部完成时自动停用。
- `.5` 等特别篇不会误判为正片完结。
- 已有历史完成任务在之后开启自动停用时也会被重新检查。
- 遗漏集数同时考虑排队中和已调度条目。
- 相同遗漏集合不重复通知；超过 10 集时记录状态但抑制噪声通知。
- 长期未更新通知持久化去重；发现新匹配条目后自动解除停更状态。
- 编辑总集数或监控开关时，仅重置相关去重状态。

### 回归范围

- RSS/Atom 解析、关键词和正则过滤、集数偏移、路径规则。
- qBittorrent 调度、下载完成后处理和规范命名。
- 数据库初始化及增量迁移。
- 登录、密钥读取、调试日志脱敏、部署文件和静态资源版本。

## 3. 执行结果

```text
Ran 102 tests in 1.736s

OK
Python compile OK
JS OK: app/static/mikan-subscription-state.js
JS OK: app/static/app.js
JS OK: app/static/login.js
JS OK: app/static/change-password.js
YAML OK: docker-compose.yml
YAML OK: docker-compose.fnos.yml
YAML OK: .github/workflows/docker-publish.yml
FastAPI import/version OK: 1.12.0
```

完整原始日志见发布包外附的 `FeedDock-1.12.0-validation.log`。

## 4. 执行命令

```bash
python -m unittest discover -s tests -v
python -m compileall -q app

node --check app/static/mikan-subscription-state.js
node --check app/static/app.js
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
    print("YAML OK:", filename)
PY

python - <<'PY'
from app.main import app, settings
assert settings.app_version == "1.12.0"
assert app.version == "1.12.0"
print("FastAPI import/version OK:", app.version)
PY
```

## 5. 旧数据库迁移验证

验证使用一份只包含 1.10.1 字段的 SQLite 数据库，预先写入订阅、历史条目和指纹，再由 1.12.0 初始化逻辑升级。

自动新增以下字段：

```text
auto_disable_when_complete
stale_days
last_new_item_at
last_stale_notified_at
completion_notified_at
last_missing_signature
```

验证结果：

```text
legacy migration OK: auto_disable_when_complete, completion_notified_at,
last_missing_signature, last_new_item_at, last_stale_notified_at, stale_days
legacy data preserved: Legacy Demo legacy-fingerprint
```

升级不需要手工执行 SQL，也不会删除历史数据。

## 6. 发布物复验

- 最终 ZIP 解压后再次运行 102 项测试、Python 编译、JavaScript 语法、YAML 和 FastAPI 导入检查，全部通过。
- Git 补丁已在干净的 1.10.1 基线仓库执行 `git apply --check` 和实际应用。
- 应用补丁后的目录与最终 ZIP 内容逐文件比较一致。
- ZIP 不包含 `__pycache__`、`.pyc`、SQLite 数据库或运行时 `data/` 目录。
- SHA-256 校验值单独写入 `FeedDock-1.12.0-SHA256SUMS.txt`。

## 7. 环境限制

当前执行环境未提供 Docker CLI，因此未实际构建、启动容器或连接真实 qBittorrent、Telegram、Bark 服务。Dockerfile、Compose 文件、应用导入、网络请求构造和各渠道分发逻辑已通过静态检查及隔离测试；部署后仍建议执行一次真实渠道测试和一条小体积下载的端到端验证。
