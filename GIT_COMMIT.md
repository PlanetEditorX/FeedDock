# FeedDock 1.17.7 Git 提交说明

## 提交标题

```text
fix(scraper): 映射下载器路径并增加单订阅刮削
```

## 提交正文

```text
- 分离 qBittorrent 下载根目录与 FeedDock 本地媒体挂载目录
- 按相对路径将下载器保存路径映射到 FeedDock 容器路径
- 自动迁移旧版被强制覆盖的 media_local_root
- 同步修复 NFO、图片、bangumi.ini 与已存在文件检查的路径定位
- 在每张订阅卡片增加“刮削”按钮
- 单订阅刮削只处理该订阅的已完成下载条目
- 路径错误日志显示下载器路径、两个根目录和映射结果
- 增加飞牛宿主机路径到 /media 的回归测试
```

## 数据库

不增加数据库列。首次启动会写入迁移标记 `migration:1.17.7:separate-media-paths`；如果旧版 `media_local_root` 仍等于 qBittorrent 下载根目录，而 Compose 配置了不同的 `MEDIA_LOCAL_ROOT`，会自动恢复为 Compose 中的本地挂载路径。
