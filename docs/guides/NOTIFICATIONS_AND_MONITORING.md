# FeedDock 通知与订阅健康监控

适用版本：1.12.0+

## 1. 事件类型

| 事件代码 | UI 名称 | 触发时机 |
|---|---|---|
| `download_started` | 开始下载 | qBittorrent 接受任务后 |
| `download_completed` | 下载完成 | 首次检测到任务 100% 完成 |
| `missing_episodes` | 发现遗漏 | 缺失集合改变，且缺失不超过 10 集 |
| `subscription_completed` | 订阅完结 | 所有预计整数集完成并自动停用 |
| `rss_error` | RSS 或推送错误 | 主备 RSS 均失败，或 qBittorrent 拒绝任务 |
| `stale_subscription` | 长期未更新 | 连续指定天数没有新的匹配条目 |

## 2. 通知渠道

### Telegram

请求：

```text
POST https://api.telegram.org/bot{TOKEN}/sendMessage
```

正文由标题和事件消息组成。Chat ID 可为用户、群组或频道 ID，具体权限由 Telegram Bot 配置决定。

### Bark

请求地址支持两种配置方式：

```text
http://主机:端口
http://主机:端口/push
```

发送前会统一归一化为一个 `/push` 端点，不会再出现 `/push/push`。未启用加密时，JSON 字段为 `title`、`body`、`device_key` 和固定分组 `FeedDock`。Device Key 放在 JSON 请求体中，不拼接到 URL，避免反向代理访问日志泄露密钥。

#### Bark 推送加密

FeedDock 可按 Bark App 的官方选项手动选择：

- 算法：`AES128`、`AES192`、`AES256`；
- 模式：`CBC`、`ECB`、`GCM`；
- 填充：`pkcs7`、`noPadding`；
- Key 长度分别为 16、24、32 个 ASCII 字符。

先在 Bark App 首页的“推送加密”中设置完全相同的算法、模式、填充和 Key，再在 FeedDock 中启用加密。FeedDock 会把标题、正文、分组、图标和图片序列化为 JSON 后加密，只向 Bark 服务发送 `device_key`、`ciphertext`，以及 CBC/GCM 所需的 `iv`。CBC/GCM 每次推送都会生成新的随机 IV；请求中的 IV 会覆盖 Bark App 内保存的 IV。ECB 不使用 IV。

通常建议选择 `CBC + pkcs7` 或 `GCM + pkcs7`。`CBC/ECB + noPadding` 只有在完整 JSON 字节长度恰好为 16 的倍数时才能发送，否则测试或实际推送会返回明确错误。

### Webhook

Webhook 接收完整结构化事件，适合接入 Home Assistant、n8n、Node-RED、飞书/企业微信转发服务或自建自动化系统。

自定义请求头会与 `Content-Type: application/json` 合并。请求头输入必须是 JSON 对象，所有值会转为字符串。


## 3. 通知模板与预览

标题和正文可分别配置模板。页面中的“预览模板”调用服务端渲染逻辑，因此预览结果与 Telegram、Bark 和 Webhook 实际收到的内容一致。

可用变量：

- `{event}`、`{event_label}`；
- `{title}`、`{message}`；
- `{subscription_name}`、`{subscription_id}`；
- `{item_title}`、`{item_episode}`、`{item_status}`；
- `{timestamp}`。

模板只允许上述平面变量，不支持属性访问、数组索引、格式说明或类型转换。默认标题模板为 `{title}`，默认正文模板为 `{message}`，升级后保持原有通知内容不变。

## 4. 密钥行为

- 设置读取接口只返回 `*_configured`；
- 密钥输入留空表示保留；
- 勾选对应“清除”才删除；
- 小眼睛按钮通过管理员保护接口读取原文；
- Webhook 地址可能包含签名参数，因此也按密钥处理；
- 设置、测试响应、WARNING/DEBUG 日志都会隐藏 Token、Device Key、Bark 加密 Key、Webhook 地址和请求头值。

## 5. 完成状态

每个 FeedItem 在推送前写入唯一 qBittorrent Tag：

```text
feeddock-item-{item_id}
```

完成检查器每 2 分钟按 Tag 查询任务。即使 `rename_enabled=false`，仍会：

- 获取任务进度；
- 记录 torrent hash；
- 设置 `completed_at`；
- 触发一次下载完成通知；
- 参与整季完成判断。

未开启规范命名时不会调用重命名 API。

## 6. 完结自动停用

条件全部满足才执行：

1. `auto_disable_when_complete=true`；
2. `total_episodes > 0`；
3. 第 `1..total_episodes` 集都有完成时间；
4. 集数是整数。

执行结果：

- `subscription.enabled=false`；
- 写入 `completion_notified_at`；
- 添加 INFO 系统日志；
- 可选发送 `subscription_completed`。

限制：只统计 FeedDock 数据库中、由 qBittorrent 确认完成的任务。已有但未被 FeedDock 管理的本地文件不会自动计入。修改总集数或重新开启完结自动停用时，会清空旧完结去重状态并按新条件重新判断。

## 7. 长期未更新

`stale_days=0` 时关闭。

活跃时间在以下条件满足时更新：

- RSS 成功读取；
- 出现数据库中尚不存在的新条目；
- 该条目通过包含、排除、播出日期和总集数边界检查。

只有被“只下载最新集”跳过的旧条目也算 RSS 活跃，因为它说明源仍在更新。被排除或超出总集数的条目不算活跃。

达到阈值后只通知一次。下一次发现新匹配条目会清空 `last_stale_notified_at`。旧数据库没有历史活跃时间时，会先使用最近检查时间作为兼容基准，避免升级后立即产生大批停更告警。

## 8. 遗漏检测

遗漏集合按预计总集数 `1..total_episodes` 计算。以下状态视为已跟踪：

- `scheduled`；
- `queued`。

缺失签名示例：

```text
2,5,8
```

签名没有变化时不重复通知。缺失超过 10 集通常意味着番剧仍在播出、总集数刚同步或规则配置不完整，因此只在订阅页面显示，不主动发送。

## 9. 失败处理

- 启用通知中心时必须至少选择一个事件并启用一个渠道；
- 每个渠道独立尝试；
- 失败渠道写入一条已脱敏的 WARNING 日志；
- 其他渠道仍继续；
- RSS 和下载事务不会因通知失败而失败；
- 当前版本不做自动重试，避免同步流程长期阻塞。

后续若增加重试，建议使用独立 `notification_deliveries` 表和后台任务，而不是在 RSS 事务中循环重试。

## 10. Webhook 示例

```bash
curl -X POST https://example.test/hooks/feeddock \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer your-token' \
  -d '{
    "event":"download_completed",
    "title":"下载完成：示例番剧",
    "message":"第 1 集下载完成。",
    "subscription":{"id":1,"name":"示例番剧"},
    "item":{"id":100,"episode":"1"},
    "details":{"progress":100},
    "timestamp":"2026-07-27T00:00:00+00:00"
  }'
```

## 11. 排障

1. 先点击“保存并测试”；
2. 检查“通知设置”顶部是否显示可用渠道；
3. 查看系统日志中的 `通知发送部分失败`；
4. 使用 DEBUG 日志查看异常类型，密钥仍会被隐藏；
5. 代理环境中确认 Telegram/Bark/Webhook 域名未被错误加入 `NO_PROXY`；
6. 自建 Bark 或 Webhook 使用内部地址时，把该主机加入 `NO_PROXY`。
