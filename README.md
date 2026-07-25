# FeedDock 1.8.0

FeedDock 是一个可通过 Docker 部署的自托管 RSS 规则处理与 qBittorrent 自动化服务。它提供应用内登录、首次改密、RSS/Atom 订阅、过滤规则、外部 qBittorrent、手动更新检查，以及带持久缓存的 Mikan 番剧目录。

> 本项目不提供、存储或分发任何媒体资源。请只添加你有权访问的 RSS，并遵守当地法律、源站条款与版权要求。

## 1.8.0 新增：按星期过滤隐藏番剧

Mikan 目录中的每个星期均有“编辑过滤”按钮：

1. 点击某个星期的“编辑过滤”；
2. 该星期已隐藏番剧重新出现并变暗；
3. 勾选不希望在普通目录中显示的番剧；
4. 点击“保存过滤”；
5. “本周全部显示”可清空该星期的隐藏设置。

隐藏记录以 `年份 + 季度 + 星期 + bangumi_id` 为唯一键，保存在 `/data/feeddock.db`。它不会修改 Mikan 缓存，也不会引起额外的 Mikan 请求。目录强制更新、浏览器刷新、容器重启和重新部署后仍然生效。

## 主要功能

- 中文 Web 管理页面；
- 默认 `admin / password`，首次登录后强制改密；
- 密码 PBKDF2-SHA256 哈希、HttpOnly 会话 Cookie；
- RSS / Atom 轮询、手动刷新、去重、包含与排除规则；
- 自定义集数正则、捕获组、集数偏移和总集数；
- 主/备用 RSS、自定义下载路径、遗漏检测和只下载最新集；
- Web 页面配置外部 qBittorrent；
- Mikan 按年份、季度、星期目录；
- Mikan 目录持久缓存，默认 6 小时更新周期；
- “强制更新”按钮；
- 全文扫描并按 `bangumi_id` 合并 Mikan 独立封面卡片；
- Mikan 封面同源代理和本地一天缓存；
- 每星期独立编辑、隐藏和恢复番剧；
- 仅手动点击时检查 GitHub Release；
- GitHub Actions 多架构镜像和 Release 自动发布。

## 飞牛 OS

使用 `docker-compose.fnos.yml`。默认数据目录：

```text
/vol1/1000/应用/feeddock/data
```

部署后访问：

```text
http://飞牛IP:7789
```

默认首次账号：

```text
admin
password
```

如果 qBittorrent 也在同一台飞牛 OS：

```text
http://host.docker.internal:8080
```

详细步骤见 `FNOS_DEPLOY.md`。

## 本地测试

```bash
python -m pip install -r requirements.txt pytest
pytest -q
```
