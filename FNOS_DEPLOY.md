# FeedDock 在飞牛 OS（fnOS）上的部署

本文按以下目录部署：

```text
/vol1/1000/应用/feeddock
```

使用镜像：

```text
ghcr.io/planeteditorx/feeddock:latest
```

## 一、目录

确认以下目录存在：

```text
/vol1/1000/应用/feeddock
/vol1/1000/应用/feeddock/data
```

`data` 保存管理员密码、会话密钥、订阅、下载记录和应用数据库。升级或重建容器时不要删除。

## 二、部署 Compose

在飞牛 Docker 的 Compose 项目中使用 `docker-compose.fnos.yml`。

默认值：

- 端口：`7789`
- 首次用户名：`admin`
- 首次密码：`password`
- qBittorrent：先留空
- Mikan 主地址：`https://mikanime.tv`

部署完成后打开：

```text
http://飞牛IP:7789
```

第一次使用 `admin / password` 登录，随后必须设置新密码。新密码保存在 `/vol1/1000/应用/feeddock/data`，以后重新部署不会恢复成 `password`。

## 三、配置 qBittorrent

登录后在网页的 **qBittorrent 下载器** 中配置。

同一台飞牛 OS：

```text
http://host.docker.internal:8080
```

局域网其他设备：

```text
http://192.168.1.20:8080
```

填写用户名、密码、分类和 qBittorrent 能识别的下载路径，然后点击“保存并测试连接”。配置会写入：

```text
/vol1/1000/应用/feeddock/data/feeddock.db
```

## 四、浏览并订阅 Mikan 番剧

首页的 Mikan 目录采用持久缓存：

1. 选择年份和季度。
2. 点击“读取缓存”。第一次没有缓存时会访问一次 Mikan。
3. 以后重复加载和标题搜索都只读取 `/vol1/1000/应用/feeddock/data` 中的缓存。
4. 已浏览季度默认每 6 小时后台更新一次。
5. 需要马上更新时点击“强制更新”。
6. 点击番剧查看字幕组 RSS；同一番剧重复打开使用详情缓存。
7. 字幕组变化时可点击弹窗里的“强制更新字幕组”。

飞牛 Compose 默认配置：

```yaml
MIKAN_BASE_URL: "https://mikanime.tv"
MIKAN_FALLBACK_URLS: "https://mikanani.me,https://mikanani.kas.pub"
MIKAN_CACHE_HOURS: "6"
MIKAN_IMAGE_CACHE_DAYS: "7"
```

季度目录和字幕组详情保存在 `feeddock.db`，封面保存在 `data/mikan-image-cache`。后台只刷新已经浏览过的季度，每轮最多处理少量到期缓存；不会遍历全部年份和所有番剧详情。刷新失败后至少等待 1 小时再尝试，避免连续请求来源站。

修改 `MIKAN_CACHE_HOURS` 后重新部署即可调整刷新间隔。建议不要设置得过短。部署新版本后请执行一次 `Ctrl + F5` 强制刷新页面。

升级到 v1.7.1 后，旧季度缓存会自动刷新一次，以修复旧缓存中的空封面或错误域名。Mikan 的相对图片路径会按最终响应域名拼接；例如页面从 `mikanime.tv` 重定向到 `mikanani.me`，封面也会使用 `mikanani.me/images/...`。

## 五、更新

FeedDock 不会自动检查更新。需要时手动点击顶部“检查更新”。

GitHub Actions 在镜像构建成功后，会根据 `VERSION` 创建对应 Git 标签和 Release。例如版本为 `1.7.1` 时发布 `v1.7.1`。

飞牛升级步骤：

1. 等待 GitHub Actions 构建成功。
2. 在飞牛 Compose 项目中拉取最新镜像。
3. 重新部署项目。
4. 浏览器执行一次强制刷新。

数据位于宿主机 `data` 目录，不会因为容器重建而丢失。

## 六、忘记密码

修改 Compose 中的 `ADMIN_PASSWORD` 不会覆盖数据库密码。若必须完全重置：

1. 停止 FeedDock。
2. 备份 `/vol1/1000/应用/feeddock/data`。
3. 删除其中的 `feeddock.db`。
4. 重新部署。

这会重新使用 `admin / password` 初始化，也会清空订阅和任务记录。

## 按星期隐藏番剧

Mikan 季度目录中，每个星期均有“编辑过滤”按钮。进入编辑模式后勾选不喜欢的番剧并保存，设置会写入现有 `/data/feeddock.db`。刷新页面、强制更新 Mikan 缓存或重建容器后仍然生效；该操作只访问本地数据库，不会增加 Mikan 请求。

