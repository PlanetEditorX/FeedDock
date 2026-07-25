# FeedDock

FeedDock 是一个自托管 RSS 规则处理与 qBittorrent 自动化服务。它可以浏览 Mikan 番剧季度目录、选择字幕组 RSS，并按规则轮询、过滤、识别集数、去重后推送到 qBittorrent。

> 本项目不提供、存储或分发媒体资源。请只处理你有权访问和下载的内容，并遵守所在地区法律、源站规则及版权要求。

当前版本：`1.6.1`

## v1.6.1

- 修复 Mikan 详情页含无名称 `meta` 标签时触发的 `NoneType.lower` 错误。
- 支持当前详情页的 `div.subgroup-text` 字幕组结构，包括纯数字 ID。
- 扩展季度目录封面解析：`data-src`、懒加载属性、`srcset` 和 CSS `background-image`。
- 新增同源封面代理，解决飞牛浏览器直接加载 Mikan 封面失败的问题。
- 封面代理失败时自动回退到原始图片地址，再失败才显示文字占位。
- 保留年份、季度、星期目录和字幕组 RSS 一键订阅流程。

## 主要功能

- 应用内登录，首次登录后强制修改初始密码。
- Mikan 年份、季度、星期番剧目录。
- 字幕组 RSS 选择和订阅表单预填。
- RSS / Atom 定时轮询、手动刷新、指纹去重和错误重试。
- 主 RSS 失败或没有条目时自动使用备用 RSS。
- 包含、排除、全局排除及自定义集数正则。
- 集数偏移、总集数、遗漏检测和只下载最新集。
- qBittorrent 可位于同机、局域网其他设备或远程地址。
- qBittorrent 配置可直接在网页保存和测试。
- GitHub Release 手动检查与可选 Watchtower 更新。
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
docker compose up -d --build
```

打开：

```text
http://服务器IP:7789
```

首次管理员由以下变量创建：

```dotenv
ADMIN_USER=admin
ADMIN_PASSWORD=change-this-to-a-strong-password
```

首次登录后必须修改密码。新密码以哈希形式保存在 `data/feeddock.db`，容器重启不会被 Compose 中的初始密码覆盖。

## Mikan 番剧目录

登录后在首页找到 **Mikan 番剧目录**：

1. 选择年份，例如 `2026`。
2. 选择季度：冬、春、夏或秋。
3. 可选输入标题关键词。
4. 点击“加载番剧”。
5. 页面按星期分组显示番剧封面和标题。
6. 点击番剧卡片，读取字幕组列表。
7. 每个字幕组会显示专用 RSS：

```text
/RSS/Bangumi?bangumiId=<番剧ID>&subgroupid=<字幕组ID>
```

8. 点击“复制 RSS”只复制地址；点击“订阅”会把名称、RSS 和来源名称带入订阅表单。
9. 检查匹配规则、集数和下载路径，预览后再保存。

页面不会自动请求 Mikan。只有点击“加载番剧”或点击番剧读取字幕组时才访问站点。

默认来源地址：

```dotenv
MIKAN_BASE_URL=https://mikanime.tv
MIKAN_FALLBACK_URLS=https://mikanani.me,https://mikanani.kas.pub
```

若主地址不可访问，会依次尝试备用地址。FeedDock 只读取公开页面和 RSS，不代理或存储媒体资源。番剧封面会由 FeedDock 临时转发给已登录的管理页面，不写入数据库，也不会长期缓存到磁盘。

若旧页面仍显示无封面或旧错误，请先确认镜像版本为 `1.6.1`，再使用 `Ctrl + F5` 强制刷新浏览器缓存。

## qBittorrent

登录后在“qBittorrent 下载器”中填写：

- WebUI 地址
- 用户名
- 密码
- 分类
- 下载保存根目录

`DOWNLOAD_PATH` 及订阅的自定义下载路径必须是 qBittorrent 所在主机或容器能够识别的路径。FeedDock 只把路径发送给 qBittorrent。

## 高级订阅规则

订阅支持：

- 参考标题、TMDB 标题、BgmUrl、日期和季。
- 主 RSS 与备用 RSS。
- 普通文字或正则包含、排除和全局排除。
- 自定义集数正则和捕获组。
- 集数偏移、小数集数和总集数限制。
- 保存路径模板或 qBittorrent 可识别的绝对路径。
- 遗漏检测、只下载最新集和启停控制。

默认路径模板：

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

保存前使用“预览规则和路径”确认匹配结果、集数和最终目录。

## 更新功能

更新检查不会自动执行。只有点击页面顶部“检查更新”时才访问 GitHub Release API。

如果 GitHub 返回限流，可在 Compose 中可选设置只读 Token：

```yaml
UPDATE_GITHUB_TOKEN: "你的 Fine-grained token"
```

不要把 Token 提交到公开仓库。

没有 Watchtower 时，在飞牛中拉取最新镜像并重新部署 Compose 即可。宿主机 `data` 目录不会丢失。

## GitHub Actions

`.github/workflows/docker-publish.yml` 会：

1. 运行测试和语法检查。
2. 构建 `linux/amd64` 与 `linux/arm64` 镜像。
3. 推送到 GHCR。
4. 根据 `VERSION` 创建 Git 标签和 GitHub Release。

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
{"status":"ok","version":"1.6.1"}
```

建议备份：

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
