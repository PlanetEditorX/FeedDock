# FeedDock 1.17.9 验证报告

## 功能验证

### 下载前媒体去重

- 规范命名开启且目标视频文件已存在时，即使旧配置关闭“文件已下载自动跳过”，也不会再次调用 qBittorrent；
- 开启“文件已下载自动跳过”后，可通过 `SxxExx` 标记识别被其它媒体工具再次改名的同集视频；
- qBittorrent 保存路径会先映射为 FeedDock 容器内的媒体路径；
- 扫描限制为目标目录向下两级、最多 5000 个文件；
- 命中后条目记录为“已跳过”，原因包含实际命中的文件名。

### 孤儿媒体元数据清理

- 自动和手动刷新订阅均会检查已经完成且曾刮削的媒体目录；
- 即使全局 RSS 开关关闭，媒体目录清理仍会执行，随后才跳过网络 RSS 请求；
- 目标季目录无视频时，可删除 FeedDock 生成的季 NFO、剧集 NFO 和季海报；
- 整个剧集或电影目录无视频时，可继续删除根目录 NFO、海报、背景图和刮削清单；
- 其它季度仍有视频时，保留剧集根目录的 `tvshow.nfo`、总海报与背景图；
- 视频、字幕和任意非元数据用户文件均保持不变；
- 清理路径必须位于配置的本地媒体根目录内部。

### 静态版本清单与在线更新

- `update.json` 版本与 `VERSION` 一致；
- 版本检查优先请求静态版本清单，不调用 GitHub Release API；
- 支持 ETag、Last-Modified 和 HTTP 304；
- 默认 6 小时内使用 SQLite 缓存，不重复请求外部服务；
- 远程清单临时不可用时继续显示旧缓存；
- 仅在没有可用清单或缓存时调用 GitHub Release API；
- GitHub API 备用检查在本地限制为每天最多一次；
- 系统设置显示“检查在线更新”以及“在线更新/配置在线更新”；
- 实际替换 Docker 镜像必须配置 Watchtower HTTP API，不向 FeedDock 容器直接开放 Docker Socket。

## 自动化与静态验证

- **165 项自动化测试全部通过**；
- Python 全项目编译通过；
- 6 个 JavaScript 文件语法检查通过；
- Docker Compose、飞牛 Compose 和 GitHub Actions YAML 解析通过；
- 138 个页面 HTML ID 均唯一；
- FastAPI 与静态资源版本为 `1.17.9`；
- `VERSION`、`update.json` 和发布 URL 对齐；
- `git diff --check` 通过。

## 数据库兼容

本次不增加数据库表或字段，不需要手工迁移。静态版本清单、ETag、检查时间和 GitHub API 备用检查时间保存在现有 `app_settings` 表中。订阅、RSS 指纹、下载记录、torrent hash 和刮削状态均保持兼容。

## 环境限制

当前环境没有 Docker CLI、真实 qBittorrent、真实媒体服务器或 Watchtower 服务，因此没有实际构建容器、推送真实下载任务或执行真实在线容器更新。媒体文件检查与清理使用真实临时文件系统验证；版本清单、GitHub API 和 Watchtower 交互使用模拟 HTTP 服务验证。
