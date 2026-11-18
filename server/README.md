# 账号与授权中心服务器

## 本地开发

```bash
cd 工程影像
pip install -r server\requirements.txt
set ALBUM_SERVER_PRIVATE_KEY=你的服务器授权私钥路径

# 创建管理员（或用环境变量 ALBUM_ADMIN_USER / ALBUM_ADMIN_PASS 自动创建）
python -m server.app create-admin --username admin --password 你的强密码

# 启动（默认 127.0.0.1:5000）
python -m server.app
```

## 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/register | 客户注册 {username, password, display_name} |
| POST | /api/login | 桌面登录，返回 Bearer 令牌；`account.id` 是稳定数字账号 ID |
| GET | /api/me | 当前账号与授权状态；返回与登录相同的 `account.id` |
| POST | /api/activate | 绑定本机，返回授权码和机器限定 `desktop_sync_token` |
| GET | /api/product-config | 免费版、价格、邀请和云预览统一配置 |
| POST | /api/client-errors | 客户端脱敏错误上报 |
| GET | /api/check-update | 查询最新版本、下载地址、大小和 SHA-256 |
| GET | /api/admin/accounts | 管理后台列表（管理员） |
| POST | /api/admin/license | 开通/续期 {account_id, license_type, valid_days, machine_limit} |
| POST | /api/admin/revoke | 吊销 {account_id} |
| POST | /api/admin/unbind | 解绑机器 {account_id, machine_id} |

移动端接口使用 `/api/mobile/v1`，桌面增量同步使用 `/api/desktop/v1`。完整字段
契约见仓库 `docs/移动端API-v1.md`。手机上传静态 JPEG/PNG 原字节，单文件硬上限
50MiB；客户端 `<=8MiB` 走直传（服务端直传硬上限 10MiB），更大文件走固定
4MiB 分片续传。服务端逐片和整图校验 SHA-256/实际大小/账号/冻结目标机器，并完整解码后
生成永久 JPEG 预览（最长边 1920、严格不超过 102400 字节）。移动端启动、图库、
详情和批次接口只签名返回预览，绝不返回原图地址。目标电脑确认落盘后先记录
`desktop_imported`，再删除中转原图；失败标记 `cleanup_pending` 并由重复 ACK 重试。
微信登录令牌显式标记 `scope=mobile`，无法访问 `/api/desktop/v1`；
桌面同步必须使用 `/api/activate` 签发的机器限定令牌，普通登录令牌也会被桌面 v1 接口拒绝。

## 生产部署（Ubuntu 22.04）

`account.id` 是数据库主键：用户名、显示名或密码改变时不会变化。新增该字段不删除
旧版客户端使用的 `username/display_name/role`，因此旧客户端可继续工作；工程管理系统
应把 `account.id` 当作外部身份 subject，不应把显示名当账号主键。

见 `deploy/` 目录。首次部署（公网地址不是秘密，但必须显式传入，防止 nginx
落到错误的默认站点）：

```bash
sudo ALBUM_PUBLIC_HOST=<公网IPv4> bash deploy/deploy.sh
```

已有正式服务优先走根目录 `deploy_auth.py` 的备份、副本迁移验证和回滚流程。
服务固定为单进程 4 线程 gunicorn；
RapidOCR 由进程内锁限制为单并发；HTTP 请求仍可由其它线程处理。
识别接口只快速返回 202 job，客户端轮询任务；新进程启动时会把旧进程遗留的
queued/running 任务立即安全恢复为人工确认；运行中的任务由独立周期心跳续租，
即使单张 OCR 较慢也不会被轮询误判超时。
分片临时区位于 `ALBUM_MOBILE_CHUNK_DIR`，默认在数据目录下，
具有 TTL、每账号/全局活跃会话数与预留字节上限。清理结果持久化为
`pending/cleaned`；失败目录在后续请求中周期重试，且 `pending` 始终占用配额，
避免清理故障演变成无界磁盘占用。

`deploy.sh` 会按以下顺序执行：

1. 生成或迁移 `/etc/album-auth/album-auth.env`，权限固定为 `root:www-data 0640`；
2. 先用 SQLite 在线备份并做 `quick_check`，再备份代码、systemd 和 nginx；
3. 在灰度目录安装依赖和编译检查，通过后原子切换代码；
4. `/api/me = 401` 且 `/api/product-config = 200` 才算成功，否则自动恢复旧代码；
5. 已有 nginx 配置原样保留，首次部署才安装 HTTP/ACME 模板。

真实令牌密钥、邮箱授权码、管理员初始密码和授权私钥都不在仓库或 service 文件中。
首次部署会生成强随机令牌密钥；旧 service 若存在内联密钥，脚本会无输出地迁移它，
避免无意中让现有登录全部失效。邮件配置由管理员用 `sudoedit` 加入受限文件：

```text
# /etc/album-auth/album-auth.env（示意字段名，不要把真实值提交仓库）
ALBUM_MAIL_HOST=
ALBUM_MAIL_PORT=
ALBUM_MAIL_USER=
ALBUM_MAIL_PASS=
```

