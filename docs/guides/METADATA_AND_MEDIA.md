# 元数据、命名与媒体目录

本文统一说明元数据匹配、目录和文件命名、qBittorrent 路径映射、本地 NFO/图片刮削以及媒体库清理边界。

## 核心路径关系

- `DOWNLOAD_PATH`：qBittorrent 能识别的下载根目录。
- `MEDIA_LOCAL_ROOT`：FeedDock 容器实际可见的媒体根目录。
- 两者字符串可以不同，但必须映射到同一份宿主机目录。

## 元数据识别与命名

## 季度策略

- 标题识别：支持“第二季”“第2期”“Season 2”“S02”。
- 最新季：读取 TMDB 剧集详情中的季度列表，排除 Season 0，选择最高已播季度。
- 手动：使用用户输入的季编号。

## 数据来源

- TMDB：Emby ID、系列/季度结构、季度集数、海报和简介。
- Bangumi：动画中文/日文名称、简介、放送日期和话数。
- AniList：动漫标题、集数、封面、背景图和简介，作为公开 API 备选。

## 本地旁车元数据与媒体库识别

FeedDock 会在下载完成后写入标准 NFO、海报和背景图，但不直接修改飞牛影视、Emby 或 Jellyfin 的数据库。媒体服务器仍负责扫描目录并建立索引。tinyMediaManager 远程调用目前未启用。

# FeedDock 元数据、命名与路径设计

## 1. 数据源职责

### Mikan

提供季度番剧目录、字幕组 RSS 和原始发布标题。Mikan 不作为 Emby 外部 ID 来源。

### Bangumi

提供动漫中文名、原名、放送日期、简介、封面和话数。公开读取通常无需 Token。

### TMDB

提供 Emby 使用的 TMDB ID、规范标题、年份、电视剧季度、简介、海报、背景图和季度总集数。

### Emby

读取 FeedDock 生成的 `名称 (年份)` 规范目录、NFO 和本地图片，也可以继续使用自己的在线元数据提供者补充演员、评分和剧集简介。TMDB ID 保存在 NFO 中，不再默认写入目录名。

## 2. 年份与名称

选择 TMDB 或 Bangumi 搜索结果时，FeedDock 会统一写入：

```text
标题 (年份)
```

例如：

```text
从0位居民开始的边境领主大人 (2026)
```

该名称会显示在订阅编辑器和订阅卡片中。生成媒体目录时会自动避免重复年份，因此不会出现 `(2026) (2026)`。

名称模式：

| 模式 | 名称来源 |
|---|---|
| auto | 手动标题 → TMDB 标题 → Bangumi 标题 → 订阅名称 |
| manual | 手动规范标题 |
| tmdb | TMDB 标题 |
| bangumi | Bangumi/参考标题 |

非法文件名字符会替换为下划线。

## 3. 唯一下载根目录

qBittorrent 和订阅路径必须使用相同的容器路径，默认：

```text
/media
```

网页保存 qBittorrent 根目录时，FeedDock 会同步所有订阅的根目录及刮削根目录。每个订阅不再使用第二套独立根目录；自定义目录结构应通过模板完成：

```text
{base}/{media_folder}/Season {season:02}
```

任何模板路径穿越都会回退到安全的默认媒体目录。

## 4. Emby 目录与文件名

电视剧目录：

```text
从0位居民开始的边境领主大人 (2026)/Season 01
```

剧集文件：

```text
从0位居民开始的边境领主大人 (2026) - S01E01.mkv
```

电影目录：

```text
电影标题 (2026)
```

当预览标题中没有集数时，FeedDock 使用 `E01` 作为明确标注的演示值。真实下载不会使用该演示值；只有成功识别 RSS 集数后才生成自动改名目标。

## 5. qBittorrent 安全重命名

FeedDock 不直接对活动任务执行系统 `mv`。它使用 qBittorrent WebUI API：

- 添加任务并传递 `savepath`、`rename`、唯一 `tags`；
- 查询标签对应任务及下载进度；
- 获取种子内部文件列表；
- 单视频任务通过 `renameFile` 改名；
- 同目录、同原文件名前缀的字幕同步改名；
- 多视频合集标记为 `manual_required`，不猜测集数。

## 6. 总集数

- TMDB：优先读取所选季度 `episodes` 数量；必要时读取季度汇总字段；
- Bangumi：读取条目话数，缺失时回退到 episode API 总数；
- 手动锁定：`total_episodes_locked=true` 后不被同步覆盖。

## 7. 下载完成后状态检查

新订阅默认 `scrape_enabled=false`。后台每 2 分钟检查带 FeedDock 标签的 qBittorrent 任务：

1. 读取进度；
2. 必要时执行安全重命名；
3. 进度达到 100% 后记录完成时间；
4. 同步外部元数据并写入剧集/电影 NFO、海报和背景图；
5. 记录刮削文件列表和完成状态；
6. 由媒体服务器扫描目录并读取旁车文件。

