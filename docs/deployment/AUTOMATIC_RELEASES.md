# 自动版本发布

FeedDock 默认分支采用自动补丁版本发布，不需要开发者单独创建或推送 Git 标签。

## 发布流程

每次向 `main` 或 `master` 推送后，工作流会：

1. 执行单元测试、版本一致性检查、JavaScript 语法检查和 Compose YAML 校验；
2. 读取最新 GitHub Release，例如 `v1.17.13`；
3. 比较该 Release 对应提交与当前分支最新提交之间的累计文件变化；
4. 发现重要文件变化时生成下一个补丁版本，例如 `1.17.14`；
5. 同步版本文件并提交 `chore(release): bump version to 1.17.14 [skip ci]`；
6. 构建并推送 `latest`、`1.17.14`、`1.17`、`1` 和 `sha-*` 镜像标签；
7. 自动创建 `v1.17.14` Git 标签和 GitHub Release。

自动提交由 GitHub Actions 完成，不要求本地执行 `git tag`。

## 哪些变化会发布

发布范围集中维护在：

```text
.github/release-paths.txt
```

默认包括：

- `app/**`：当前应用源代码和前端静态资源；
- `src/**`：为未来源代码目录预留；
- `Dockerfile`、`docker-entrypoint.py`；
- Python 依赖锁定或声明文件；
- 两份 Docker Compose 和环境变量示例；
- 版本同步脚本、发布路径清单和发布工作流。

`docs/**` 与 `tests/**` 不在发布路径清单中，因此仅修改文档或测试不会生成新版本。测试文件仍会触发验证工作流，但发布任务会显示“没有未发布的重要变化”。

需要调整规则时直接编辑 `.github/release-paths.txt`。该文件自身属于重要文件，修改规则后会生成一次新版本。

## 版本递增规则

默认只自动递增补丁版本：

```text
1.17.13 -> 1.17.14
```

需要发布次版本或主版本时，可以直接把 `VERSION` 手动提高，例如改为 `1.18.0`。工作流发现仓库版本高于最新 Release 后，会采用手动指定的版本，不再额外递增为 `1.18.1`。

版本同步脚本会同时更新：

- `VERSION`；
- `update.json`；
- Dockerfile 的 `APP_VERSION` 默认值；
- `app/config.py` 的运行时默认版本和 User-Agent；
- `.env.example` 的构建版本和 User-Agent；
- README 当前版本；
- HTML 中所有静态 CSS/JavaScript 缓存参数。

本地检查：

```bash
python scripts/release_version.py check
```

本地模拟同步：

```bash
python scripts/release_version.py sync \
  --version 1.18.0 \
  --published-at 2026-07-28T12:00:00Z
```

## GitHub 权限要求

工作流需要：

```yaml
permissions:
  contents: write
  packages: write
```

仓库还需要允许 GitHub Actions 写入内容。在 GitHub 仓库设置中检查：

```text
Settings -> Actions -> General -> Workflow permissions
```

选择 `Read and write permissions`。如果默认分支启用了分支保护，还需要允许 GitHub Actions 创建自动版本提交；否则工作流会在 `git push` 步骤失败。

## 手动运行

`workflow_dispatch` 保留两个控制项：

- `push_image=true`：推送镜像并允许创建 Release；
- `force_release=true`：即使没有重要文件变化，也递增补丁版本。

只想验证镜像构建时，将 `push_image` 设为 `false`。这种模式不会修改版本、推送镜像或创建 Release。

## 并发处理

工作流按分支串行运行。如果旧工作流开始时发现分支已经有更新提交，它会跳过发布，由后续工作流基于最新提交处理全部累计变化，避免旧提交覆盖新版本。
