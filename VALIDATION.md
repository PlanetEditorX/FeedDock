# FeedDock 1.16.1 验证报告

## 结论

FeedDock 1.16.1 修复了 ANI.BT、Anime Garden、Nyaa 和 SubsPlease 周历共同依赖单一 GitHub Raw 域名的问题。

验证结果：

- **137 项 pytest 测试通过，另有 19 个子测试通过**；
- Python 全项目编译通过；
- 6 个前端 JavaScript 文件语法检查通过；
- Docker Compose、飞牛 Compose 和 GitHub Actions YAML 解析通过；
- 主页面 124 个、登录页 3 个、改密页 7 个 HTML ID 均唯一；
- FastAPI 可导入，运行版本为 `1.16.1`；
- 默认配置包含 3 个 `bangumi-data` 周历镜像；
- 不新增数据库表或字段；
- 完整发布包解压回归和从 1.16.0 应用 Git 补丁回归均通过。

## 修复覆盖

### 多镜像顺序回退

默认顺序：

1. `cdn.jsdelivr.net`
2. `fastly.jsdelivr.net`
3. `raw.githubusercontent.com`

每个月按顺序尝试。某个镜像发生 DNS 解析失败后，会在当前刷新周期熔断，后续月份不会重复等待该域名。

### Mikan 目录回退

当季度中任意月份无法从所有 `bangumi-data` 镜像读取时：

- 优先复用 Mikan 同季度目录；
- Mikan 强制更新失败但已有本地缓存时，继续读取缓存；
- 页面显示明确的回退提示；
- Mikan ID 与 Bangumi 条目 ID 分开保存，不会污染元数据字段；
- ANI.BT 使用兼容的 `bangumiId` 参数生成 RSS；
- Anime Garden、Nyaa 和 SubsPlease 继续基于标题生成各自 RSS。

如果 Mikan 也不可用，但部分月份已成功读取，则显示部分季度数据；只有所有来源均失败且没有缓存时才返回错误。

### 缓存兼容

- 原 `anime:catalog:{year}:{season}` 缓存键保持不变；
- 缓存 schema 版本从 1 升至 2，用于触发一次容错逻辑刷新；
- 刷新失败时仍可回退旧缓存；
- 原 Mikan 缓存、订阅、下载记录和系统设置不受影响。

## 自动化测试重点

`tests/test_catalog_weekly_sources.py` 新增覆盖：

- 首个镜像 DNS 失败后自动使用第二镜像；
- DNS 失败镜像在后续月份被熔断；
- 所有镜像 DNS 失败后自动回退 Mikan；
- 回退目录保留星期、封面、Mikan ID 和播出时间；
- ANI.BT 生成 `bangumiId` 兼容 RSS；
- 强制更新 Mikan 失败后读取已有 Mikan 缓存；
- 标准 Bangumi ID 不被 Mikan ID 覆盖。

`tests/test_deployment_files.py` 新增覆盖：

- 飞牛 Compose 包含多镜像默认配置；
- 前端向详情接口单独传递 `mikan_id`；
- 前端显示 `fallback_notice`。

## 执行命令

```bash
PYTHONPATH=. pytest -q
python -m compileall -q app tests
node --check app/static/app.js
node --check app/static/change-password.js
node --check app/static/login.js
node --check app/static/mikan-subscription-state.js
node --check app/static/navigation.js
node --check app/static/subscription-sources.js
```

YAML 和 HTML ID 通过独立 Python 检查脚本验证。

## 未执行项目

当前环境没有 Docker CLI，因此未实际构建容器镜像。沙箱网络不适合验证用户所在网络的 DNS 路由，因此未把真实外部站点请求作为通过条件；DNS 失败、多镜像切换、缓存回退和 RSS 生成均通过模拟 HTTP/异常测试验证。
