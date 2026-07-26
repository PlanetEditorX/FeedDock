# 容器入口文件缺失修复

错误：

```text
exec: "/usr/local/bin/feeddock-entrypoint": stat /usr/local/bin/feeddock-entrypoint: no such file or directory
```

原因是镜像的 Entrypoint 配置指向 `/usr/local/bin/feeddock-entrypoint`，但旧 Dockerfile 没有保证该文件被复制到镜像。

当前 Dockerfile 已执行：

```dockerfile
COPY docker-entrypoint.py /usr/local/bin/feeddock-entrypoint
RUN chmod 0755 /usr/local/bin/feeddock-entrypoint \
    && test -x /usr/local/bin/feeddock-entrypoint \
    && /usr/local/bin/feeddock-entrypoint --check
ENTRYPOINT ["/usr/local/bin/feeddock-entrypoint"]
```

## 更新仓库

不要仅添加新文件。请使用 `git add -A`，确保 Dockerfile、工作流和删除记录全部提交：

```bash
cd /你的/feeddock仓库目录
git add -A
git commit -m "fix: include and verify Docker entrypoint"
git push
```

## 飞牛 OS 重新部署

GitHub Actions 变为绿色后，在飞牛 Docker 中停止 FeedDock 项目，重新拉取并部署 `ghcr.io/planeteditorx/feeddock:latest`。

若飞牛仍使用旧镜像，先删除本地 `latest` 镜像，再重新部署。不要删除数据目录：

```text
/vol1/1000/应用/feeddock/data
```
