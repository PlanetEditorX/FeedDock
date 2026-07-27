# FeedDock 1.13.0 Git 提交说明

## 推荐提交标题

```text
feat(ui): 重构订阅优先的任务式控制台
```

## 推荐提交正文

```text
- 将默认首页精简为订阅统计、筛选和订阅卡片
- 新增添加、下载、刷新、管理、设置和日志顶部导航
- 为 Mikan、ANI.BT、Anime Garden 和其它 RSS 提供明确添加入口
- 将下载、基础配置、代理、登录、通知、系统和日志拆为独立视图
- 新增订阅批量启动、禁用、删除和所选导出
- 新增 FeedDock JSON 订阅导入、全量导出与冲突更新策略
- 允许管理员在首次初始化后继续从登录设置修改密码
- 增加默认禁用的重启与关闭接口和安全状态提示
- 新增前端 Hash 路由模块及后端管理 API 测试
- 更新 README、飞牛部署、界面说明和验证报告
- 版本升级至 1.13.0
```

## 建议分拆提交

```text
feat(ui): 增加订阅优先导航与独立功能视图
feat(subscriptions): 增加批量管理和 JSON 导入导出
feat(system): 增加安全禁用的服务重启与关闭操作
test(docs): 补齐导航、认证与部署回归测试
```

## 主要文件

```text
app/static/index.html
app/static/styles.css
app/static/navigation.js
app/static/app.js
app/static/change-password.html
app/static/change-password.js
app/main.py
app/schemas.py
app/config.py
app/system_control.py
tests/test_subscription_management.py
tests/test_auth_flow.py
tests/test_deployment_files.py
UI_NAVIGATION.md
README.md
FNOS_DEPLOY.md
VALIDATION.md
```

## 提交命令

```bash
git add \
  VERSION Dockerfile docker-compose.yml docker-compose.fnos.yml \
  .env.example .env.fnos.example .github/workflows/docker-publish.yml \
  app tests README.md UI_NAVIGATION.md FNOS_DEPLOY.md VALIDATION.md GIT_COMMIT.md

git commit -m "feat(ui): 重构订阅优先的任务式控制台" \
  -m "将首页改为订阅列表，补齐任务导航、批量启停删除、订阅导入导出、常规密码修改和安全禁用的系统操作。"
```

## 升级影响

- 从 1.12.0 升级不增加数据库字段，不需要手工 SQL。
- 导入冲突按主 RSS 地址识别，可选择跳过或更新。
- “添加合集”当前表示批量导入一组订阅定义，不创建永久分组。
- 重启和关闭默认禁用；需要时设置 `FEEDDOCK_ALLOW_SYSTEM_ACTIONS=true`。
- 系统操作是否真正保持停止状态取决于容器重启策略。