## 8. 权限

飞牛默认以 `PUID=0`、`PGID=0` 运行。入口脚本不会递归修改整个媒体库，只检查 `/data` 与 `/media` 是否可写。需要非 root 运行时，必须保证所选 UID/GID 对宿主机挂载目录具备读写权限。

## 9. 清理策略

“清理最近条目”只设置隐藏标记，保留 `subscription_id + fingerprint` 唯一记录，因此旧 RSS 条目不会重复下载。“清理系统日志”会真实删除日志表中的当前记录。

## 10. 限制

- 多视频合集仍需要人工确认每个文件对应的集数；
- Bangumi 与 TMDB 的季度划分可能不同，保存前应确认季编号和总集数；
- FeedDock 不下载或分发媒体，只处理用户配置的 RSS、下载器任务和本地元数据。

## 元数据刷新与自动刮削

1.17.7 允许 qBittorrent 下载根目录与 FeedDock 本地媒体挂载目录不同，并在每张订阅卡片提供单独“刮削”入口。路径映射说明见 本文“下载路径映射”章节。

## 三个独立动作

顶部“刷新”菜单包含：

- **刷新全部订阅**：读取启用订阅的 RSS，执行匹配、去重和下载器推送；
- **同步订阅元数据**：只更新 FeedDock 数据库中的标题、简介、评分、海报地址、总集数和关联 ID；
- **刮削已完成媒体**：为所有已完成下载向实际媒体目录写入 NFO 和图片，适合升级后的历史补写。

三个动作互不替代。仅执行“同步订阅元数据”不会在媒体目录生成文件。

## 下载完成后自动刮削

该选项默认开启。下载完成检查按以下顺序执行：

1. 确认 qBittorrent 任务真实存在并达到 100%；
2. 在元数据过期时同步 TMDB、Bangumi 或 AniList；
3. 将 NFO 与图片写入条目实际保存目录；
4. 如启用 `bangumi.ini`，在番剧根目录追加写入 Bangumi ID；
5. 将 FeedDock 条目的刮削状态记录为完成或错误。

元数据同步或本地写入失败不会把下载任务改回下载失败。下载仍保持完成，刮削状态会显示错误，并可通过“检查下载完成”或“刮削已完成媒体”重试。

## 写入内容

电视番剧：

```text
番剧目录/
├── tvshow.nfo
├── poster.jpg|png|webp
├── fanart.jpg|png|webp
├── season01-poster.jpg|png|webp
├── .feeddock-scrape.json
└── Season 01/
    ├── season.nfo
    ├── poster.jpg|png|webp
    ├── 番剧名 - S01E01.mkv
    └── 番剧名 - S01E01.nfo
```

电影：

```text
电影目录/
├── movie.nfo
├── 电影文件.nfo
├── poster.jpg|png|webp
├── fanart.jpg|png|webp
└── .feeddock-scrape.json
```

NFO 包含可用的标题、原始标题、简介、年份、首播日期、评分，以及 TMDB、Bangumi、AniList 唯一 ID。剧集 NFO 还包含季号、集号和发布日期。

## 安全边界

- 下载目录必须位于设置中的统一媒体根目录；越界路径会拒绝写入；
- 使用临时文件、`fsync` 和原子替换，降低中断造成半文件的风险；
- 图片响应必须是图片类型，单张最大 25 MiB；
- 已存在的图片会复用，避免每一集完成后重复下载；
- FeedDock 不删除视频、字幕或用户已有的其它元数据文件；
- FeedDock 不直接修改媒体服务器数据库，写入后需要媒体服务器自动或手动扫描目录。

## 升级行为

本版本不增加数据库列。首次从旧版本启动时，会把所有已完成条目一次性标记为等待本地刮削；自动刮削开启时由后台逐批补写，也可以手动点击“刮削已完成媒体”。

## 本地媒体旁车文件

## 为什么 1.17.4 没有文件

1.17.4 的“自动刮削”只调用元数据服务，并将结果保存在 SQLite 的订阅字段中。旧 `app/scraper.py` 明确返回“已移除本地 NFO/图片刮削”，因此媒体目录不会出现 NFO、海报或背景图。

1.17.5 恢复了受媒体根目录约束的本地旁车文件写入；1.17.7 增加 qBittorrent 路径到 FeedDock 本地挂载路径的映射。

## 路径要求

qBittorrent 和 FeedDock 必须访问同一个宿主机目录，但容器内路径可以不同。例如：

```yaml
qBittorrent 下载根目录：/vol2/1000/影视
FeedDock volumes：/vol2/1000/影视:/media
FeedDock 本地媒体挂载目录：/media
```

