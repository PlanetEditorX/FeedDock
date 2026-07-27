# FeedDock 1.17.9 媒体去重、孤儿元数据清理与在线更新

## 下载前媒体去重

FeedDock 在调用 qBittorrent 前，会把任务保存路径从 qBittorrent 路径映射到 FeedDock 本地媒体挂载路径，并在该目录内检查目标视频：

1. 精确匹配规范命名后的文件名；
2. 启用“文件已下载自动跳过”时，再使用 `SxxExx` 集数标记作保守匹配；
3. 最多扫描两级子目录和 5000 个文件；
4. 命中后把条目标记为“已跳过”，不会调用 qBittorrent。

精确目标文件检查属于安全保护，即使旧配置中“自动跳过”关闭也会执行；开关控制较宽松的集数标记匹配。

## 无视频时清理 NFO 与图片

自动或手动刷新订阅时，FeedDock 会检查该订阅已经完成且曾刮削的媒体目录。如果目标季目录已经没有视频文件，会删除 FeedDock 生成的：

- `season.nfo`；
- 与剧集同名的 `.nfo`；
- 季海报。

如果整个剧集或电影目录都没有任何视频，还会删除：

- `tvshow.nfo` / `movie.nfo`；
- `poster.*`、`fanart.*`、`season*-poster.*`；
- `.feeddock-scrape.json`。

不会删除视频、字幕或任意其它用户文件。清理范围受媒体根目录限制，并优先依据 FeedDock 刮削清单。即使 RSS 总开关关闭，手动检查订阅也会先执行本地清理，再跳过网络请求。

## 静态版本清单

版本检查优先读取固定 URL 的 `update.json`：

```json
{
  "version": "1.17.9",
  "release_url": "https://github.com/planeteditorx/feeddock/releases/tag/v1.17.9",
  "published_at": "2026-07-27T00:00:00Z",
  "image": "ghcr.io/planeteditorx/feeddock:latest"
}
```

发布新版本时只需更新并发布该文件。FeedDock 会：

- 缓存版本清单；
- 使用 ETag 或 Last-Modified 条件请求；
- 默认 6 小时内直接使用缓存；
- 清单不可用时使用旧缓存；
- 只有没有任何清单缓存时，才调用 GitHub Release API；
- GitHub API 备用检查每天最多一次。

可配置：

```dotenv
UPDATE_MANIFEST_URLS=https://cdn.jsdelivr.net/gh/planeteditorx/feeddock@main/update.json,https://raw.githubusercontent.com/planeteditorx/feeddock/main/update.json
UPDATE_CHECK_CACHE_HOURS=6
```

## 在线更新

网页会显示“在线更新”或“配置在线更新”。真正替换 Docker 镜像需要 Watchtower HTTP API：

```dotenv
WATCHTOWER_URL=http://watchtower:8080
WATCHTOWER_TOKEN=至少32位随机字符串
```

未配置 Watchtower 时，FeedDock 仍能检查版本、显示最新版本和打开发布说明，但不会直接修改正在运行的容器。
