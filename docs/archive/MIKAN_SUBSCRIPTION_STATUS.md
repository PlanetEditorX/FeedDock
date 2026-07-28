# Mikan 番剧目录订阅标识

## 功能行为

Mikan 番剧目录会根据现有订阅的主 RSS 和备用 RSS，识别 URL 查询参数中的 `bangumiId`。匹配成功的番剧卡片显示 `✓ 已订阅`，并增加已订阅卡片样式。

订阅新增、编辑或删除后，管理页重新读取订阅列表时会立即同步当前已打开目录，不需要重新请求 Mikan，也不需要手动点击“读取缓存”。

以下 URL 参数写法均可识别：

```text
?bangumiId=123
?BangumiID=123
?BANGUMIID=123&subgroupid=7
```

空值、非数字、负数、零以及格式错误的 URL 不会被识别为有效订阅。

## 模块划分

### 后端：`app/mikan_subscription.py`

- `extract_mikan_bangumi_id`：从单个 RSS URL 中解析正整数 `bangumiId`。
- `collect_subscribed_mikan_bangumi_ids`：合并主 RSS、备用 RSS，并对番剧 ID 去重。
- `app/main.py` 在返回目录数据时使用该模块标注 `subscribed` 字段。

### 前端：`app/static/mikan-subscription-state.js`

- `extractBangumiId`：浏览器侧 URL 解析。
- `collectSubscribedBangumiIds`：从订阅列表生成去重集合。
- `updateCatalogSubscriptionState`：只修改状态发生变化的目录项，并返回变化数量。

`app/static/app.js` 只负责调用模块和在确有变化时重新渲染目录，避免把可测试的状态逻辑继续堆积在页面主脚本中。

## 数据流程

```text
读取 Mikan 目录
  ↓
后端根据数据库订阅标注 subscribed
  ↓
页面显示“✓ 已订阅”
  ↓
新增/编辑/删除订阅
  ↓
重新读取 /api/subscriptions
  ↓
前端模块更新当前目录状态
  ↓
仅在状态变化时重新渲染
```

## 测试

专用测试位于 `tests/test_mikan_subscription_state.py`，覆盖：

- 查询参数大小写不敏感；
- 主 RSS 与备用 RSS；
- 重复 ID 去重；
- 空值、非数字、零和负数；
- 相对 URL；
- 仅修改实际变化的目录项；
- 第二次同步相同状态时返回零变化，避免无效重绘。

执行完整测试：

```bash
python -m unittest discover -s tests -v
```

执行 JavaScript 语法检查：

```bash
node --check app/static/mikan-subscription-state.js
node --check app/static/app.js
```

## 部署注意事项

该功能最初在 `1.10.1` 中引入，当时同步更新了静态资源 URL，用于绕过浏览器对旧 `app.js` 的缓存。部署后通常无需手动强制刷新；若反向代理额外缓存 HTML，可刷新一次页面或清理代理缓存。

本功能不修改数据库结构，不需要迁移。
