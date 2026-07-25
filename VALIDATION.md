# FeedDock v1.8.1 验证报告

修复内容：

- `requirements.txt` 补充 `SQLAlchemy>=2.0,<3.0`。
- 新增 `requirements-test.txt`，集中安装应用与测试依赖。
- GitHub Actions 使用 `python -m pip` 和 `python -m pytest`，避免解释器环境不一致。
- 测试前显式验证 FastAPI、HTTPX、BeautifulSoup 与 SQLAlchemy 导入。
- 新增旧版残留文件清理说明，防止网页覆盖上传造成新旧代码混用。
- 保留按星期编辑、隐藏和恢复 Mikan 番剧的持久化过滤功能。

本地检查：

- Python 3.12 项目编译通过。
- JavaScript 语法检查通过。
- YAML 解析通过。
- 项目现有自动化测试通过。
- SQLAlchemy 导入验证通过。
