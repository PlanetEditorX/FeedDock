# FeedDock 1.17.12 验证报告

## 功能范围

- 两份 Compose 的 Watchtower HTTP API、共享 Token、内部网络、容器标签和 Docker Socket 挂载；
- 根目录文档精简及 `docs/` 分类、重复 qBittorrent 与媒体文档合并；

- 全系统 JSON 备份与恢复：网页有效配置、全部订阅和番剧隐藏偏好；
- 敏感值默认省略，可选择包含；
- 合并恢复与替换恢复；
- 不含敏感值的替换恢复保留当前实例密码与 Token；
- 独立订阅导入导出格式升级为 v2；
- 更新 RSS 时跨 Mikan、ANI.BT、Anime Garden 搜索候选；
- 当前站点番剧 ID、Bangumi ID、参考标题、TMDB 标题、手动标题和订阅名称参与匹配；
- 空 RSS 在 INFO 日志中显示处理建议，不展示内部 Traceback 或 RSS 私密地址。

## 自动化测试

```text
182 passed, 15 subtests passed
```

新增覆盖：

- 系统备份导出有效配置并排除缓存与迁移标记；
- 默认不导出 qBittorrent 密码等敏感值；
- 不含敏感值的替换恢复保留现有密钥；
- 跨站搜索列出三个站点及其全部字幕组 RSS；
- 旧 ANI.BT 订阅在缺少独立 Bangumi ID 时仍使用当前站点番剧 ID 精确恢复；
- 空 RSS 的 INFO 日志包含“更新 RSS”处理建议，且不包含 Traceback、`rss_url` 或完整 URL；
- 原有订阅、下载、刮削、更新、通知、目录、网络和鉴权回归测试。

## 静态与结构检查

- Python `compileall`：通过；
- 6 个 JavaScript 文件 `node --check`：通过；
- `docker-compose.yml`、`docker-compose.fnos.yml`、Watchtower 配置和 GitHub Actions YAML：通过；
- `index.html`：152 个 ID，无重复；
- `login.html`：3 个 ID，无重复；
- `change-password.html`：7 个 ID，无重复；
- `app.js` 的 146 个 `getElementById` 引用均可在主页面找到；
- FastAPI 版本：`FeedDock 1.17.12`；
- 系统备份导入/导出和 RSS 候选路由均已注册；
- `VERSION` 与 `update.json` 均为 `1.17.12`；
- `git diff --check`：通过。

## 数据与恢复边界

- 替换订阅会删除 FeedDock 内的订阅条目历史，但不会删除媒体文件或 qBittorrent 任务；
- 管理员密码、登录会话、运行日志、下载历史、缓存、媒体文件和 Compose 文件不进入系统备份；
- Compose 的端口、卷挂载、DNS、PUID/PGID、Watchtower 和容器权限必须单独迁移；
- 单次订阅导入仍限制为 500 条。

## 法律文本说明

免责声明继续明确技术中立不等同于用途合法，且不排除依法不得免除的责任。民法典第五百零六条规定，造成人身损害以及因故意或重大过失造成对方财产损失的免责条款无效。该文本是开源项目的一般说明，不构成法律意见。

## 环境限制

当前验证环境没有连接生产 qBittorrent、真实用户媒体库或持续可用的三个 RSS 原站。跨站候选通过与原站响应结构一致的模拟提供器验证；请求编排、身份优先级、分组展示、保存和日志链路均已覆盖。发布后仍应在实际网络环境中确认站点可达性和 RSS 有效性。
