# 变更记录

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
