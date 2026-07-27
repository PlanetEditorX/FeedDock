# FeedDock 1.17.3 qBittorrent 推送确认

## 问题根因

旧版本把 `/api/v2/torrents/add` 返回 HTTP 200 和 `Ok.` 直接视为推送成功。该响应只说明 qBittorrent 接受了添加请求；当参数是远程 `.torrent` URL 时，qBittorrent 后续获取种子文件失败，任务可能不会出现在列表中。

## 新的推送流程

### Magnet

```text
提交 magnet 和唯一任务标签
  → qBittorrent 接受请求
  → FeedDock 按标签轮询 /api/v2/torrents/info
  → 查到任务名称、状态和哈希后才记为成功
```

### HTTP/HTTPS Torrent

```text
FeedDock 使用当前代理设置下载 .torrent
  → 校验响应大小和 BitTorrent 文件结构
  → 把原始字节上传到 qBittorrent torrents/add
  → 按唯一标签回查任务
  → 查到任务后才记为成功
```

这样 qBittorrent 不需要自行访问私有 Torrent URL，也不会因为 DNS、代理、证书或私有站点参数问题产生“接口成功但没有任务”的假成功。

## 日志

成功日志改为：

```text
qBittorrent 已确认任务
```

详细信息包含任务标签、qBittorrent 返回的实际任务名称、状态和任务哈希，但不会记录完整 magnet、Torrent URL 或 passkey。

如果添加接口返回成功但任务回查失败，条目会进入 `error`：

```text
qBittorrent 添加接口返回成功，但未在任务列表中找到新任务
```

可在下载列表点击“重试下载”。

## 历史假成功记录

后台下载完成检查会重新按任务标签查找旧的 `queued` 条目。记录超过两分钟仍找不到任务时，会自动改为错误状态并显示“重试下载”，避免永远停留在等待状态。

## 刷新行为

“刷新全部订阅”恢复为点击后直接执行，不再显示二次确认。