FeedDock 会保留 qBittorrent 根目录下面的相对路径并拼接到 `/media`。例如 `/vol2/1000/影视/Show/Season 01` 会映射为 `/media/Show/Season 01`。映射后仍执行根目录越界保护。

## 自动流程

```text
qBittorrent 下载完成
→ 同步外部元数据（如到期）
→ 定位媒体目录和实际视频文件
→ 写入剧集/电影 NFO
→ 下载或复用海报与背景图
→ 记录 .feeddock-scrape.json
→ 更新条目刮削状态与日志
```

## 历史任务补写

升级后选择：

```text
刷新 → 刮削已完成媒体
```

任务会遍历 FeedDock 中所有带 `completed_at` 的下载条目。清理过页面历史的条目仍保留去重记录并可以补写。

每张订阅卡片也提供“刮削”按钮，只处理当前订阅的已完成条目。

## 媒体服务器扫描

NFO 与图片落盘后，飞牛影视、Emby、Jellyfin、Kodi 等仍需扫描媒体目录。FeedDock 当前不会直接调用媒体服务器的刷新 API，以避免把某一种媒体服务器变成强依赖。

## 日志

成功日志包含订阅 ID、条目 ID、媒体目录和生成文件列表；失败日志会明确指出路径不存在、目录越界、图片请求失败或文件写入失败。日志不会包含 RSS Passkey、磁力链接或下载器密码。

## 目录命名

默认目录采用 `名称 (年份)`，例如 `金牌得主 (2025)/Season 02`。TMDB、Bangumi 和 AniList ID 写入 NFO，不附加到目录名。已有目录不会自动重命名。

## 媒体库去重、卫生与更新

## 下载前媒体去重

FeedDock 在调用 qBittorrent 前，会把任务保存路径从 qBittorrent 路径映射到 FeedDock 本地媒体挂载路径，并在该目录内检查目标视频：

1. 精确匹配规范命名后的文件名；
2. 启用“文件已下载自动跳过”时，再使用 `SxxExx` 集数标记作保守匹配；
3. 最多扫描两级子目录和 5000 个文件；
4. 命中后把条目标记为“已跳过”，不会调用 qBittorrent。

精确目标文件检查属于安全保护，即使旧配置中“自动跳过”关闭也会执行；开关控制较宽松的集数标记匹配。

## 无视频时清理 NFO 与图片

自动或手动刷新订阅时，FeedDock 会检查该订阅已经完成且曾刮削的媒体目录。如果目标季目录已经没有视频文件，会删除 FeedDock 生成的：

- `season.nfo`；
- 与剧集同名的 `.nfo`；
- 季海报。

如果整个剧集或电影目录都没有任何视频，还会删除：

- `tvshow.nfo` / `movie.nfo`；
- `poster.*`、`fanart.*`、`season*-poster.*`；
- `.feeddock-scrape.json`。

不会删除视频、字幕或任意其它用户文件。清理范围受媒体根目录限制，并优先依据 FeedDock 刮削清单。即使 RSS 总开关关闭，手动检查订阅也会先执行本地清理，再跳过网络请求。

## 容器镜像更新检查

FeedDock 直接读取 `FEEDDOCK_IMAGE` 指向标签的 OCI manifest 和镜像 config，例如：

```dotenv
FEEDDOCK_IMAGE=ghcr.io/planeteditorx/feeddock:latest
UPDATE_CHECK_CACHE_HOURS=6
```

检查过程会：

- 按 OCI/Docker Registry V2 协议读取远端 manifest；
- 多架构镜像会选择当前运行平台的 config；
- 读取 `org.opencontainers.image.version`；
- 读取 `org.opencontainers.image.revision`；
- 记录远端 manifest digest 和平台 digest；
- 使用当前镜像的 `APP_REVISION` 与远端 revision 判断是否存在更新；
- 非手动检查时使用数据库缓存，默认 6 小时。

该流程不需要 `update.json`，也不调用 GitHub Release API。公开 GHCR 镜像可通过仓库认证挑战获取匿名只读 Token。

首次部署包含该能力的镜像后，后续镜像都会带有完整 revision。旧镜像缺少 `APP_REVISION` 时，会暂时回退到镜像版本比较；完成一次更新后即可使用精确 revision 判断。

## 在线更新

网页会显示“在线更新”或“配置在线更新”。真正替换 Docker 镜像需要 Watchtower HTTP API：

```dotenv
WATCHTOWER_URL=http://watchtower:8080
WATCHTOWER_TOKEN=至少32位随机字符串
```

未配置 Watchtower 时，FeedDock 仍能检查远端镜像版本、revision 和 digest，但不会直接修改正在运行的容器。

## 下载路径映射

## 问题原因

qBittorrent 返回的保存目录属于 **qBittorrent 所在环境**。在飞牛 OS 上，它可能是：

