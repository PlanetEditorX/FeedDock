# 变更记录

## 未发布

### 订阅星期分组与导航菜单修复

- 管理菜单中的“查看订阅状态”统一改为“订阅列表”。
- 订阅排序选择“按星期”时改为星期一至星期日分区展示，不再只把全部卡片混排在同一网格中；未设置首播日期的订阅单独归入“未设置星期”。
- 顶部菜单箭头改为尺寸统一的 CSS 图形，并随悬浮窗展开或收起切换方向。
- 顶部悬浮菜单改为互斥展开；打开另一个菜单、点击菜单项、点击空白区域或按 Esc 时会关闭此前菜单。

### 订阅列表排序与构建信息修复

- 修复订阅列表“批量管理”按钮在窄空间中被逐字竖排的问题。
- 订阅列表新增按星期、更新时间、添加时间、名字和评分排序，并可在列表中直接切换和单独持久化。
- 旧的“拼音”排序设置自动迁移为“按名字”。
- 修复 Dockerfile 将 `${APP_VERSION}`、`${APP_REVISION}` 原样写入镜像构建信息文件的问题。
- 构建信息读取会拒绝未展开的 Docker ARG 占位符，避免页面显示异常变量文本和误判镜像更新。

### 镜像版本同步修复

- 当前版本、revision 和构建时间改为优先读取镜像内 `/app/.feeddock-build.json`，避免 Watchtower 复用旧容器环境变量后显示旧版本。
- Dockerfile 不再将构建版本作为最终镜像 `ENV`，仅保留 OCI 标签和不可变构建信息文件。
- 同 revision 且本地版本仅来自环境变量时，不再误报“发现新镜像”，而是提示重新创建容器。
- 系统更新页面新增“本地元数据”来源。
- 登录页、修改密码页和主页面的静态资源缓存参数改为按运行镜像 revision 动态生成。

### 容器镜像更新检测

- 在线更新检查改为直接读取 `FEEDDOCK_IMAGE` 对应容器仓库的 OCI manifest 和镜像 config。
- 使用 `org.opencontainers.image.revision` 比较当前运行镜像与远端标签，不再依赖静态版本清单或 GitHub Release。
- 页面新增当前构建、远端构建、远端 digest 和镜像平台信息。
- 删除 `update.json` 及 GitHub Release API 备用检查配置。
- Docker 构建写入 OCI 标签和镜像内不可变构建信息文件。

### 镜像发布流程

- 工作流从远端 `latest` 镜像读取上一版本并自动递增补丁号。
- 不再自动修改或提交版本文件，避免发布提交循环和分支保护冲突。
- 远端镜像 revision 已等于当前提交时跳过重复构建。
- GitHub Release 改为镜像发布后的可选记录，创建失败不影响镜像发布结果。

## 1.17.13 - 2026-07-28

### 自动版本发布

- 默认分支不再要求手动创建或推送 Git 标签。
- 工作流比较最新 GitHub Release 与当前代码，发现重要文件存在累计变化时自动递增补丁版本。
- 自动同步 `VERSION`、`update.json`、Docker 构建版本、运行时默认版本和前端静态资源缓存参数。
- 镜像发布成功后自动创建对应 Git 标签和 GitHub Release。
- 仅文档和测试变化不会创建新版本；发布范围由 `.github/release-paths.txt` 统一维护。


### Docker 在线更新与文档结构

- `docker-compose.yml` 与 `docker-compose.fnos.yml` 统一使用远程镜像并提供可选 `updater` profile。
- 两个 Compose 均包含 Watchtower HTTP API、共享 Token、容器标签、独立网络和 DNS 配置。
- 根目录文档按部署、使用指南、参考资料和历史分析重新归档。
- 合并重复的 qBittorrent、元数据、命名和媒体目录说明。

### 通知与订阅交互

## Bark 修复

- Bark 地址可填写服务根地址或完整 `/push` 地址。
- 发送前统一归一化端点，避免生成 `/push/push`。
- Device Key 继续使用 Bark JSON 字段 `device_key`，不写入 URL，降低代理日志泄密风险。

## 通知模板与预览

- 新增标题模板和正文模板。
- 新增 `POST /api/notifications/preview`，页面预览与实际发送共用同一套服务端渲染逻辑。
- 模板支持事件、订阅和条目相关的平面变量，并校验未知变量及高级格式表达式。

## 交互与文案

- 设置菜单和页面标题统一改为“通知设置”。
- 添加订阅状态下显示“取消添加”；编辑状态下显示“取消编辑”。

## 模块拆分

后端通知逻辑拆分到 `app/notification/`：

- `config.py`：配置持久化与校验；
- `templates.py`：模板变量、校验和渲染；
- `channels.py`：Telegram、Bark、Webhook 渠道适配；
- `service.py`：统一编排、脱敏错误和预览；
- `types.py`：结果值对象。

前端通知设置拆分到 `app/static/modules/notification-settings.js`。旧的 `app/notifications.py` 和 `app/notification_config.py` 保留兼容入口，避免影响现有调用方。

## 测试

执行：

```bash
PYTHONPATH=. pytest -q
```

结果：`178 passed, 15 subtests passed`。

### qBittorrent 下载完成记录延迟清理

- 支持开关和可配置等待分钟数。
- 优先依据 qBittorrent `completion_on` 计算到期时间。
- 删除任务记录时固定 `deleteFiles=false`，保留媒体文件。
- 后处理等待或失败时暂缓清理。
