# FeedDock 1.17.10 媒体挂载路径自动修复

## 问题

飞牛宿主机和不同容器看到的路径可能不同：

```text
qBittorrent / 宿主机：/vol2/1000/影视
FeedDock 容器：       /media
```

如果自定义 Compose 只配置了：

```yaml
volumes:
  - "/vol2/1000/影视:/media"
```

但没有显式设置 `MEDIA_LOCAL_ROOT`，旧版本可能把 qBittorrent 的 `/vol2/1000/影视` 保存为 FeedDock 本地路径。FeedDock 随后会在自己的容器中检查 `/vol2/...`，即使宿主机目录真实存在，也会报告目录不存在。

## 1.17.10 行为

- 容器内媒体挂载目录默认使用 `/media`；
- `MEDIA_LOCAL_ROOT` 未填写时也不会再退回 qBittorrent 路径；
- 检测到数据库中的本地路径与 qBittorrent 根目录同为 `/vol*`、`/mnt*`、`/share*` 等宿主机路径时，会自动恢复为 `/media`；
- 已经完成的 1.17.7 迁移不会阻止本次修复；
- 运行时还有一层自修复，即使迁移记录异常，刮削仍使用正确的容器路径；
- 裸机或测试环境若确实让两个进程使用相同普通路径，不会被强制改成 `/media`。

## 推荐 Compose

```yaml
environment:
  DOWNLOAD_PATH: "/vol2/1000/影视"
  MEDIA_LOCAL_ROOT: "/media"
volumes:
  - "/vol2/1000/影视:/media"
```

若 qBittorrent 配置是在网页中保存，Compose 中的 `DOWNLOAD_PATH` 可保持默认；关键是 FeedDock 容器内挂载点必须是 `/media`。

升级后，在“设置 → 刮削设置”中应看到：

```text
qBittorrent 根目录 /vol2/1000/影视 → FeedDock /media
```
