# FeedDock 主备 RSS 与代理访问测试修复

此次修改基于上传的 FeedDock-1.17.77 源码，不删除订阅、下载任务或数据库。项目目录中的 `VERSION` 文件保留原内容；自定义本地镜像构建版本由构建参数指定。

## 修复范围

1. **代理设置 → 测试外部请求**：保留 Bangumi 测试，增加 Google (`https://www.google.com/generate_204`) 的真实 HTTP 访问测试。两个站点独立显示成功/失败和 HTTP 状态，并使用已保存的代理设置及“不使用代理”规则。DNS 诊断仍然独立展示，避免以 DNS 解析结果代替代理访问结果。
2. **RSS 候选弹窗 → 设为主/备用 RSS 并保存**：选择候选地址会立即保存到订阅数据库，关闭弹窗，提示保存结果并安排检查（仅在订阅已启用时）。不再只把地址填进被遮挡的编辑表单。订阅详情展示完整主备配置和最近一次成功读取的来源。
3. **独立测试主、备 RSS**：在编辑订阅的“RSS 来源”中添加两个检查入口，返回能否读取以及条目数量。这两个测试只读取已保存的地址，不推送下载，不改写订阅的历史错误状态。
4. **历史异常正确失效**：实际修改任一 RSS URL 后，立即清空只适用于旧地址的历史 RSS 错误、旧检查时间和旧使用来源，状态变为“待检查”。刷新完成后，成功显示启用状态；失败则显示针对新 RSS 的错误，不会把旧异常一直挂在卡片上。单纯修改名称不会掩盖真实 RSS 失败。
5. **主备选择逻辑**：主 RSS 可访问且包含条目时始终优先；主 RSS 失败或无条目才会尝试备用 RSS。系统记录最终实际使用的是主源还是备用源，方便确认是否发生过接管。
6. **后台检查回显**：保存 RSS 后会定期读取任务结果，更新订阅卡片；不必依赖人工刷新页面看状态变化。

## 部署须知

原有两个 Compose 文件使用公开仓库的预构建镜像并设置 `pull_policy: always`，**直接替换源代码后仅执行 `docker compose up -d` 不会使修复生效**。必须使用本地构建的镜像：

```bash
# 进入本 ZIP 解压后的项目目录，在有 Docker 构建能力的主机执行
# 提前备份数据库所在的 data 目录，不要删除已有的 .env、data、downloads 目录
docker build --build-arg APP_VERSION=local-rssfix -t feeddock:rssfix .

# 普通 Docker Compose
# 确保 .env 配置沿用现有实例（勿复制示例覆盖已有配置）
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d --no-deps feeddock

# 飞牛 OS 使用下面这条命令代替上一条
docker compose -f docker-compose.fnos.yml -f docker-compose.local.yml up -d --no-deps feeddock
```

`docker-compose.local.yml` 将目标镜像设为 `feeddock:rssfix`、禁止自动拉取覆盖，且关闭此实例的 Watchtower 自动更新。部署后强制刷新浏览器，核对保存的订阅数据是否正常。此过程只修改 FeedDock 服务，不主动重建 qBittorrent。数据库新增的 `last_rss_source` 字段通过启动时的兼容迁移自动创建；请保留迁移前的数据库备份。

## 验收方式

- 设置 → 代理设置 → 保存代理 → 测试外部请求：应分别看到 Bangumi 和 Google 的结果。Google 期望 HTTP 204，Bangumi 期望 HTTP 200。两项成功才表示两个目标均可访问。
- 订阅列表 → 更新 RSS → 设为备用 RSS 并保存：返回编辑界面后能看到保存成功提示；在“订阅详情”中可见备用 RSS 地址。
- 编辑订阅 → RSS 来源：点击“测试主 RSS”和“测试备用 RSS”，查看两者分别的访问结果。主源正常时备用源处于待命状态，不会被自动合并读取。
- 把之前故障的 RSS 替换为另一个地址并保存：旧“异常”立即消失，待检查完成后再根据新请求的实际结果判断是否异常。

## 自动化测试

`python -m unittest discover -s tests -q`：291 项测试执行通过，1 项跳过。`node --check app/static/app.js` 通过。这些为本地模拟/单元测试，并非已经对你的实际代理、RSS 站点或 NAS 容器完成了在线验证。
