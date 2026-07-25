# FeedDock 飞牛 OS 部署说明

## 1. 数据目录

创建：

```text
/vol1/1000/应用/feeddock/data
```

数据库、Mikan 目录缓存和封面缓存都保存在这里。升级时不要删除。

## 2. 基础部署

使用项目中的 `docker-compose.fnos.yml`。默认端口：

```text
http://飞牛地址:7789
```

首次登录：

```text
admin / password
```

登录后立即修改密码。

## 3. qBittorrent

在 FeedDock 网页中填写：

```text
WebUI 地址：http://host.docker.internal:8080
用户名：你的 qBittorrent 用户名
密码：你的 qBittorrent 密码
下载保存根目录：qBittorrent 能识别的路径
```

若 qBittorrent 在其他设备，填写局域网地址。

## 4. TMDB 与 Bangumi

网页打开“元数据与刮削设置”：

- TMDB Read Access Token：用于搜索和季度总集数；
- Bangumi Token：可留空；
- 元数据语言：建议 `zh-CN`。

保存后，在订阅编辑器中搜索并选择条目。选择时会立即读取详情和总集数。

## 5. 仅使用 Emby 在线刮削

这是推荐方式，不需要给 FeedDock 挂载媒体目录。

1. 选择正确 TMDB 条目。
2. 使用默认目录模板。
3. 打开规范重命名。
4. 在 Emby 中扫描 qBittorrent 下载目录。

最终目录带 `[tmdbid=ID]`，Emby 更容易准确识别。

## 6. 启用本地 NFO/海报刮削

修改 Compose：

```yaml
services:
  feeddock:
    environment:
      DOWNLOAD_PATH: "/media"
      MEDIA_LOCAL_ROOT: "/media"
      EMBY_URL: "http://host.docker.internal:8096"
      EMBY_API_KEY: "你的 Emby API Key"
    volumes:
      - "/vol1/1000/应用/feeddock/data:/data"
      - "/vol2/1000/影视:/media"
```

qBittorrent 也必须把同一宿主机目录挂载为 `/media`。路径不一致会导致 FeedDock 无法安全定位文件。

重新部署后，在订阅中勾选：

```text
允许生成本地 NFO 与图片
```

成功规范化单视频任务后会自动写入 NFO；也可在订阅卡片手动点击“刮削本地文件”。

## 7. 更新

GitHub Actions 构建并发布新镜像后，在飞牛中重新拉取：

```bash
cd /你的/Compose目录
docker compose -f docker-compose.fnos.yml pull
docker compose -f docker-compose.fnos.yml up -d
```

更新后浏览器执行一次强制刷新。数据库迁移为新增字段，不会删除旧数据。

## 8. 故障排查

### TMDB 搜索提示未配置

检查 Read Access Token 是否保存。网页只显示“已配置”，不会返回原文。

### 总集数不正确

确认：

- 媒体类型是否为电视番剧；
- 季编号是否与 TMDB 一致；
- 是否误勾选“锁定总集数”。

### 文件一直 pending

磁力链接尚未获取元数据，FeedDock 每 2 分钟重试。也可点击顶部“规范化文件名”。

### 显示 manual_required

种子中有多个视频文件。FeedDock不会把合集全部改成同一个集数名称，需要人工处理。

### 本地刮削提示路径不在根目录

`DOWNLOAD_PATH` 与 `MEDIA_LOCAL_ROOT` 映射不一致。建议两个容器使用同一个容器内路径 `/media`。

### Emby 没有刷新

检查 Emby 地址、API Key、网络连通性，并点击“通知 Emby 刷新”。
