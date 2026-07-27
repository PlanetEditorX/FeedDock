# FeedDock 1.17.1 容器网络与 DNS 排障

当 Mikan、ANI.BT、Anime Garden、Bangumi 等多个互不相关的域名同时出现：

```text
[Errno -3] Temporary failure in name resolution
```

故障发生在容器 DNS 解析层，不是某个番剧目录接口或 RSS 解析器。应用无法在没有 IP 地址的情况下建立 HTTPS 连接，继续增加备用网址不会解决该问题。

## 1.17.1 默认 DNS

`docker-compose.yml` 和 `docker-compose.fnos.yml` 为 FeedDock 服务增加了：

```yaml
dns:
  - 223.5.5.5
  - 119.29.29.29
  - 1.1.1.1
dns_opt:
  - timeout:2
  - attempts:2
  - rotate
```

普通 Compose 可通过 `.env` 覆盖：

```dotenv
FEEDDOCK_DNS_PRIMARY=223.5.5.5
FEEDDOCK_DNS_SECONDARY=119.29.29.29
FEEDDOCK_DNS_TERTIARY=1.1.1.1
```

DNS 是容器创建时写入 `/etc/resolv.conf` 的网络配置。修改 Compose 或 `.env` 后，必须重新创建容器：

```bash
docker compose up -d --force-recreate feeddock
```

仅执行 `docker restart feeddock` 或在网页中重启进程不会更新 DNS。

## 飞牛 OS

使用新的 `docker-compose.fnos.yml` 重新部署，或者在飞牛 Compose 编辑器的 `feeddock` 服务中加入上面的 `dns` 与 `dns_opt`，再选择重新创建容器。

重新创建后执行：

```bash
docker exec feeddock cat /etc/resolv.conf
docker exec feeddock python -c "import socket; print(socket.getaddrinfo('anibt.net', 443))"
docker exec feeddock python -c "import socket; print(socket.getaddrinfo('mikanime.tv', 443))"
```

## 网页诊断

进入：

```text
设置 → 代理设置 → 诊断 DNS
```

页面会显示：

- 容器当前 nameserver；
- Mikan 主域名和备用域名；
- ANI.BT；
- Anime Garden；
- Bangumi；
- 每个域名的解析结果和 IP。

“测试外部请求”会继续测试实际 HTTPS 请求，并同时附带 DNS 诊断。

## 仍然失败时

1. 检查 NAS 防火墙是否允许容器访问 UDP/TCP 53 和 TCP 443；
2. 在宿主机上测试相同域名，确认不是整个 NAS 无法联网；
3. 将 DNS 改为路由器、运营商或所在网络可访问的解析器；
4. 在 FeedDock 的“代理设置”配置可用 HTTP/SOCKS5 代理；
5. 代理运行在 NAS 上时，使用 `host.docker.internal` 或宿主机局域网 IP，不要填写容器中的 `127.0.0.1`。

## 为什么不内置固定 IP

Mikan、ANI.BT 和 Anime Garden 使用 HTTPS 与 CDN，服务器 IP 可能变化。把临时 IP 写入 `/etc/hosts` 会造成证书、SNI、负载均衡和后续迁移问题，因此 FeedDock 不采用固定 IP 绕过 DNS。
