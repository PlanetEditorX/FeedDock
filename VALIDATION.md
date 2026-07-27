# FeedDock 1.17.10 验证报告

## 修复场景

本次针对以下飞牛部署进行验证：

```text
qBittorrent 保存根目录：/vol2/1000/影视
FeedDock 容器挂载目录：/media
数据库旧值 media_local_root：/vol2/1000/影视
Compose 未显式配置 MEDIA_LOCAL_ROOT
```

升级后：

- `MEDIA_LOCAL_ROOT` 的容器默认值为 `/media`；
- 已存在的 `migration:1.17.7:separate-media-paths` 标记不会阻止本次修复；
- 新迁移把旧数据库中的 `media_local_root` 改为 `/media`；
- 运行时读取配置时也会识别并修正相同的旧值；
- `/vol2/1000/影视/<相对目录>` 成功映射到 `/media/<相对目录>`；
- 映射后的真实临时目录通过存在性与目录类型检查。

## 兼容性

- 显式配置 `MEDIA_LOCAL_ROOT` 时始终尊重用户配置；
- Docker 中 `/media` 是实际挂载点时自动选择 `/media`；
- qBittorrent 使用 `/vol*`、`/volume*`、`/mnt*` 或 `/share*` 等宿主机/NAS 路径时自动选择容器挂载根目录；
- 裸机或测试环境使用相同普通路径时，不会被错误强制切换为 `/media`；
- 保存刮削设置时，本地路径留空会选择正确的容器根目录，而不是 qBittorrent 路径。

## 自动化与静态验证

- **168 项自动化测试全部通过，另有 15 个子测试通过**；
- Python 全项目编译通过；
- 6 个 JavaScript 文件语法检查通过；
- Docker Compose、飞牛 Compose 和 GitHub Actions YAML 解析通过；
- 128 个页面 HTML ID 均唯一；
- FastAPI 运行版本为 `1.17.10`；
- `VERSION`、Docker 构建版本、静态资源缓存参数和 `update.json` 一致；
- 旧数据库迁移脚本实测得到 `media_local_root=/media`；
- `git diff --check` 通过。

## 数据库兼容

本次不增加数据库表或字段。仅在现有 `app_settings` 表增加迁移标记：

```text
migration:1.17.10:default-media-local-root
```

订阅、RSS 指纹、下载记录、torrent hash、刮削状态及用户媒体文件均不受影响。

## 环境限制

当前环境没有真实飞牛 Docker 服务，因此没有直接重建用户容器。路径映射使用真实 `/media` 临时目录验证，旧数据库迁移使用临时 SQLite 数据库验证。
