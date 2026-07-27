# FeedDock 1.17.12 配置备份、订阅迁移与 RSS 恢复

## 全系统配置导出

入口：`设置 → 系统管理 → 配置备份与恢复`。

系统备份使用 JSON，包含：

- 网页可修改的下载器、页面、RSS、Tracker、元数据、刮削、定时任务、代理、通知、全局规则和日志级别；
- 当前有效值，即某项仍来自 Compose 默认值时也会写入备份；
- 全部订阅定义；
- 跨站番剧隐藏偏好及 Mikan 周历隐藏设置。

不包含：

- 管理员密码及会话；
- RSS 下载历史、qBittorrent 任务状态和日志；
- Mikan/原站目录缓存、Tracker 缓存、更新检查缓存；
- 媒体文件、NFO、海报和数据库外的 Compose 文件。

### 敏感值

默认不导出 qBittorrent 密码、TMDB/Bangumi Token、Emby/TMM 密钥、代理地址、Telegram/Bark/Webhook 私密值。勾选“包含密码、Token 与私密地址”后才会写入。

包含敏感值的备份应加密保存，不应提交到 Git 或发送到公开渠道。

## 全系统配置导入

支持两种方式：

- **合并**：保留现有配置；备份中的设置覆盖同名设置，订阅按主 RSS 地址跳过或更新；
- **替换**：替换网页配置、全部订阅和隐藏偏好。替换订阅会清除 FeedDock 内的条目历史，但不会删除媒体文件或 qBittorrent 中的任务。

不含敏感值的备份以替换模式恢复时，当前实例已经保存的密码与 Token 会保留，避免无意清空凭据。

Compose 环境变量、卷挂载、端口、DNS、Watchtower 和容器权限必须继续在 Compose 中维护，JSON 导入不会修改容器定义。

## 仅订阅导入导出

订阅列表的批量管理和系统备份面板都提供独立的订阅导入导出。

导出格式：

```json
{
  "format": "feeddock-subscriptions",
  "version": 2,
  "app_version": "1.17.12",
  "exported_at": "2026-07-27T00:00:00+00:00",
  "subscriptions": []
}
```

订阅定义包含 RSS、备用 RSS、匹配规则、集数偏移、元数据身份、命名模板、下载路径策略、停更与完结规则，不包含数据库 ID、下载历史和日志。

## 更新 RSS

每张订阅卡片的“更新 RSS”不再只选中原 URL，而是自动执行候选搜索：

1. 当前来源是 Mikan 时，优先使用现有 Mikan 番剧 ID；
2. 有 Bangumi Subject ID 时，ANI.BT 与 Anime Garden 优先精确查询该 ID；
3. 继续使用参考标题、TMDB 标题、手动标题和订阅名称搜索；
4. 分别读取 Mikan、ANI.BT、Anime Garden 的番剧与字幕组信息；
5. 按站点列出所有匹配字幕组 RSS。

候选 RSS 支持：

- 填入主 RSS；
- 填入备用 RSS；
- 保存为主 RSS 并立即检查当前订阅；
- 打开原站详情。

TMDB ID 本身不能直接换算成第三方 RSS 站点 ID；FeedDock 使用已经同步的 TMDB 标题参与搜索。Bangumi ID 和当前站点番剧 ID 则用于精确匹配。

## 空 RSS 错误

`主 RSS 没有条目` 属于可恢复的业务错误。INFO 日志不再显示内部 JSON 和 Python Traceback，而会显示：

```text
订阅 ID：1
订阅名称：示例番剧
错误：主 RSS 没有条目
处理建议：请在订阅卡片点击“更新 RSS”，按当前番剧信息重新搜索 Mikan、ANI.BT 与 Anime Garden。
```

DEBUG 日志仍保留完整堆栈，供开发排查解析器或网络异常。

备用 RSS 返回空列表时也会判定为“备用 RSS 没有条目”，不会再被误认为成功。
