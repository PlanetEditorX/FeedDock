# FeedDock

FeedDock 是一个自托管 RSS 规则处理与 qBittorrent 自动化服务。它定时读取用户自行添加的 RSS / Atom，按文字或正则规则过滤、识别集数、去重后推送到 qBittorrent，并通过中文 Web 页面管理订阅、任务、日志与版本更新。

> 本项目不提供、存储或分发任何媒体资源。请只处理你有权访问和下载的内容，并遵守所在地区法律、源站条款及版权要求。

当前版本：`1.5.0`

## v1.5.0

- 新增“搜索并添加番剧”页面区域，只有手动点击搜索时才请求外部站点。
- 内置 Mikan 搜索解析：搜索番剧、打开番剧详情、列出字幕组并生成字幕组专用 RSS。
- Mikan 主地址不可用时可按顺序尝试备用地址；HTML 页面变化时会回退到关键词 RSS 搜索。
- 内置动漫花园搜索解析：生成关键词 RSS、展示最近发布，并可选择某条发布作为规则预览样本。
- 搜索结果只负责预填订阅表单，仍需用户确认匹配、排除、集数和下载路径后保存。
- 新增 `MIKAN_BASE_URL`、`MIKAN_FALLBACK_URLS`、`DMHY_BASE_URL` 环境变量，方便飞牛网络环境切换镜像站。

## 主要功能

- 应用内登录，首次登录后强制修改初始密码。
- RSS / Atom 定时轮询、手动刷新、指纹去重和错误重试。
- Mikan 番剧/字幕组搜索与动漫花园关键词 RSS 搜索，可手动选择后预填订阅。
- 主 RSS 失败或没有条目时自动使用备用 RSS。
- 包含、排除和全局排除均支持普通文字；含正则符号时按正则匹配。
- qBittorrent 可部署在同机、局域网其他设备或远程 HTTPS 地址。
- qBittorrent 配置可直接在网页保存和测试。
- GitHub Release 手动检查与可选 Watchtower 一键更新。
- GitHub Actions 自动测试、构建多架构 GHCR 镜像并发布 Release。

## 飞牛 OS 部署

飞牛 OS 使用：

- `docker-compose.fnos.yml`
- `FNOS_DEPLOY.md`

默认镜像：

```text
ghcr.io/planeteditorx/feeddock:latest
```

默认数据目录：

```text
/vol1/1000/应用/feeddock/data
```

同一台飞牛上的 qBittorrent 地址通常填写：

```text
http://host.docker.internal:8080
```

详细步骤见 [FNOS_DEPLOY.md](FNOS_DEPLOY.md)。

## 通用 Docker Compose 部署

```bash
cp .env.example .env
```

至少修改：

```dotenv
ADMIN_PASSWORD=首次登录使用的强密码
QBIT_URL=http://192.168.1.20:8080
QBIT_USERNAME=admin
QBIT_PASSWORD=你的qBittorrent密码
DOWNLOAD_PATH=/downloads/rss
```

启动：

```bash
docker compose up -d --build
```

打开：

```text
http://服务器IP:7789
```

附带 qBittorrent：

```bash
docker compose --profile with-qbit up -d --build
```

## 登录与密码

初次启动由以下环境变量创建管理员：

```dotenv
ADMIN_USER=admin
ADMIN_PASSWORD=change-this-to-a-strong-password
```

首次登录后必须修改密码。新密码以哈希形式保存在：

```text
data/feeddock.db
```

后续重启或重新部署不会用 Compose 中的初始密码覆盖数据库密码。

## Mikan 与动漫花园搜索

登录后在首页找到“搜索并添加番剧”：

1. 选择 `Mikan + 动漫花园`、`仅 Mikan` 或 `仅动漫花园`。
2. 输入番剧关键词并点击“搜索”。页面不会在后台自动搜索。
3. Mikan 结果先选择番剧，再选择字幕组；系统生成：

```text
/RSS/Bangumi?bangumiId=<番剧ID>&subgroupid=<字幕组ID>
```

4. 动漫花园结果会提供关键词 RSS，并列出最近发布；可选择某条标题带入规则预览。
5. 点击“选择并填入”后，检查订阅表单中的名称、RSS、匹配规则、集数和路径，再手动保存。

默认来源：

```dotenv
MIKAN_BASE_URL=https://mikanime.tv
MIKAN_FALLBACK_URLS=https://mikanani.me,https://mikanani.kas.pub
DMHY_BASE_URL=https://share.dmhy.org
```

