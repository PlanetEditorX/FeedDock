# FeedDock DEBUG 日志指南

## 日志级别

### INFO

记录：

- 启动；
- 订阅创建成功；
- RSS 检查结果；
- qBittorrent 下载与命名检查；
- WARNING 和 ERROR。

### DEBUG

在 INFO 基础上增加：

- 每个 API 请求；
- HTTP 状态码；
- 请求耗时；
- 查询参数；
- 订阅保存阶段；
- RSS 单订阅开始处理信息。

## 500 请求编号

每个请求都有 `X-Request-ID`。订阅保存失败时页面显示：

```text
保存订阅失败 [请求编号]：异常类型: 异常消息
```

日志中同一编号会对应完整 traceback。

## 三个查看位置

1. FeedDock 网页“系统日志与调试”；
2. `/data/logs/feeddock.log`；
3. `docker logs feeddock`。

## 日志脱敏

以下字段自动替换为 `***`：

- password/passwd；
- token；
- api_key；
- secret；
- authorization；
- cookie。

## 日志轮转

- 当前文件最大 5 MB；
- 保留 5 个历史文件；
- UTF-8 编码。
