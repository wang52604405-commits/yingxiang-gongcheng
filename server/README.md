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
| POST | /api/login | 登录，返回 Bearer 令牌 |
| GET | /api/me | 当前账号与授权状态 |
| POST | /api/activate | 客户端绑定本机并获取授权码 {machine_id} |
| GET | /api/product-config | 免费版、价格、邀请和云预览统一配置 |
| POST | /api/client-errors | 客户端脱敏错误上报 |
| GET | /api/check-update | 查询最新版本、下载地址、大小和 SHA-256 |
| GET | /api/admin/accounts | 管理后台列表（管理员） |
| POST | /api/admin/license | 开通/续期 {account_id, license_type, valid_days, machine_limit} |
| POST | /api/admin/revoke | 吊销 {account_id} |
| POST | /api/admin/unbind | 解绑机器 {account_id, machine_id} |

## 生产部署（Ubuntu 22.04）

见 `deploy/` 目录：

```bash
sudo bash deploy/deploy.sh
```

部署内容：安装依赖、gunicorn systemd 服务、nginx 反代、HTTPS 证书、每日数据库备份。

`main` 分支推送后，自托管 GitHub Actions 会从加密 Secrets 向 Runner 临时目录注入发布凭据，运行测试与发布契约检查，再把服务端上传到独立灰度目录；任务结束即清理临时凭据。部署脚本在替换线上代码前创建备份，重启后以 `/api/me = 401` 作为健康检查；失败时自动恢复上一版代码。

## 安全要点

1. `private_key.pem` 只放服务器（生产建议 `/etc/album-auth/private_key.pem`，chmod 600），
   离线加密备份一份，绝不进入安装包；
2. `ALBUM_SERVER_SECRET` 设置为强随机值；
3. 服务器防火墙只开放 80/443/SSH；
4. 客户数据只有账号/授权信息，照片仍在客户本地。
