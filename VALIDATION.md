# FeedDock v1.6.1 验证报告

## 结论

FeedDock v1.6.1 已通过 40 项自动化测试，并完成 Python 编译、JavaScript 语法以及 Compose / GitHub Actions YAML 解析检查。

## Mikan 季度目录

已验证：

- 调用 `/Home/BangumiCoverFlowByDayOfWeek?year=...&seasonStr=...` 获取季度目录。
- 解析 `data-dayofweek` 并按星期分组。
- 解析番剧 ID、标题、封面、更新时间和详情地址。
- 支持 `data-src`、`data-original`、`srcset` 与 CSS `background-image` 封面。
- 同源封面代理校验来源主机、图片类型和 6 MiB 大小上限。
- 同一番剧 ID 自动去重。
- 支持在选定季度内按标题筛选。
- 主地址失败时尝试备用 Mikan 地址。
- 年份与季度参数校验。

## 字幕组与 RSS

已验证：

- 点击番剧后请求 `/Home/Bangumi/{id}`。
- 从字幕组链接与页面节点提取 Subgroup ID。
- 支持 `div.subgroup-text` 的纯数字 ID、`subgroup-*` ID 和 `data-subgroupid`。
- 含无 `property/name` 的 `meta` 标签时不会再触发空值 `.lower()`。
- 生成专用 RSS：

```text
/RSS/Bangumi?bangumiId={番剧ID}&subgroupid={字幕组ID}
```

- 页面显示 RSS 地址、复制按钮和订阅按钮。
- 选择订阅后预填名称、来源和 RSS，不会跳过规则预览直接保存。

## 页面行为

已验证：

- 首页包含年份、季度、标题筛选和“加载番剧”。
- 番剧按星期分区，以封面卡片显示。
- 前端优先使用 FeedDock 同源封面代理，失败后回退原地址与文字占位。
- 番剧详情使用弹窗显示字幕组 RSS。
- 页面加载不会自动访问 Mikan。
- 外部标题使用 DOM 文本节点渲染，不直接写入 `innerHTML`。
- 移动端目录和详情弹窗具有响应式布局。
- 使用 Chromium 无头浏览器模拟加载目录、点击番剧和显示 RSS 弹窗，未出现前端运行错误。

## 既有功能回归

以下功能继续通过测试：

- 首次登录强制改密和密码持久化。
- 网页配置外部 qBittorrent。
- qBittorrent 登录、读取版本和推送任务。
- GitHub Release 手动检查、限流提示和更新触发。
- 主/备用 RSS、规则过滤、集数偏移、小数集数和路径预览。
- 遗漏检测、只下载最新集、编辑与删除订阅。
- RSS、Atom、Torrent enclosure、Magnet 和路径越界防护。
- 飞牛绝对数据路径、宿主机网关和 GHCR 镜像配置。
- Docker 镜像成功后自动创建 Release。

## 测试边界

当前构建环境不能直接访问线上 Mikan，因此目录与详情集成测试使用真实页面结构格式的固定 HTML 样本和 `httpx.MockTransport`。第三方站点若调整 HTML 结构、域名或访问策略，解析器可能需要随之更新。
