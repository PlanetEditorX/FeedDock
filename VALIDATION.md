# FeedDock 1.17.2 验证报告

验证日期：2026-07-27

## 功能验证

已验证以下行为：

- 新建订阅提交成功后，后台只刷新该订阅一次；
- 停用的新订阅不会发起 RSS 请求，并记录跳过日志；
- 点击“刷新全部订阅”前显示“是否刷新全部订阅？”确认框；
- 手动刷新记录开始、逐订阅检查和最终汇总；
- 下载器推送记录准备、重试、成功、最终失败；
- 达到并发限制时记录等待并发空位；
- 启用统一下载时间时记录等待定时推送；
- 目标文件已存在时记录跳过推送；
- 网页日志和文件日志同时获得 RSS/下载器日志；
- 推送日志不包含完整 magnet、Torrent URL 或 RSS 私密参数；
- 日志页面不再显示“500 错误可按提示中的请求编号定位”。

## 自动化测试

```text
Ran 143 tests
OK
```

其中新增覆盖：

- 创建订阅后调度首次刷新；
- 首次刷新解析 RSS 并推送 qBittorrent；
- 推送成功日志；
- 日志脱敏；
- 刷新确认弹窗；
- 500 提示移除；
- 发布文件版本与静态资源缓存参数。

## 静态检查

- `python -m compileall -q app tests`：通过；
- 所有 `app/static/*.js` 执行 `node --check`：通过；
- `docker-compose.yml`：YAML 解析通过；
- `docker-compose.fnos.yml`：YAML 解析通过；
- `.github/workflows/docker-publish.yml`：YAML 解析通过；
- `index.html`：126 个唯一 ID；
- `login.html`：3 个唯一 ID；
- `change-password.html`：7 个唯一 ID；
- 运行版本：`1.17.2`；
- 静态资源缓存参数：`v=1.17.2`。

## 旧数据库兼容

使用 FeedDock 1.17.1 创建 SQLite 数据库和订阅，再由 1.17.2 执行 `ensure_schema()`：

```text
migration ok 1 migration demo
```

本次不增加数据库字段，历史订阅和启用状态保持完整。

## 外部服务边界

当前环境没有 Docker CLI，也没有可连接的真实 qBittorrent、Mikan、ANI.BT 或 Anime Garden 服务，因此未执行真实容器构建及外部端到端下载。

qBittorrent 推送行为通过适配器模拟验证，覆盖 Web API 成功、失败重试、并发等待和日志输出。
