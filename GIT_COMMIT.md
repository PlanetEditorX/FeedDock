# Git 提交说明

## 推荐提交标题

```text
refactor(mikan): 模块化目录订阅状态同步
```

## 提交正文

```text
- 提取后端 Mikan bangumiId 解析与订阅 ID 聚合模块
- 提取前端目录订阅状态纯函数模块
- 主 RSS 与备用 RSS 均参与识别，参数名大小写不敏感
- 新增、编辑和删除订阅后即时刷新当前目录标识
- 仅在目录状态实际变化时重新渲染
- 增加 Python 与 Node 边界测试并接入 CI 语法检查
- 更新版本至 1.10.1，刷新静态资源缓存参数
- 补充功能设计、部署注意事项和验证报告
```

## 主要文件

```text
app/mikan_subscription.py
app/static/mikan-subscription-state.js
app/static/app.js
app/main.py
app/static/index.html
tests/test_mikan_subscription_state.py
tests/test_deployment_files.py
MIKAN_SUBSCRIPTION_STATUS.md
VALIDATION.md
```

## 提交命令

```bash
git add .
git commit -m "refactor(mikan): 模块化目录订阅状态同步" \
  -m "拆分前后端订阅状态模块，支持主/备用 RSS 与大小写兼容，并补齐即时同步、边界测试、CI 校验和说明文档。"
```

本次更新不修改数据库结构，不需要迁移。
