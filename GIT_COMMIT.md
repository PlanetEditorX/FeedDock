# FeedDock 1.17.10 Git 提交说明

## 推荐提交

```text
fix(scraper): 自动修复容器媒体挂载路径
```

## 提交正文

```text
- MEDIA_LOCAL_ROOT 未配置时默认使用容器内 /media
- 修复旧数据库把 qBittorrent 宿主机路径保存为本地刮削路径的问题
- 即使 1.17.7 迁移已经执行，也会重新修正错误路径
- 增加运行时自修复与裸机路径兼容判断
- 补充飞牛 /vol2 到 /media 的迁移和映射测试
```

## 主要文件

```text
app/config.py
app/database.py
app/media_paths.py
app/runtime_config.py
docker-entrypoint.py
tests/test_settings_features.py
tests/test_deployment_files.py
MEDIA_PATH_DEFAULT_1.17.10.md
```

本次不新增数据库字段，不需要手工 SQL。
