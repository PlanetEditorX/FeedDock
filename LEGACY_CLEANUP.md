# 升级到 v1.8.1 前的旧文件清理

GitHub 网页上传文件只会覆盖同名文件，不会删除新版项目中已经取消的旧文件。
如果仓库曾运行 SQLAlchemy 版本的 FeedDock，请在提交 v1.8.1 前删除下面这些旧文件（存在才删除）：

```text
app/database.py
app/discovery.py
app/models.py
app/rss_service.py
app/mikan_cache.py

tests/test_discovery.py
tests/test_integrations.py
tests/test_mikan_cache.py
tests/test_rss_service.py
```

v1.8.1 的正式文件为：

```text
app/db.py
app/mikan.py
app/rss.py
app/runtime_config.py

tests/test_api.py
tests/test_filtering.py
tests/test_mikan_parser.py
tests/test_rss.py
```

## 推荐的干净更新方法

在本地克隆仓库后，先删除仓库中除 `.git` 外的旧内容，再复制 v1.8.1 完整源码：

```bash
cd /你的/feeddock
find . -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
cp -a /解压路径/FeedDock-1.8.1/. .
git add -A
git commit -m "fix: install complete test dependencies and clean legacy files"
git push
```

`git add -A` 很重要，它会把旧文件删除记录一并提交。
