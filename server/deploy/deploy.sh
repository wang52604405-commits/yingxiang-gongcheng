#!/usr/bin/env bash
# 部署脚本（Ubuntu 22.04，需 root）
set -euo pipefail

APP_DIR=/opt/album-auth
# 源目录 = 本脚本所在 deploy/ 的上一级（含 server/ 代码的仓库根），先转绝对路径
SRC_DIR="$(cd "$(dirname "$0")/.." && pwd)"

apt-get update
apt-get install -y python3-venv nginx certbot python3-certbot-nginx sqlite3

mkdir -p "$APP_DIR" /etc/album-auth
# 复制内容（"." 结尾避免已存在目标目录时产生嵌套：/opt/album-auth/album-auth-src/...）
cp -r "$SRC_DIR/." "$APP_DIR"/

python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/server/requirements.txt"

# 权限：服务以 www-data 运行，私钥与数据目录必须可读可写
if [ -f /etc/album-auth/private_key.pem ]; then
    chown root:www-data /etc/album-auth/private_key.pem
    chmod 640 /etc/album-auth/private_key.pem
fi
chown -R www-data:www-data "$APP_DIR/data" 2>/dev/null || true
mkdir -p "$APP_DIR/data"
chown www-data:www-data "$APP_DIR/data"

# 生成并写入强随机 SECRET（占位值会导致 config.py 拒绝启动）。
cp "$APP_DIR/deploy/album-auth.service" /etc/systemd/system/
sed -i 's|ALBUM_SERVER_SECRET=[^"]*|ALBUM_SERVER_SECRET='"$(openssl rand -hex 32)"'|' /etc/systemd/system/album-auth.service
systemctl daemon-reload
systemctl enable --now album-auth

cp "$APP_DIR/deploy/nginx.conf" /etc/nginx/sites-available/album-auth
ln -sf /etc/nginx/sites-available/album-auth /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx

echo "请把私钥放到 /etc/album-auth/private_key.pem"
echo "（已自动设置属主 root:www-data，权限 640）"
echo "然后执行：certbot --nginx -d api.你的域名.com"
