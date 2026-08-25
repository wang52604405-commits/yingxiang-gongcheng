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
| POST | /api/login | 登录，返回 Bearer 令牌；`account.id` 是稳定数字账号 ID |
| GET | /api/me | 当前账号与授权状态；返回与登录相同的 `account.id` |
| POST | /api/activate | 客户端绑定本机并获取授权码 {machine_id} |
| GET | /api/product-config | 免费版、价格、邀请和云预览统一配置 |
| POST | /api/client-errors | 客户端脱敏错误上报 |
| GET | /api/check-update | 查询最新版本、下载地址、大小和 SHA-256 |
| GET | /api/admin/accounts | 管理后台列表（管理员） |
| POST | /api/admin/license | 开通/续期 {account_id, license_type, valid_days, machine_limit} |
| POST | /api/admin/revoke | 吊销 {account_id} |
| POST | /api/admin/unbind | 解绑机器 {account_id, machine_id} |

## 生产部署（Ubuntu 22.04）

`account.id` 是数据库主键：用户名、显示名或密码改变时不会变化。新增该字段不删除
旧版客户端使用的 `username/display_name/role`，因此旧客户端可继续工作；工程管理系统
应把 `account.id` 当作外部身份 subject，不应把显示名当账号主键。

见 `deploy/` 目录。首次部署（公网地址不是秘密，但必须显式传入，防止 nginx
落到错误的默认站点）：

```bash
sudo ALBUM_PUBLIC_HOST=<公网IPv4> bash deploy/deploy.sh
```

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
# 一致性数据库备份（默认保留 30 天，最少允许 7 天）
sudo bash /opt/album-auth/server/deploy/backup.sh

# 回退到某次 deploy.sh 留下的代码版本
sudo bash /opt/album-auth/server/deploy/rollback.sh \
  /opt/album-auth/backups/deploy-<UTC时间>
```

代码回退前还会再保留当前代码，并执行编译、依赖和健康检查。`rollback.sh` 不自动
恢复数据库，因为那会抹掉部署之后的新注册和业务数据；数据库恢复必须在停服、确认
数据影响并另做当前库备份后人工执行。

`main` 分支推送后，自托管 GitHub Actions 会从加密 Secrets 向 Runner 临时目录注入发布凭据，运行测试与发布契约检查，再把服务端上传到独立灰度目录；任务结束即清理临时凭据。部署脚本在替换线上代码前创建备份，重启后以 `/api/me = 401` 作为健康检查；失败时自动恢复上一版代码。

## 安全要点

1. `private_key.pem` 只放服务器（`/etc/album-auth/private_key.pem`，`root:www-data 0640`），
   离线加密备份一份，绝不进入安装包；
2. `ALBUM_SERVER_SECRET` 只放 `/etc/album-auth/album-auth.env`，不放 systemd unit；
3. 服务器防火墙只开放 80/443/SSH；
4. EnvironmentFile、数据库备份目录权限须保持受限；
5. 客户数据只有账号/授权信息，照片仍在客户本地。