若飞牛所在网络无法访问某个域名，可以只修改 Compose 中对应地址。FeedDock 不会代理、存储或提供站点资源；它只读取公开页面/RSS，并将用户选择的订阅配置保存到本地。

## qBittorrent

登录后在首页的“qBittorrent 下载器”区域填写：

- WebUI 地址
- 用户名
- 密码
- 分类
- 下载保存根目录

`DOWNLOAD_PATH` 和每个订阅的自定义下载路径，都是 qBittorrent 所在主机或容器能够识别的路径。FeedDock 只将路径发送给 qBittorrent，不直接读取该目录。

## 高级订阅配置

### 基础信息

- 名称：FeedDock 中显示的订阅名称。
- 参考标题、TMDB 标题、BgmUrl：用于记录元数据和路径变量，不会自动调用 TMDB。
- 日期：条目发布日期早于该日期时跳过。
- 季：可用于路径变量 `{season}`。

### RSS

- `rss_url` 是主 RSS。
- 主 RSS 请求失败或返回空列表时，才尝试备用 RSS。
- 两个 RSS 的条目仍通过指纹去重。

### 匹配和排除

规则以逗号、中文逗号或换行分隔：

```text
720
\d-\d
合集
特别篇
```

- 普通文字按不区分大小写的包含关系匹配。
- 包含 `\d`、`[]`、`()`、`*`、`+` 等正则符号时按正则匹配。
- 排除优先于匹配。
- 全局排除应用到所有订阅。
- “匹配”留空或填写 `无` 表示不限制。

### 集数

示例：

```text
自定义集数正则：\d+(\.5)?
捕获组：0
集数偏移：-13
总集数：9
```

- 捕获组 `0` 表示使用整个正则匹配结果。
- 捕获组 `1` 表示使用第一个括号捕获结果。
- 偏移在识别后应用，例如 `14 - 13 = 1`。
- 支持 `13.5` 这类特别集。
- 总集数为 `0` 表示未知，不执行上限过滤。

### 下载路径

默认模板：

```text
{base}/{subscription}/Season {season}
```

可用变量：

```text
{base}
{subscription}
{reference_title}
{tmdb_title}
{season}
{episode}
{year}
```

自定义下载路径可直接填写 qBittorrent 识别的绝对路径，例如：

```text
/vol2/1000/影视/金牌得主 (2025)/Season 2
```

保存前点击“预览规则和路径”，页面会显示匹配结果、原始集数、偏移后集数和最终下载位置。

### 下载策略

- 遗漏检测：根据已成功推送的整数集数和总集数显示缺失列表。
- 只下载最新集：一次刷新发现多条新匹配记录时，只推送集数最高的一条；其他条目记录为跳过。
- 启用订阅：关闭后调度器不再轮询该订阅。

## 更新功能

更新检查不会自动执行。只有点击页面顶部“检查更新”时，才访问：

```text
https://api.github.com/repos/planeteditorx/feeddock/releases/latest
```

GitHub 对 REST API 有访问限额。若飞牛所在公网 IP 与其他用户共享限额，可在 Compose 中可选设置 GitHub Token：

```yaml
UPDATE_GITHUB_TOKEN: "你的Fine-grained token"
```

公开仓库只读取 Release 时，Token 不需要仓库写权限。不要把 Token 提交到公开仓库。

没有 Watchtower 时，手动升级：

```bash
docker compose pull feeddock
docker compose up -d --no-build --remove-orphans
```

## GitHub Actions

`.github/workflows/docker-publish.yml` 会：

1. 运行 Python 测试和 JavaScript/YAML 校验。
2. 构建 `linux/amd64` 和 `linux/arm64` 镜像。
3. 推送到 GHCR。
4. 根据 `VERSION` 创建对应 Git 标签和 GitHub Release。

发布新版本只需修改 `VERSION` 后提交到 `main`。

## 运维

查看日志：

```bash
docker compose logs -f feeddock
```

健康检查：

```bash
curl http://127.0.0.1:7789/health
```

返回示例：

```json
{"status":"ok","version":"1.5.0"}
```

需要备份：

```text
data/feeddock.db
data/session-secret.key
.env
```

## 测试

```bash
python -m unittest discover -s tests -v
node --check app/static/app.js
```

## License

MIT