```text
/vol2/1000/影视/番剧名称 (2026)/Season 01
```

但 FeedDock 容器通常将同一宿主机目录挂载为：

```text
/media/番剧名称 (2026)/Season 01
```

1.17.6 及更早版本错误地要求两个路径字符串完全相同，因此即使宿主机目录真实存在，FeedDock 容器仍会报告“下载目录不存在”。

## 1.17.7 的映射规则

配置：

```text
qBittorrent 下载根目录：/vol2/1000/影视
FeedDock 本地媒体挂载目录：/media
```

条目保存路径：

```text
/vol2/1000/影视/感谢对战。～大小姐才不玩格斗游戏～ (2026)/Season 01
```

FeedDock 会保留相对部分并映射为：

```text
/media/感谢对战。～大小姐才不玩格斗游戏～ (2026)/Season 01
```

映射后的路径仍必须位于 FeedDock 本地媒体挂载根目录内，避免通过路径模板写入容器其他位置。

## 飞牛 Compose 示例

```yaml
services:
  feeddock:
    environment:
      DOWNLOAD_PATH: "/vol2/1000/影视"
      MEDIA_LOCAL_ROOT: "/media"
    volumes:
      - "/vol2/1000/影视:/media"
```

如果 qBittorrent 也在 Docker 中，推荐两个容器都挂载为 `/media`；如果 qBittorrent 使用宿主机路径或另一容器路径，则分别填写实际路径即可。

## 单订阅刮削

每张订阅卡片新增“刮削”按钮。点击后只处理该订阅中 `completed_at` 已存在的下载条目：

1. 必要时同步外部元数据；
2. 映射 qBittorrent 保存路径到 FeedDock 本地路径；
3. 写入 `tvshow.nfo`、`season.nfo`、剧集同名 NFO；
4. 写入或复用海报和背景图；
5. 更新条目刮削状态并记录系统日志。

如果订阅没有已完成条目，接口会返回明确提示，不会启动空任务。

## 升级迁移

旧版本曾把 `media_local_root` 强制覆盖成 qBittorrent 下载路径。1.17.7 首次启动时，如果检测到该旧值仍与 qBittorrent 根目录相同，并且 Compose 配置了不同的 `MEDIA_LOCAL_ROOT`，会自动恢复 Compose 中的本地挂载路径。

## 媒体挂载路径自动识别

## 问题

飞牛宿主机和不同容器看到的路径可能不同：

```text
qBittorrent / 宿主机：/vol2/1000/影视
FeedDock 容器：       /media
```

如果自定义 Compose 只配置了：

```yaml
volumes:
  - "/vol2/1000/影视:/media"
```

但没有显式设置 `MEDIA_LOCAL_ROOT`，旧版本可能把 qBittorrent 的 `/vol2/1000/影视` 保存为 FeedDock 本地路径。FeedDock 随后会在自己的容器中检查 `/vol2/...`，即使宿主机目录真实存在，也会报告目录不存在。

## 1.17.10 行为

- 容器内媒体挂载目录默认使用 `/media`；
- `MEDIA_LOCAL_ROOT` 未填写时也不会再退回 qBittorrent 路径；
- 检测到数据库中的本地路径与 qBittorrent 根目录同为 `/vol*`、`/mnt*`、`/share*` 等宿主机路径时，会自动恢复为 `/media`；
- 已经完成的 1.17.7 迁移不会阻止本次修复；
- 运行时还有一层自修复，即使迁移记录异常，刮削仍使用正确的容器路径；
- 裸机或测试环境若确实让两个进程使用相同普通路径，不会被强制改成 `/media`。

## 推荐 Compose

```yaml
environment:
  DOWNLOAD_PATH: "/vol2/1000/影视"
  MEDIA_LOCAL_ROOT: "/media"
volumes:
  - "/vol2/1000/影视:/media"
```

若 qBittorrent 配置是在网页中保存，Compose 中的 `DOWNLOAD_PATH` 可保持默认；关键是 FeedDock 容器内挂载点必须是 `/media`。

升级后，在“设置 → 刮削设置”中应看到：

```text
qBittorrent 根目录 /vol2/1000/影视 → FeedDock /media
```

## 默认目录命名

默认电影和剧集目录现在统一采用：

```text
名称 (年份)
```

电视剧示例：

```text
金牌得主 (2025)/Season 02
```

电影示例：

```text
电影名称 (2026)
```

TMDB ID 不再附加为 `[tmdbid=123]`。它仍保存在 FeedDock 数据库和 NFO 的 `uniqueid` 字段中，因此不会影响媒体识别。

为了保护 qBittorrent 做种路径和现有媒体库索引，升级不会自动重命名已经存在的目录。新任务和重新计算保存路径的任务会使用新格式。用户自定义模板仍可显式使用 `{tmdb_id}`。
