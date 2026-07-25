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

v1.6.0 起，首页使用季度目录，而不是发布条目混合搜索：

1. 打开 **Mikan 番剧目录**。
2. 选择年份。
3. 选择冬、春、夏或秋。
4. 可选填写标题筛选词。
5. 点击“加载番剧”。
6. 页面按星期展示封面和标题。
7. 点击某一番剧。
8. 弹窗会列出字幕组名称和对应 RSS。
9. 点击“订阅”将该 RSS 带入订阅表单。
10. 配置过滤、集数和路径，预览后保存。

Mikan 请求只会在点击按钮时发起。默认 Compose 中的来源设置是：

```yaml
MIKAN_BASE_URL: "https://mikanime.tv"
MIKAN_FALLBACK_URLS: "https://mikanani.me,https://mikanani.kas.pub"
```

若主域名在当前网络不可访问，会尝试备用域名。修改来源地址不会影响已有数据库和订阅。

## 五、更新

FeedDock 不会自动检查更新。需要时手动点击顶部“检查更新”。

GitHub Actions 在镜像构建成功后，会根据 `VERSION` 创建对应 Git 标签和 Release。例如版本为 `1.6.0` 时发布 `v1.6.0`。

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
