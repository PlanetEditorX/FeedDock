# FeedDock 1.17.7 本地媒体库刮削

## 为什么 1.17.4 没有文件

1.17.4 的“自动刮削”只调用元数据服务，并将结果保存在 SQLite 的订阅字段中。旧 `app/scraper.py` 明确返回“已移除本地 NFO/图片刮削”，因此媒体目录不会出现 NFO、海报或背景图。

1.17.5 恢复了受媒体根目录约束的本地旁车文件写入；1.17.7 增加 qBittorrent 路径到 FeedDock 本地挂载路径的映射。

## 路径要求

qBittorrent 和 FeedDock 必须访问同一个宿主机目录，但容器内路径可以不同。例如：

```yaml
qBittorrent 下载根目录：/vol2/1000/影视
FeedDock volumes：/vol2/1000/影视:/media
FeedDock 本地媒体挂载目录：/media
```

FeedDock 会保留 qBittorrent 根目录下面的相对路径并拼接到 `/media`。例如 `/vol2/1000/影视/Show/Season 01` 会映射为 `/media/Show/Season 01`。映射后仍执行根目录越界保护。

## 自动流程

```text
qBittorrent 下载完成
→ 同步外部元数据（如到期）
→ 定位媒体目录和实际视频文件
→ 写入剧集/电影 NFO
→ 下载或复用海报与背景图
→ 记录 .feeddock-scrape.json
→ 更新条目刮削状态与日志
```

## 历史任务补写

升级后选择：

```text
刷新 → 刮削已完成媒体
```

任务会遍历 FeedDock 中所有带 `completed_at` 的下载条目。清理过页面历史的条目仍保留去重记录并可以补写。

每张订阅卡片也提供“刮削”按钮，只处理当前订阅的已完成条目。

## 媒体服务器扫描

NFO 与图片落盘后，飞牛影视、Emby、Jellyfin、Kodi 等仍需扫描媒体目录。FeedDock 当前不会直接调用媒体服务器的刷新 API，以避免把某一种媒体服务器变成强依赖。

## 日志

成功日志包含订阅 ID、条目 ID、媒体目录和生成文件列表；失败日志会明确指出路径不存在、目录越界、图片请求失败或文件写入失败。日志不会包含 RSS Passkey、磁力链接或下载器密码。

## 目录命名

默认目录采用 `名称 (年份)`，例如 `金牌得主 (2025)/Season 02`。TMDB、Bangumi 和 AniList ID 写入 NFO，不附加到目录名。已有目录不会自动重命名。
