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
| POST | /api/login | 桌面登录，返回 desktop Bearer 令牌 |
| GET | /api/me | 当前账号与授权状态 |
| POST | /api/activate | 绑定本机，返回授权码和机器限定 desktop_sync_token |
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

见 `deploy/` 目录：

```bash
sudo bash deploy/deploy.sh
```

该脚本只允许空机首次安装；检测到已有 service 或数据库会直接拒绝。
已有正式服务只能走根目录 `deploy_auth.py` 的备份、副本迁移验证和回滚流程。
首安内容包括依赖、单进程 4 线程 gunicorn 服务、nginx 反代和数据库目录。
RapidOCR 由进程内锁限制为单并发；HTTP 请求仍可由其它线程处理。
识别接口只快速返回 202 job，客户端轮询任务；新进程启动时会把旧进程遗留的
queued/running 任务立即安全恢复为人工确认；运行中的任务由独立周期心跳续租，
即使单张 OCR 较慢也不会被轮询误判超时。
分片临时区位于 `ALBUM_MOBILE_CHUNK_DIR`，默认在数据目录下，
具有 TTL、每账号/全局活跃会话数与预留字节上限。清理结果持久化为
`pending/cleaned`；失败目录在后续请求中周期重试，且 `pending` 始终占用配额，
避免清理故障演变成无界磁盘占用。

首次签发证书时部署脚本会使用 `nginx-bootstrap.conf`；证书就绪后切换到
`nginx.conf`。正式 API 域名固定为 `https://api.shuiliyingxiang.cn`，nginx 请求体
上限为 52MiB（总原图硬上限 50MiB；直传端点硬上限 10MiB），上传链路的 nginx
connect/read/send 超时为有限的 240 秒，gunicorn 为 300 秒。微信公众平台的
request/uploadFile 合法域名填该 API 域名。downloadFile 除 API 域名外，
还必须加入「永久预览 Bucket 实际返回的 HTTPS 主机或已绑定的预览
自定义域名」；具体主机在 Bucket 创建后确认，此项是真机发布阻塞项。
原图 Bucket 签名地址只供电脑端使用，不加入小程序合法域名。

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

`main` 分支推送后，自托管 GitHub Actions 会从加密 Secrets 向 Runner 临时目录注入发布凭据，运行测试与发布契约检查，再把服务端上传到独立灰度目录；任务结束即清理临时凭据。`deploy_auth.py` 在替换线上代码前通过 SQLite backup API 生成一致性备份，并调用 `validate_mobile_migration.py` 只在第二份副本上验证迁移、旧表行数和完整性。验证失败时不会替换线上代码。验证通过后安装 `album-auth-mobile-v1.conf` drop-in，只覆盖 gunicorn 的 `ExecStart` 为单 worker、4 线程，原服务的环境变量和密钥配置保持不变。重启后同时检查旧接口和移动端接口；失败时自动恢复上一版代码与 drop-in。

## 安全要点

1. `private_key.pem` 只放服务器（生产建议 `/etc/album-auth/private_key.pem`，chmod 600），
   离线加密备份一份，绝不进入安装包；
2. `ALBUM_SERVER_SECRET` 由部署脚本写入服务器专用环境文件，不进入仓库；
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
