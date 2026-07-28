# 通知与订阅交互改动

## Bark 修复

- Bark 地址可填写服务根地址或完整 `/push` 地址。
- 发送前统一归一化端点，避免生成 `/push/push`。
- Device Key 继续使用 Bark JSON 字段 `device_key`，不写入 URL，降低代理日志泄密风险。

## 通知模板与预览

- 新增标题模板和正文模板。
- 新增 `POST /api/notifications/preview`，页面预览与实际发送共用同一套服务端渲染逻辑。
- 模板支持事件、订阅和条目相关的平面变量，并校验未知变量及高级格式表达式。

## 交互与文案

- 设置菜单和页面标题统一改为“通知设置”。
- 添加订阅状态下显示“取消添加”；编辑状态下显示“取消编辑”。

## 模块拆分

后端通知逻辑拆分到 `app/notification/`：

- `config.py`：配置持久化与校验；
- `templates.py`：模板变量、校验和渲染；
- `channels.py`：Telegram、Bark、Webhook 渠道适配；
- `service.py`：统一编排、脱敏错误和预览；
- `types.py`：结果值对象。

前端通知设置拆分到 `app/static/modules/notification-settings.js`。旧的 `app/notifications.py` 和 `app/notification_config.py` 保留兼容入口，避免影响现有调用方。

## 测试

执行：

```bash
PYTHONPATH=. pytest -q
```

结果：`178 passed, 15 subtests passed`。
