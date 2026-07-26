# FeedDock v1.10.2 飞牛 OS 部署

## 1. 目录

FeedDock 只需要一个持久目录：

```text
/vol1/1000/应用/feeddock/data
```

不需要把影视目录挂载给 FeedDock。

## 2. Compose

使用项目中的 `docker-compose.fnos.yml`。关键配置：

```yaml
environment:
  PUID: "0"
  PGID: "0"
  UMASK: "002"
  LOG_LEVEL: "INFO"
  DOWNLOAD_PATH: "/media"

volumes:
  - "/vol1/1000/应用/feeddock/data:/data"
```

`DOWNLOAD_PATH=/media` 是 qBittorrent 容器内路径，不是飞牛宿主机路径。

qBittorrent 应配置：

```yaml
volumes:
  - "/vol2/1000/影视:/media"
```

## 3. 启动

```bash
cd /你的/Compose目录
docker compose -f docker-compose.fnos.yml pull
docker compose -f docker-compose.fnos.yml up -d
```

打开：

```text
http://飞牛IP:7789
```

初始账号：`admin`  
初始密码：`password`

首次登录后必须修改密码。

## 4. DEBUG 日志

网页进入“系统日志与调试”，将级别从 `INFO` 切换为 `DEBUG`。网页设置会保存在 SQLite 中，并优先于 Compose 的 `LOG_LEVEL`。

Docker 日志：

```bash
cd /你的/Compose目录
docker logs --tail 300 feeddock
```

持续查看：

```bash
cd /你的/Compose目录
docker logs -f feeddock
```

宿主机日志：

```text
/vol1/1000/应用/feeddock/data/logs/feeddock.log
```

出现 500 后，复制错误中的请求编号，在网页“请求编号”输入框筛选。详细日志会显示：

- 请求路径和耗时；
- 订阅保存阶段；
- 异常类型和消息；
- 当前订阅表字段；
- 完整 Python traceback。

## 5. 刮削功能

v1.10.2 不包含任何刮削功能，不需要配置或安装 tinyMediaManager、Emby API、NFO 写入目录，也不需要授予 FeedDock 对影视目录的写权限。

## 6. 更新后仍出现 500

先确认正在运行新镜像：

```bash
cd /你的/Compose目录
docker exec feeddock python -c "from app.config import settings; print(settings.app_version)"
```

应输出：

```text
1.10.2
```

然后开启 DEBUG，重新保存订阅，并按请求编号查看日志。
