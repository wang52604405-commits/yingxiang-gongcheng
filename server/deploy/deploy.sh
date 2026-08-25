#!/usr/bin/env bash
# 部署脚本（Ubuntu 22.04，需 root）
set -euo pipefail

APP_DIR=/opt/album-auth
# 源目录 = 本脚本所在 deploy/ 的上一级，即 Python 的 server 包目录。
SRC_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SERVER_DIR="$APP_DIR/server"
DATA_DIR="$APP_DIR/data"

# 此脚本只用于空机首次安装。已有服务/数据库必须走根目录
# deploy_auth.py 的「在线备份 -> 副本迁移验证 -> 可回滚替换」流程。
if systemctl cat album-auth.service >/dev/null 2>&1 || [ -e "$DATA_DIR/server.db" ]; then
    echo "检测到已有正式服务或数据库，拒绝用首安脚本覆盖。" >&2
    echo "请使用 deploy_auth.py，或使用 deploy-staging.sh 部署隔离测试环境。" >&2
    exit 1
fi

apt-get update
apt-get install -y python3-venv nginx certbot python3-certbot-nginx sqlite3

mkdir -p "$SERVER_DIR" "$DATA_DIR/mobile_objects" "$DATA_DIR/mobile_chunks" /etc/album-auth
# 保留 server/ 包这一层，使 WorkingDirectory=/opt/album-auth 下可导入 server.app。
cp -a "$SRC_DIR/." "$SERVER_DIR"/

python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/server/requirements.txt"

# 权限：服务以 www-data 运行，私钥与数据目录必须可读可写
if [ -f /etc/album-auth/private_key.pem ]; then
    chown root:www-data /etc/album-auth/private_key.pem
    chmod 640 /etc/album-auth/private_key.pem
fi
chown -R www-data:www-data "$DATA_DIR"

# SECRET 只存在服务器环境文件，不写入代码或 systemd 模板。
if [ ! -s /etc/album-auth/server.env ]; then
    umask 027
    printf 'ALBUM_SERVER_SECRET=%s\n' "$(openssl rand -hex 32)" > /etc/album-auth/server.env
fi
chown root:www-data /etc/album-auth/server.env
chmod 640 /etc/album-auth/server.env

cp "$SERVER_DIR/deploy/album-auth.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable album-auth
systemctl restart album-auth

if [ -s /etc/letsencrypt/live/api.shuiliyingxiang.cn/fullchain.pem ] && \
   [ -s /etc/letsencrypt/live/api.shuiliyingxiang.cn/privkey.pem ]; then
    cp "$SERVER_DIR/deploy/nginx.conf" /etc/nginx/sites-available/album-auth
else
    cp "$SERVER_DIR/deploy/nginx-bootstrap.conf" /etc/nginx/sites-available/album-auth
fi
ln -sf /etc/nginx/sites-available/album-auth /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx

echo "请把私钥放到 /etc/album-auth/private_key.pem"
echo "（已自动设置属主 root:www-data，权限 640）"
echo "首次部署可执行：certbot certonly --webroot -w /var/www/html -d api.shuiliyingxiang.cn"
echo "证书签发后复制 deploy/nginx.conf 并执行 nginx -t && systemctl reload nginx。"
