# FeedDock v1.5.0 验证报告

## 验证结论

FeedDock v1.5.0 已通过 32 项自动化测试，并完成 Python 编译、前端 JavaScript 语法、Docker Compose YAML 和 GitHub Actions YAML 校验。

本版本新增 Mikan 与动漫花园的手动搜索、番剧选择和订阅表单预填，同时保留既有登录、qBittorrent、更新检查和高级订阅功能。

## Mikan 搜索与解析

已使用固定 HTML 样本和模拟 HTTP 服务验证：

- 从 `/Home/Search?searchstr=...` 搜索页解析番剧名称与 Bangumi ID。
- 对重复的番剧链接按 ID 去重。
- 从 `/Home/Bangumi/{id}` 详情页解析字幕组名称与 Subgroup ID。
- 支持从 `/Home/PublishGroup/{id}` 链接和 `id="subgroup-{id}"` 节点识别字幕组。
- 自动生成字幕组专用 RSS：

```text
/RSS/Bangumi?bangumiId={番剧ID}&subgroupid={字幕组ID}
```

- HTML 搜索页无法解析时，回退到 `/RSS/Search?searchstr=...` 关键词 RSS。
- 选择字幕组后只预填订阅表单，不会绕过预览直接保存。
- 首选 Mikan 地址不可用时，会依次尝试配置的备用地址。

## 动漫花园搜索与解析

已使用固定 RSS 样本和模拟 HTTP 服务验证：

- 根据关键词生成动漫花园 RSS：

```text
/topics/rss/rss.xml?keyword={关键词}&sort_id=2&team_id=0&order=date-desc
```

- 解析条目标题、详情地址、发布时间与 Torrent enclosure。
- 搜索结果第一项可直接选择“关键词 RSS”，用于持续接收后续发布。
- 也可选择某条发布，将其标题作为样本带入规则预览。
- 搜索结果只预填订阅表单，仍需管理员确认匹配、排除、集数和路径后保存。

## 搜索接口与页面

已验证：

- `GET /api/discovery/search` 支持 `all`、`mikan` 和 `dmhy`。
- `GET /api/discovery/mikan/{bangumi_id}` 返回可选字幕组。
- 两个接口都要求管理员登录。
- 同时搜索时，某一来源失败不会丢弃另一来源的结果。
- 页面包含来源选择、关键词搜索、结果卡片、字幕组选择和表单预填。
- 搜索只在点击“搜索”或“选择字幕组”时发起，不会后台自动访问来源站点。
- 前端使用 DOM API 渲染外部标题，不把来源内容直接写入 `innerHTML`。

## 既有功能回归

仍通过以下测试：

- 首次登录强制修改密码及容器重启后的密码持久化。
- 管理接口改密前锁定、注销和会话失效。
- 网页配置外部 qBittorrent、密码保留和重启持久化。
- qBittorrent 登录、版本读取和任务推送。
- GitHub Release 仅手动检查、限流提示和更新触发。
- 主/备用 RSS、高级匹配、全局排除、集数偏移、小数集数和路径预览。
- 遗漏检测、只下载最新集、编辑和删除订阅。
- RSS 2.0、Atom、Torrent enclosure、Magnet 和路径越界防护。
- 飞牛 OS 绝对数据目录、宿主机网关和 GHCR 镜像配置。
- Docker 镜像发布后自动创建对应 GitHub Release。

## 配置验证

飞牛 OS Compose 已包含：

```yaml
MIKAN_BASE_URL: "https://mikanime.tv"
MIKAN_FALLBACK_URLS: "https://mikanani.me,https://mikanani.kas.pub"
DMHY_BASE_URL: "https://share.dmhy.org"
```

这些值只决定搜索来源，不会修改现有订阅。替换地址并重新部署后，已有数据库仍保留。

## 测试边界

当前构建环境无法进行外部 DNS 解析，因此没有直接请求线上 Mikan 或动漫花园。本次集成验证使用 `httpx.MockTransport`、真实格式的 HTML/RSS 样本和实际应用 API 完成。

第三方站点可能调整页面结构、域名、访问策略或启用反爬限制。FeedDock 已提供备用 Mikan 地址、关键词 RSS 回退、部分来源失败保留结果和可配置站点地址，但线上可用性仍取决于飞牛 OS 当时的网络及来源站点状态。

动漫花园提供的是关键词发布搜索，而不是具有统一作品 ID 的番剧目录，因此选择动漫花园结果时会预填关键词 RSS 和样本标题，不会自动推断季度、总集数或 TMDB/Bangumi 元数据。
