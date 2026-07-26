# 旧文件清理说明

GitHub 网页上传或直接复制新版本文件，只会覆盖同名文件，不会删除新版本已经取消的旧文件。

从包含刮削功能的旧版本升级时，仓库中必须删除：

```text
app/scraper.py
```

推荐在仓库目录执行：

```bash
cd /你的/FeedDock仓库目录
git rm -f app/scraper.py
git add -A
git commit -m "fix: remove legacy scraper module"
git push
```

若文件已经不存在，使用：

```bash
cd /你的/FeedDock仓库目录
rm -f app/scraper.py
git add -A
git commit -m "fix: clean legacy scraper module"
git push
```

当前 GitHub Actions 也会在测试和构建前执行 `rm -f app/scraper.py`，避免旧文件进入镜像；但仍建议使用 `git rm` 将它从仓库历史版本的当前树中正式删除。
