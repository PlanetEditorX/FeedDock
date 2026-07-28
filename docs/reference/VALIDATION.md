# FeedDock 镜像更新检测验证报告

## 本次验证范围

- 运行时更新检查直接读取部署镜像标签的 OCI manifest 与 image config；
- 通过 `org.opencontainers.image.revision`、`org.opencontainers.image.version` 和远端 digest 判断更新状态；
- 支持 OCI index、Docker manifest list、单平台 manifest，以及 `linux/amd64`、`linux/arm64` 和 ARM variant 选择；
- 支持公开仓库匿名 Bearer Token，以及私有仓库用户名/Token 认证；
- 远端镜像查询失败时使用数据库缓存，不再回退到 `update.json` 或 GitHub Release；
- GitHub Actions 从远端 `latest` 镜像标签读取上一镜像版本，自动递增补丁版本；
- GitHub Release 仅作为可选发布记录，创建失败不会影响镜像发布；
- Watchtower 继续负责实际拉取镜像和重建容器。

## 自动化测试

```text
196 unit tests passed
```

新增及重点覆盖：

- GHCR/Registry V2 Bearer 认证挑战与 Token 获取；
- 私有仓库 Basic 凭据交换；
- 多架构镜像选择当前运行平台，并忽略 provenance/attestation descriptor；
- OCI revision、version、created、root digest 与平台 digest 读取；
- 当前 revision 与远端 revision 不同时提示更新；
- revision 相同且本地元数据来自镜像构建文件时，可识别同代码的新镜像构建；
- revision 相同但本地版本来自旧容器环境变量时，不误报更新并给出重建提示；
- 镜像内构建信息文件优先级高于残留的 APP_VERSION/APP_REVISION 环境变量；
- Registry 查询缓存、过期缓存与错误降级；
- digest 固定镜像禁止 Watchtower 标签更新；
- 发布版本由远端镜像版本递增，`VERSION` 只作为 major/minor 人工提升下限；
- 重要文件路径检测，不因纯文档或纯测试变更发布镜像；
- 项目中不存在 `update.json`，更新服务不调用 GitHub Release API。

## 静态与配置检查

- Python `compileall`：通过；
- 前端 JavaScript `node --check`：通过；
- `docker-compose.yml`、`docker-compose.fnos.yml`：YAML 解析通过；
- `.github/workflows/docker-publish.yml`：YAML 解析通过；
- `VERSION` 语义化版本下限：`1.17.13`，校验通过；
- Dockerfile 写入 OCI 标准标签与 `/app/.feeddock-build.json`，不再把版本元数据作为最终镜像 ENV；
- HTML 静态资源缓存键由运行镜像 revision 动态生成；
- Compose 已提供 `UPDATE_REGISTRY_USERNAME`、`UPDATE_REGISTRY_TOKEN` 可选配置；
- Watchtower API 保持 Docker 内部网络访问，不映射宿主机端口。

## 判断边界

FeedDock 不挂载 Docker Socket，因此运行中的容器不能直接读取 Docker Engine 保存的本地 RepoDigest。当前方案使用镜像构建时写入的 source revision 与远端 OCI revision 做稳定比较，并展示远端 root digest 和当前平台 digest。实际更新时，Watchtower 会再按镜像 digest 判断是否需要拉取和重建。

此设计避免把 `/var/run/docker.sock` 暴露给主应用。旧镜像没有 `/app/.feeddock-build.json` 时会显示“容器环境变量（兼容）”；安装新镜像后切换为“镜像构建文件”，版本与 revision 均来自当前镜像文件系统。

## 环境限制

当前执行环境的外部 DNS 不可用，无法对生产 GHCR 地址完成实时联网查询。Registry 认证、manifest、平台选择、config blob、OCI 标签、digest、缓存和错误处理链路已通过完整模拟测试。部署后应确认 GHCR 包为公开可读；若是私有包，应配置具有 `read:packages` 权限的 `UPDATE_REGISTRY_USERNAME` 与 `UPDATE_REGISTRY_TOKEN`。
