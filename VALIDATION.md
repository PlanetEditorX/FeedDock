# FeedDock 1.1.0 功能验证报告

验证日期：2026-07-25

## 1. 登录与首次改密

验证结果：通过。

实际启动 Uvicorn 服务后执行了以下流程：

1. 未登录访问 `/`，返回 `303` 并跳转 `/login`。
2. 使用错误密码登录，返回 `401`。
3. 使用初始密码登录，返回：

   ```json
   {"authenticated":true,"username":"admin","must_change_password":true}
   ```

4. 未改密访问 `/api/dashboard`，返回：

   ```text
   HTTP 428
   {"detail":"PASSWORD_CHANGE_REQUIRED"}
   ```

5. 访问 `/change-password`，页面包含“请修改初始密码”提示。
6. 修改密码成功后，新会话可以访问 `/api/dashboard`，返回 `200`。
7. 注销后再次访问业务接口，返回 `401`。

密码使用 PBKDF2-SHA256 哈希保存；修改密码会增加会话版本，使旧 Cookie 失效。

## 2. 外部 qBittorrent

验证结果：通过。

使用独立 HTTP 测试服务模拟位于另一主机的 qBittorrent Web API，验证：

- `POST /api/v2/auth/login` 登录成功。
- `GET /api/v2/app/version` 读取版本成功。
- `POST /api/v2/torrents/add` 推送 Magnet 任务成功。
- 客户端使用配置的完整外部 HTTP 地址，不依赖 Compose 内置 qBittorrent。
- 默认 FeedDock 服务没有 `depends_on: qbittorrent`。
- qBittorrent 仅在 `with-qbit` profile 下启动。

## 3. 更新功能

验证结果：通过。

验证内容：

- 从兼容 GitHub Releases API 的接口读取最新版本。
- 比较 `1.1.0` 与 `1.2.0`，正确识别存在更新。
- 使用 `Authorization: Bearer <token>` 调用 Watchtower `/v1/update`。
- Watchtower 返回成功后，FeedDock 返回已触发更新提示。
- Compose 中 Watchtower 仅在 `updater` profile 下启动。
- Watchtower 使用 label 过滤，只更新 FeedDock，不更新 qBittorrent 或自身。

## 自动化测试

执行命令：

```bash
python -m unittest discover -s tests -v
```

结果：11 项全部通过。

覆盖范围：

- 登录、错误密码、首次改密强制跳转、API 锁定、改密、注销
- 外部 qBittorrent 连接与任务推送
- 版本比较、Release 检查与 Watchtower 更新触发
- RSS、Atom、关键词过滤、集数提取和路径越界保护

## 其他检查

- Python 全项目编译检查：通过
- JavaScript `node --check`：通过
- `docker-compose.yml` YAML 解析：通过
- GitHub Actions 工作流 YAML 解析：通过
- 容器入口脚本降权测试：从 root 修正数据目录权限后，以 UID/GID `1000:1000` 启动主进程

## 验证边界

当前执行环境没有 Docker Engine，因此没有在本机执行 `docker build`、真实 GHCR 拉取或真实 Watchtower 容器重建。应用 HTTP 流程已实际启动验证；qBittorrent 和 Watchtower 使用协议兼容的本地模拟服务完成集成测试。
