# FeedDock 1.8.0 验证范围

自动化测试覆盖：

- 首次登录与强制修改密码；
- 修改密码后旧会话失效；
- Mikan 独立图片卡片在星期区块外时按 `bangumi_id` 回填；
- 相对封面路径使用 HTTP 最终响应域名；
- 每星期隐藏记录持久化；
- 保存某星期不会清空其他星期；
- 普通模式移除隐藏番剧；
- 编辑模式返回全部番剧并标记 `hidden=true`；
- 清空单星期隐藏设置；
- RSS/Atom 解析、规则过滤和集数偏移；
- Python 编译、JavaScript 语法、Compose 和 Actions YAML。
