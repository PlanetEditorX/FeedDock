# FeedDock 1.17.1 验证报告

## 修复目标

处理多个原站同时出现以下错误的部署问题：

```text
[Errno -3] Temporary failure in name resolution
```

该错误表示容器无法完成 DNS 解析，不属于 Mikan、ANI.BT 或 Anime Garden 的目录解析错误。

## 实现验证

- `docker-compose.yml` 为 FeedDock 服务设置三个可覆盖 DNS；
- `docker-compose.fnos.yml` 为飞牛部署设置三个默认 DNS；
- 配置 `timeout:2`、`attempts:2`、`rotate`；
- 新增 `/api/network/diagnostics` 管理员接口；
- 诊断读取容器 `/etc/resolv.conf` 中的 nameserver 与 options；
- 分别解析 Mikan 主域名、Mikan 备用域名、ANI.BT、Anime Garden 和 Bangumi；
- DNS 异常分类为 `dns`，不会混同为站点解析错误；
- “测试外部请求”同时附带 DNS 结果；
- 网页代理设置新增“诊断 DNS”和结构化结果展示；
- 不返回 resolver search 域，避免暴露私有基础设施名称；
- 不使用固定站点 IP，避免 HTTPS SNI、证书和 CDN 失效。

## 自动化测试

执行：

```bash
python -m unittest discover -s tests -v
```

结果：

```text
Ran 140 tests
OK
```

新增覆盖：

- `/etc/resolv.conf` nameserver/options 解析；
- IPv4/IPv6 地址去重；
- `socket.gaierror(-3)` 分类；
- 所有目标同时失败时的容器 DNS 指引；
- 普通 Compose 和飞牛 Compose 的 DNS 配置；
- 网络诊断前端入口与 API 路由。

## 静态验证

- Python 全项目 `compileall` 通过；
- 所有前端 JavaScript 文件 `node --check` 通过；
- `docker-compose.yml` YAML 解析通过；
- `docker-compose.fnos.yml` YAML 解析通过；
- GitHub Actions 工作流 YAML 解析通过；
- 主页面共 126 个 HTML ID，全部唯一；
- 运行版本为 `1.17.1`。

## 故障复现

当前隔离执行环境无法解析外部域名。运行新诊断时得到：

```text
容器无法解析任何外部站点域名，请修复 Docker DNS 或配置可用代理
```

Mikan 三个地址、ANI.BT、Anime Garden 和 Bangumi 均被独立标记为 DNS 失败，与用户报告的故障模式一致。

## 未执行项目

当前环境没有 Docker CLI，无法实际重新创建容器并验证写入后的 `/etc/resolv.conf`。Compose 字段已依据规范进行 YAML 与结构测试；部署后仍需在目标 NAS 上执行 `--force-recreate` 并使用网页诊断确认。

## 数据兼容

本版本不修改数据库模型。1.17.0 的订阅、RSS 指纹、缓存、隐藏偏好和下载记录均可直接使用。
