# FeedDock 1.16.1 多站点番剧周历

## 目标

1.16.1 将 ANI.BT、Anime Garden、Nyaa 和 SubsPlease 从“只有站点说明的通用表单”升级为与 Mikan 一致的番剧发现流程：

- 按年份和季度读取番剧；
- 按星期展示；
- 在当前目录内搜索标题和别名；
- 优先读取 SQLite 持久化缓存；
- 支持管理员手动强制更新；
- 已浏览季度按缓存周期后台更新；
- 点击番剧后生成站点专用 RSS，并缓存最近资源预览；
- 已订阅番剧即时显示“已订阅”。

## 为什么使用统一周历层

并非每个资源站都提供与 Mikan 完全相同的季度目录 API。FeedDock 因此把能力拆为两层：

1. **番剧周历层**负责季度、星期、标题、翻译和 Bangumi 条目 ID；
2. **资源站适配器**负责把选中的番剧转换成站点支持的 RSS 与筛选规则。

共享周历使用 `bangumi-data` 的月度 JSON 数据。页面会显示 `番剧周历数据：bangumi-data（CC BY 4.0）`，以保留数据来源说明。

Mikan 不经过共享周历，继续使用自身季度目录、字幕组列表和封面缓存。

## 1.16.1 网络容错

共享周历默认依次尝试：

```text
https://cdn.jsdelivr.net/gh/bangumi-data/bangumi-data@master/data/items
https://fastly.jsdelivr.net/gh/bangumi-data/bangumi-data@master/data/items
https://raw.githubusercontent.com/bangumi-data/bangumi-data/master/data/items
```

配置项：

```dotenv
ANIME_CATALOG_BASE_URLS=地址1,地址2,地址3
```

行为：

1. 每个月按镜像顺序尝试；
2. 检测到 DNS 解析失败后，该镜像在本轮立即熔断，后续月份不再重复等待；
3. 三个月未能全部读取时，自动读取 Mikan 同季度目录；
4. 强制更新 Mikan 失败但本地已有 Mikan 缓存时，继续使用缓存；
5. Mikan 也不可用时，如果已成功读取部分月份，则显示部分数据；
6. 所有来源均失败且没有任何缓存时，才返回错误。

回退数据保留 Mikan ID，不会伪装成 Bangumi 条目 ID。ANI.BT 使用官方支持的 `bangumiId` 兼容参数；Anime Garden、Nyaa 和 SubsPlease 使用标题生成 RSS。

## 支持站点

### Mikan

- 使用 Mikan 原生季度目录；
- 按星期展示；
- 标题搜索；
- 读取缓存、强制更新；
- 打开番剧后列出字幕组 RSS；
- 支持每个星期的隐藏过滤；
- 保留本地 WebP 封面缓存。

### ANI.BT

- 使用共享番剧周历；
- 标准周历使用 Bangumi 条目 ID；Mikan 回退目录使用 Mikan ID；
- 自动生成全部发布、1080p 和 720p RSS；
- 标准模式使用 `bgmId`，回退模式使用 ANI.BT 官方兼容的 `bangumiId`；
- 资源详情分别缓存各 RSS 的最近条目。

既没有 Bangumi 条目 ID、也没有 Mikan ID 的番剧会保留在周历中，但按钮禁用并说明无法生成 ANI.BT RSS。

### Anime Garden

- 使用共享番剧周历；
- 自动生成包含当前番剧标题的过滤 RSS；
- 打开详情时读取并缓存过滤后的最近资源；
- 不会默认使用未过滤的全站 Feed。

### Nyaa

- 使用共享番剧周历；
- 优先使用原始日文/英文标题生成关键词 RSS；
- 提供英文字幕动画、可信发布和日文原盘三种预设；
- 各预设独立缓存资源预览。

Nyaa 的标题匹配依赖站点发布标题。保存前仍可编辑匹配、排除和字幕组规则。

### SubsPlease

- 使用共享番剧周历；
- 提供 1080p、720p、SD 和全部分辨率 RSS；
- 由于官方 RSS 是分辨率级全站 Feed，FeedDock 会自动填写番剧英文标题作为包含规则；
- 详情预览也会按番剧别名过滤，避免显示无关资源。

## 缓存行为

共享周历和站点资源详情复用现有 `mikan_cache_entries` 表，不增加数据库结构。

### 周历缓存

缓存键：

```text
anime:catalog:{year}:{season}
```

行为：

- 第一次读取：从多镜像获取季度对应月份；全部镜像失败时复用 Mikan 季度目录；
- 普通读取：只读缓存，不因为切换站点或输入搜索词重复请求；
- 搜索：在缓存结果中本地过滤；
- 强制更新：重新获取共享周历；镜像失败时回退 Mikan，全部失败时继续显示旧缓存并记录错误；
- 后台更新：只更新用户已经浏览过、且超过缓存周期的季度；
- 失败重试：同一失败缓存最多每小时重试一次。

ANI.BT、Anime Garden、Nyaa 和 SubsPlease 共享同一份周历缓存，因此切换站点不会重复下载季度数据。

### 资源详情缓存

缓存键包含站点、Bangumi 条目 ID 和标题摘要：

```text
anime:detail:{source}:{subject_id}:{title_hash}
```

- 首次打开番剧时生成所有 RSS 预设并读取最近资源；
- 再次打开优先读取缓存；
- “强制更新资源”重新读取该站点的全部 RSS 预设；
- 某一个 RSS 失败只记录在该预设中，不会影响其它预设和订阅按钮。

## 代理

共享周历和各站点 RSS 请求使用 FeedDock 的代理配置。需要代理访问 GitHub、Nyaa 或其它站点时，在 `设置 → 代理设置` 中配置即可。

## API

### 周历

```http
GET /api/discovery/catalog/{source_id}?year=2026&season=夏&q=标题
POST /api/discovery/catalog/{source_id}/refresh?year=2026&season=夏&q=标题
```

`source_id` 支持：

```text
anibt
ag
nyaa
subsplease
```

Mikan 保持原 API：

```http
GET /api/discovery/mikan/catalog
POST /api/discovery/mikan/catalog/refresh
```

### 资源详情

```http
GET /api/discovery/catalog/{source_id}/detail
```

参数包含标题、原始标题、英文标题、别名和可选 Bangumi 条目 ID。`force_refresh=true` 时强制刷新资源详情缓存。

## 升级

从 1.15.0 升级到 1.16.1：

- 不增加数据库表或字段；
- 不修改已有订阅和下载历史；
- 旧 Mikan 缓存继续有效；
- 新的共享周历缓存会在第一次打开对应季度时创建；
- 静态资源版本升级为 `v=1.16.1`，升级后建议强制刷新浏览器。
