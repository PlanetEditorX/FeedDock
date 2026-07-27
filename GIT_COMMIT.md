# FeedDock 1.17.1 Git 提交说明

## 推荐提交

```text
fix(network): 修复容器 DNS 并增加网络诊断
```

## 提交正文

```text
- 为普通 Compose 和飞牛 Compose 配置可轮换的外部 DNS
- 支持通过环境变量覆盖普通 Compose 的三个 DNS 地址
- 新增容器 DNS 诊断 API 和代理设置页面诊断结果
- 分别检查 Mikan、ANI.BT、Anime Garden 与 Bangumi 域名
- 外部请求测试同时返回 DNS 状态，区分解析与 HTTPS/代理错误
- 增加 DNS 失败分类、解析器读取和部署配置测试
- 版本更新为 1.17.1
```

## 影响范围

```text
app/network_diagnostics.py
app/main.py
app/static/index.html
app/static/app.js
app/static/styles.css
docker-compose.yml
docker-compose.fnos.yml
.env.example
.env.fnos.example
NETWORK_TROUBLESHOOTING.md
tests/test_network_diagnostics.py
tests/test_deployment_files.py
```

## 数据库

不增加或修改数据库字段，无需执行迁移。

## 部署注意

DNS 属于容器创建时的网络配置。应用补丁或替换 Compose 后必须执行：

```bash
docker compose up -d --force-recreate feeddock
```

仅重启旧容器或应用进程不会更新容器的 `/etc/resolv.conf`。
