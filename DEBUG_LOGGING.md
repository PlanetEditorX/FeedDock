# FeedDock 调试日志

本次修改只增强日志，不改变订阅、下载、重命名、元数据或刮削逻辑。

## 在网页开启 DEBUG

1. 登录 FeedDock。
2. 打开“系统日志”板块。
3. 将“日志级别”改为 `DEBUG`。
4. 点击“保存级别”。
5. 再次执行出现问题的操作。

DEBUG 会记录：

- API 请求方法、路径、状态码和耗时；
- 添加或编辑订阅时所处阶段；
- 请求编号；
- 异常类型与异常消息；
- 完整 Python traceback；
- RSS 后台轮询和调度线程中原本被忽略的异常。

密码、Token、API Key、Cookie 和代理认证信息会自动替换为 `***`。

## 500 错误

页面会显示类似：

```text
服务器内部错误 [a1b2c3d4e5f6]：OperationalError: ...
```

方括号中的内容是请求编号。在“系统日志”中展开 ERROR 记录，可以看到相同请求编号、失败阶段和完整 traceback。

## 日志位置

网页：FeedDock 的“系统日志”板块。

容器文件：

```text
/data/logs/feeddock.log
```

飞牛宿主机默认位置：

```text
/vol1/1000/应用/feeddock/data/logs/feeddock.log
```

Docker 控制台：

```bash
cd /你的/Compose目录
docker logs --tail 300 feeddock
```

持续查看：

```bash
cd /你的/Compose目录
docker logs -f feeddock
```

文件日志单个最大 5 MB，保留 5 个轮转文件。
