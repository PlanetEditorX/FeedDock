# FeedDock 1.17.7 验证报告

## 功能验证

- qBittorrent 保存根目录 `/vol2/1000/影视` 可映射到 FeedDock 本地挂载根目录 `/media`；
- 用户报告路径 `/vol2/1000/影视/感谢对战。～大小姐才不玩格斗游戏～ (2026)/Season 01` 成功映射到 `/media/感谢对战。～大小姐才不玩格斗游戏～ (2026)/Season 01`；
- 映射后的真实临时目录成功写入 `tvshow.nfo`、`season.nfo` 和剧集同名 NFO；
- 映射结果仍受 FeedDock 本地媒体根目录越界保护；
- `bangumi.ini` 与“文件已下载自动跳过”使用同一映射逻辑；
- 元数据设置允许 qBittorrent 根目录和 FeedDock 本地根目录不同；
- 每张订阅卡片显示“刮削”按钮；
- 单订阅刮削只处理目标订阅的已完成条目，不修改其他订阅状态；
- 没有已完成条目时返回明确提示；
- 旧版强制路径配置自动迁移到 Compose 的 `MEDIA_LOCAL_ROOT`。

## 自动化与静态验证

- 154 项自动化测试通过；
- Python 全项目编译通过；
- 6 个 JavaScript 文件语法检查通过；
- Docker Compose、飞牛 Compose和 GitHub Actions YAML 解析通过；
- 页面 128 个 HTML ID 唯一；
- FastAPI 导入与运行版本 `1.17.7` 检查通过。

## 迁移验证

使用模拟旧版 SQLite 数据库：

```text
download_path=/vol2/1000/影视
media_local_root=/vol2/1000/影视
MEDIA_LOCAL_ROOT=/media
```

执行 `ensure_schema()` 后验证：

```text
download_path=/vol2/1000/影视
media_local_root=/media
migration:1.17.7:separate-media-paths=1
```

订阅、下载条目和历史刮削状态不被删除。

## 环境限制

当前环境没有真实飞牛文件系统、qBittorrent 和媒体服务器，因此容器挂载通过真实临时目录与路径映射测试验证；实际部署仍需保证 FeedDock 的 `/media` 确实挂载宿主机 `/vol2/1000/影视`。
