# FeedDock 1.17.9 Git 提交说明

## 推荐提交

```text
feat(library): 增加媒体去重、孤儿清理与静态更新
```

## 提交正文

```text
- 下载前检查媒体目录中的精确目标文件和 SxxExx 集数标记
- 刷新订阅时清理没有视频的 FeedDock NFO、海报和背景图
- RSS 总开关关闭时仍允许执行本地孤儿元数据清理
- 使用静态 update.json、条件请求和 SQLite 缓存检查新版本
- GitHub Release API 降级为每天最多一次的备用检查
- 在系统设置中提供在线更新入口与 Watchtower 配置提示
```

## 兼容性

- 不增加数据库列；版本清单缓存继续使用 `app_settings`。
- 不删除视频、字幕或任意非元数据用户文件。
- 已存在的规范命名目标视频会始终阻止重复推送；较宽松的 `SxxExx` 匹配仍由“文件已下载自动跳过”控制。
- 在线更新仍要求外部 Watchtower HTTP API，不向 FeedDock 容器开放 Docker Socket。
