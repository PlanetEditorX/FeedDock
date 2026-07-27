# FeedDock 1.17.8 qBittorrent 推送确认

## 推送成功的判断

`/api/v2/torrents/add` 返回 HTTP 200 或 `Ok.` 只代表 qBittorrent 接受请求。FeedDock 会为本次请求增加一个临时 `feeddock-item-*` 标签，再通过任务列表回查真实任务。

只有查到任务名称、状态和 torrent hash 后，条目才进入 `queued`。

## 临时标签生命周期

```text
添加请求
  → 临时标签回查
  → 保存 torrent hash
  → removeTags 从任务移除标签
  → deleteTags 删除标签定义
```

后续重命名、下载完成检查、Tracker 和刮削均使用 hash，不再依赖永久标签。历史标签由后台维护自动清理，详见 [`QBITTORRENT_TEMPORARY_TAGS.md`](QBITTORRENT_TEMPORARY_TAGS.md)。

## HTTP/HTTPS Torrent

FeedDock 使用当前代理设置下载 `.torrent`，校验内容后上传原始字节到 qBittorrent。这样 qBittorrent 不需要自行访问私有 Torrent URL，也不会因为 DNS、代理、证书或 Passkey 问题产生假成功。

## 失败处理

添加接口返回成功但回查不到任务时，条目进入 `error`，下载列表显示“重试下载”。临时标签清理失败不会否定已经确认的任务，会在后台继续重试。

## 日志隐私

日志记录条目 ID、临时关联标识、实际任务名称、状态和 hash，不输出完整 magnet、Torrent URL 或私有站点 Passkey。
