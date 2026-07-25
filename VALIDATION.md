# FeedDock v1.4.0 验证报告

## 验证结论

通过 24 项自动化测试，并完成 Python 编译、前端 JavaScript 语法、Compose YAML 和 GitHub Actions YAML 校验。

## 手动更新检查

- 首页初始化只读取 `/api/config` 中的本地版本信息。
- 页面加载、订阅刷新和定时轮询均不会调用 `/api/update/status`。
- 只有点击“检查更新”按钮才调用 GitHub Release API。
- GitHub 返回 `403` 且 `X-RateLimit-Remaining: 0` 时，显示限额恢复时间和“再次手动检查”提示。
- 可选 `UPDATE_GITHUB_TOKEN` 会作为 Bearer Token 发送。

## 高级订阅

已验证：

- 主 RSS、备用 RSS 字段保存和读取。
- 参考标题、TMDB 标题、BgmUrl、日期和季字段。
- 普通文字匹配、正则排除和全局排除。
- `\d+(\.5)?`、捕获组 0、集数偏移和小数集数。
- 总集数上限。
- 自定义绝对下载路径预览。
- 遗漏集数计算。
- 只下载最新集配置保存。
- 编辑、启用、停用和删除订阅。

样例预览：

```text
参考标题：金牌得主 (2025)
RSS 标题：[LoliHouse] 金牌得主 - 14 [1080p]
正则：\d+(\.5)?
捕获组：0
偏移：-13
偏移后集数：1
最终路径：/vol2/1000/影视/金牌得主 (2025)/Season 2
```

## 数据库升级

启动时执行添加式 SQLite 迁移，为旧 `subscriptions` 表补充新字段。现有管理员、qBittorrent 配置、订阅和历史条目不会被删除。

## 限制

- TMDB 标题和 BgmUrl 当前是元数据字段，不会自动抓取 TMDB 或 Bangumi 信息。
- 遗漏检测以状态为 `queued` 的整数集数为依据；`.5` 特别集不计入 1 到总集数的整数缺失列表。
- 自定义下载路径由管理员输入，FeedDock 只发送给 qBittorrent，不验证该路径在 qBittorrent 主机上是否实际存在。
