# FeedDock 1.17.7 媒体路径映射与单订阅刮削

## 问题原因

qBittorrent 返回的保存目录属于 **qBittorrent 所在环境**。在飞牛 OS 上，它可能是：

```text
/vol2/1000/影视/番剧名称 (2026)/Season 01
```

但 FeedDock 容器通常将同一宿主机目录挂载为：

```text
/media/番剧名称 (2026)/Season 01
```

1.17.6 及更早版本错误地要求两个路径字符串完全相同，因此即使宿主机目录真实存在，FeedDock 容器仍会报告“下载目录不存在”。

## 1.17.7 的映射规则

配置：

```text
qBittorrent 下载根目录：/vol2/1000/影视
FeedDock 本地媒体挂载目录：/media
```

条目保存路径：

```text
/vol2/1000/影视/感谢对战。～大小姐才不玩格斗游戏～ (2026)/Season 01
```

FeedDock 会保留相对部分并映射为：

```text
/media/感谢对战。～大小姐才不玩格斗游戏～ (2026)/Season 01
```

映射后的路径仍必须位于 FeedDock 本地媒体挂载根目录内，避免通过路径模板写入容器其他位置。

## 飞牛 Compose 示例

```yaml
services:
  feeddock:
    environment:
      DOWNLOAD_PATH: "/vol2/1000/影视"
      MEDIA_LOCAL_ROOT: "/media"
    volumes:
      - "/vol2/1000/影视:/media"
```

如果 qBittorrent 也在 Docker 中，推荐两个容器都挂载为 `/media`；如果 qBittorrent 使用宿主机路径或另一容器路径，则分别填写实际路径即可。

## 单订阅刮削

每张订阅卡片新增“刮削”按钮。点击后只处理该订阅中 `completed_at` 已存在的下载条目：

1. 必要时同步外部元数据；
2. 映射 qBittorrent 保存路径到 FeedDock 本地路径；
3. 写入 `tvshow.nfo`、`season.nfo`、剧集同名 NFO；
4. 写入或复用海报和背景图；
5. 更新条目刮削状态并记录系统日志。

如果订阅没有已完成条目，接口会返回明确提示，不会启动空任务。

## 升级迁移

旧版本曾把 `media_local_root` 强制覆盖成 qBittorrent 下载路径。1.17.7 首次启动时，如果检测到该旧值仍与 qBittorrent 根目录相同，并且 Compose 配置了不同的 `MEDIA_LOCAL_ROOT`，会自动恢复 Compose 中的本地挂载路径。
