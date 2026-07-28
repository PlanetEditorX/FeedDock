# 容器镜像自动发布

FeedDock 的发布和在线更新以容器镜像为准，不要求开发者手动创建或推送 Git 标签，也不依赖仓库中的静态版本清单。

## 发布流程

向 `main` 或 `master` 推送后，工作流会：

1. 执行单元测试、JavaScript 语法检查和 Compose YAML 校验；
2. 比较本次 push 前后的文件变化；
3. 仅在 `.github/release-paths.txt` 匹配到应用、依赖或部署文件时继续构建；
4. 直接读取 `ghcr.io/planeteditorx/feeddock:latest` 的 OCI manifest 和镜像 config；
5. 从远端镜像标签读取 `org.opencontainers.image.version` 与 `org.opencontainers.image.revision`；
6. 若远端 revision 已等于当前提交，跳过重复构建；
7. 否则基于远端镜像版本递增补丁号，构建并推送多架构镜像；
8. 在镜像中写入当前提交 SHA、构建版本和构建时间；
9. 镜像发布完成后，尝试创建同版本 GitHub Release。Release 创建失败不会使已发布镜像失效。

例如远端 `latest` 的镜像版本为 `1.17.13`，本次重要代码发生变化后，新镜像版本为：

```text
1.17.14
```

运行中的 FeedDock 不通过 GitHub Release 判断更新，而是比较当前镜像内置 revision 与远端 `latest` 镜像 revision。

## 版本来源

`VERSION` 仅作为版本下限和手动提升主版本、次版本的入口，不是运行时更新判断依据。

默认情况下：

```text
VERSION = 1.17.13
远端 latest = 1.17.18
下一镜像版本 = 1.17.19
```

需要提升次版本时，将 `VERSION` 改为更高值：

```text
VERSION = 1.18.0
远端 latest = 1.17.18
下一镜像版本 = 1.18.0
```

工作流不会自动提交版本文件，也不会修改默认分支内容。

本地检查 `VERSION` 格式：

```bash
python scripts/release_version.py check
```

根据远端镜像版本模拟下一版本：

```bash
python scripts/release_version.py next \
  --base 1.17.13 \
  --latest-image 1.17.18
```

## 哪些变化会构建镜像

发布范围由以下文件维护：

```text
.github/release-paths.txt
```

默认包括：

- `app/**` 与未来的 `src/**`；
- `Dockerfile`、`docker-entrypoint.py`；
- Python 依赖文件；
- 两份 Docker Compose 和环境变量示例；
- 镜像版本脚本、镜像查询脚本和发布工作流。

`docs/**` 与 `tests/**` 不在镜像发布路径中。测试文件变化仍会运行验证，但不会推送新镜像。

## 镜像元数据

构建时写入以下 OCI 标准标签和运行时环境变量：

```text
org.opencontainers.image.version
org.opencontainers.image.revision
org.opencontainers.image.created
APP_VERSION
APP_REVISION
APP_CREATED_AT
```

`APP_REVISION` 是运行中镜像对应的提交 SHA。FeedDock 查询远端镜像时会读取同一标签进行比较，因此不需要挂载 Docker Socket，也不需要读取 GitHub Release。

## 手动运行

工作流支持：

- `push_image=true`：推送构建结果；
- `force_build=true`：即使远端 `latest` 已对应当前提交，也重新构建并递增补丁版本；
- `image_tag`：附加 `manual`、`dev` 或 `nightly` 等标签。

仅验证构建时，将 `push_image` 设为 `false`。

## GitHub 权限

推送 GHCR 镜像需要：

```yaml
permissions:
  packages: write
```

可选 GitHub Release 记录需要：

```yaml
permissions:
  contents: write
```

Release 是附属记录，不参与 FeedDock 的在线更新判断。

## 并发与重复运行

同一分支的发布工作流按顺序执行。工作流会先读取远端 `latest` 的 revision；如果它已经等于当前 `GITHUB_SHA`，普通 push 运行会跳过重复发布。