### 为公网 IP 启用 HTTPS

公网 IP 证书必须使用 Certbot 5.4+ 的 webroot `--ip-address` 和 Let's Encrypt
`shortlived` 配置（证书约 6 天，所以自动续期是硬性要求）。先确认安全组/防火墙开放
80 和 443，再执行。具体参数依据 [Let's Encrypt 官方 IP 证书说明](https://letsencrypt.org/2026/03/11/shorter-certs-certbot/)：

```bash
sudo bash /opt/album-auth/server/deploy/enable-https-ip.sh \
  <公网IPv4> <证书通知邮箱>
```

脚本先在隔离目录申请 staging 证书，成功后才申请正式证书、备份 nginx 并打开 443；
若 nginx 或 HTTP/HTTPS 健康检查失败，会恢复原配置。80 端口不会跳转，旧版 HTTP
客户端仍可使用；新系统使用 `https://<公网IPv4>`。脚本同时安装续期 reload hook，
由 snap Certbot 定时器自动续期并让 nginx 重新载入证书。

### 备份和回退

```bash
# 一致性数据库备份（保留全部历史副本；空间不足时停止）
sudo bash /opt/album-auth/server/deploy/backup.sh

# 回退到已经核实完整性的代码快照
sudo bash /opt/album-auth/server/deploy/rollback.sh \
  /opt/album-auth/backups/deploy-<UTC时间>
```

每日备份在独占目录内生成并校验 SQLite 副本；同秒重试不会覆盖已有副本。历史
`ALBUM_BACKUP_RETENTION_DAYS` 环境变量已不再生效，现有 cron 可以保持原样，
脚本不再删除过期备份。它只备份数据库，不代替原片、预览图、分块和桌面资料的
独立备份。运行前必须确认 `ALBUM_BACKUP_DB` 或默认路径确实指向当前数据库。

手动代码回退只处理固定白名单文件；`server/data` 和外部数据目录、所有影像及
部署控制文件保持原地不动。它先在新的 `pre-rollback-*` 目录独占保存当前和目标
代码及哈希，再停止服务、切换代码并检查健康。切换或健康检查失败时恢复本次保存
的当前代码，不把旧数据库或影像覆盖回来；恢复失败会明确停止并报告快照路径。

目标备份必须是 `backups` 下直接的 `deploy-*` 目录，并包含完整的
`runtime/.snapshot-ready` 标记。缺少该标记的旧 `deploy.sh` 快照无法确定根运行
文件是否齐全，会在停服前拒绝。回退不会执行备份脚本或安装依赖；目标依赖清单
须与当前一致，且已安装的直接和间接依赖须通过只读检查。数据库恢复仍须单独
停服、核实业务影响并保留当前数据，不能用代码回退替代。

首次签发证书时可使用 `nginx-bootstrap.conf`；证书就绪后安装
`nginx-domain.conf`。正式 API 域名固定为 `https://api.shuiliyingxiang.cn`，nginx 请求体
上限为 52MiB（总原图硬上限 50MiB；直传端点硬上限 10MiB），上传链路的 nginx
connect/read/send 超时为有限的 240 秒，gunicorn 为 300 秒。微信公众平台的
request、uploadFile、downloadFile 合法域名都填写该 API 域名。手机端 100KB
预览统一经 API 同域代理读取私有 OSS，不再要求把 Bucket 主机加入小程序合法域名。
原图 Bucket 签名地址只供电脑端使用，也不加入小程序合法域名。

### 完全隔离的 staging

```bash
sudo bash deploy/deploy-staging.sh
```

staging 使用独立的 `/opt/album-auth-staging`、`/var/lib/album-auth-staging/staging.db`、
本地对象目录、systemd 服务 `album-auth-staging` 和端口 `18080`，不会重启或读写
正式服务。可选 nginx 模板为 `nginx-staging.conf`。微信和 OSS 测试配置只通过
`/etc/album-auth-staging/mobile.env` 注入，并且必须使用测试小程序和测试 Bucket。

部署脚本会创建专用 Unix 用户 `album-auth-staging`、独立 Ed25519 授权私钥、
root-only 数据库备份，并拒绝 staging 路径/unit 的符号链接、硬链接、未知
systemd drop-in 和并发部署。unit 通过文件系统沙箱隐藏 `/opt/album-auth`、
`/etc/album-auth`、`/var/lib/album-auth`；数据库、私钥、对象和分片路径由
`ExecStart=/usr/bin/env ...` 最终锁定，不能被环境文件重定向。

`server.env` 只允许 `ALBUM_SERVER_SECRET`。`mobile.env` 只允许脚本列出的微信、
移动端限额和 OSS 变量，并采用不带引号的单行 `KEY=VALUE`。启用微信或 OSS 前，
必须先在 `/etc/album-auth-staging/staging-policy.env` 精确钉住测试 AppID、原图桶和
预览桶，并登记正式 AppID 及全部正式 Bucket 作为拒绝清单；缺少拒绝清单、测试资源
与正式资源相同，或 Bucket 名不含 `staging`/`test` 时，服务都会拒绝启动。这些
配置/密钥文件均为 `root:album-auth-staging 0640`，不得复制正式环境文件。

迁移验证器只接受稳定 SQLite backup 副本，并要求显式指定专用安全根目录：

```bash
sudo install -d -m 0700 /var/backups/album-auth-staging/validation
sudo python validate_mobile_migration.py \
  --source /var/backups/album-auth-staging/source.sqlite3 \
  --copy /var/backups/album-auth-staging/validation/run-1.sqlite3 \
  --copy-root /var/backups/album-auth-staging/validation
```

验证器使用排他创建和 `0600` 权限，不覆盖已有副本，不接受在线代码/数据目录，
并注入仅存在于进程内的一次性 secret，绝不在验证目录生成 `.server_secret`。
迁移副本只用来证明旧库可安全增量升级，不安装进 staging；隔离联调使用新建的
空测试数据库和一次性测试账号，避免真实账号资料进入测试服务。

`main` 分支推送会启动正式发布。凭据仅注入 Runner 临时目录，任务结束即清理。
`deploy_auth.py` 只接受现有 systemd、nginx、cron 与本次模板完全一致且 nginx
链接正确、systemd 没有待重载变更的环境；检查在任何远端写入前及代码替换前各
执行一次。差异即停止，本流程不安装、覆盖或重载这些配置。

发布先确认磁盘空间，再保存代码和 SQLite 一致性备份；仅在独占副本验证数据库
迁移、旧表行数和完整性。历史部署快照、安装包备份及每日数据库副本均不自动
清理，空间不足时停止。依赖步骤只核验现有解释器的实际包版本和间接依赖，并
保存校验凭据；不执行 `pip install`，缺包或版本不兼容需独立处理。重启后的接口
及 HTTPS 健康检查失败时，仅恢复白名单代码并再次检查服务，不还原旧业务数据。

## 安全要点

1. `private_key.pem` 只放服务器（`/etc/album-auth/private_key.pem`，`root:www-data 0640`），
   离线加密备份一份，绝不进入安装包；
2. `ALBUM_SERVER_SECRET` 只放 `/etc/album-auth/album-auth.env`，不进入仓库或 systemd unit；
3. 服务器防火墙只开放 80/443/SSH；
4. `ALBUM_WECHAT_APP_SECRET` 只放服务器环境文件，不保存微信临时 code 或明文密码；
5. 生产 OSS 必须使用两个不同的私有 Bucket：`ALBUM_OSS_ORIGINAL_BUCKET` 是原图
   中转桶，开启服务端加密、关闭版本控制并设置短期生命周期兜底；
   `ALBUM_OSS_PREVIEW_BUCKET` 是永久预览桶，开启服务端加密和版本控制且不自动
   删除。普通 delete 在版本化 Bucket 只写删除标记，因此禁止把原图放进预览桶；
6. ECS RAM 角色分别授予两个 Bucket 的最小权限，不在代码、数据库或记忆中保存
   AccessKey。其它变量为 `ALBUM_MOBILE_STORAGE_BACKEND=oss`、`ALBUM_OSS_REGION`、
   `ALBUM_OSS_ENDPOINT`；旧 `ALBUM_OSS_BUCKET` 仅作为预览桶名称的兼容别名，原图
   桶必须显式配置且不能与预览桶同名；
7. `desktop_machine_id` 必须是当前账号 `machines.active=1` 的电脑。工程快照保存该
   ID，批次创建时冻结为 `target_machine_id`，inbox 按账号+目标机器精确过滤；
8. 未配置 OSS 的 staging 仅使用 `ALBUM_MOBILE_STORAGE_DIR` 受控目录。电脑端既有
   原图不由 backfill 修改或上传，backfill 只接收 `<=102400` 字节 JPEG 预览。
9. gunicorn 仅监听 127.0.0.1 并只信任单层本机 nginx 的转发头；微信登录/绑定与
   旧登录共用按真实客户端 IP 的短窗限流，禁止把 gunicorn 端口直接暴露公网。
10. 微信 `mobile` 令牌不能调用任何桌面接口；`desktop_sync_token`
    同时校验账号、claims 内的机器 ID 和 `machines.active=1`，且仅能访问
    `/api/desktop/v1`，不能进入移动、管理员或旧云预览写接口。
11. 分片 init 受按 IP 短窗限流；临时片按账号/批次/UUID 隔离并在完成、失败、
    取消或过期时清理。发布前确认 `ALBUM_MOBILE_CHUNK_DIR` 位于有容量监控的独立
    staging/生产数据目录，不能与另一环境共用。
12. EnvironmentFile、数据库备份目录权限须保持受限；移动原图只作短期中转，
    电脑归档确认后删除，永久预览与账号数据按 `account.id` 隔离。
