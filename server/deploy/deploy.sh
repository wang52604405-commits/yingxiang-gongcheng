#!/usr/bin/env bash
# Ubuntu 22.04/24.04 授权中心部署：保留密钥、先备份、失败自动回滚。
set -Eeuo pipefail

APP_DIR=/opt/album-auth
CODE_DIR="$APP_DIR/server"
DATA_DIR="$APP_DIR/data"
CONFIG_DIR=/etc/album-auth
ENV_FILE="$CONFIG_DIR/album-auth.env"
SERVICE_FILE=/etc/systemd/system/album-auth.service
NGINX_FILE=/etc/nginx/sites-available/album-auth
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER_SRC="$(cd "$SCRIPT_DIR/.." && pwd)"
PUBLIC_HOST="${ALBUM_PUBLIC_HOST:-_}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
STAGE_DIR="$APP_DIR/releases/deploy-$STAMP"
BACKUP_DIR="$APP_DIR/backups/deploy-$STAMP"
SWITCHED=0
OLD_CODE_BACKED_UP=0
NEW_CODE_ACTIVE=0

if [ "$(id -u)" -ne 0 ]; then
    echo "错误：请用 root 执行此脚本。" >&2
    exit 1
fi
if [[ ! "$PUBLIC_HOST" =~ ^[A-Za-z0-9._-]+$ ]]; then
    echo "错误：ALBUM_PUBLIC_HOST 只能是 IPv4、域名或下划线。" >&2
    exit 1
fi
if [ "$PUBLIC_HOST" = "_" ] && [ ! -f "$NGINX_FILE" ]; then
    echo "错误：首次部署必须通过 ALBUM_PUBLIC_HOST 显式提供公网 IPv4 或域名。" >&2
    exit 1
fi
if [ ! -f "$SERVER_SRC/app.py" ] || [ ! -f "$SERVER_SRC/requirements.txt" ]; then
    echo "错误：未找到完整的 server/ 源代码。" >&2
    exit 1
fi

restore_regular_file() {
    local backup_file="$1"
    local live_file="$2"
    if [ -f "$backup_file" ]; then
        install -m "$(stat -c %a "$backup_file")" "$backup_file" "$live_file"
    fi
}

rollback() {
    local exit_code=$?
    trap - ERR
    if [ "$SWITCHED" -eq 1 ] || [ "$OLD_CODE_BACKED_UP" -eq 1 ] || [ "$NEW_CODE_ACTIVE" -eq 1 ]; then
        echo "部署失败，正在恢复部署前版本……" >&2
        systemctl stop album-auth 2>/dev/null || true
        if [ "$NEW_CODE_ACTIVE" -eq 1 ] && [ -d "$CODE_DIR" ]; then
            mv "$CODE_DIR" "$STAGE_DIR/failed-server" 2>/dev/null || true
        fi
        if [ "$OLD_CODE_BACKED_UP" -eq 1 ] && [ -d "$BACKUP_DIR/server" ]; then
            mv "$BACKUP_DIR/server" "$CODE_DIR"
        fi
        restore_regular_file "$BACKUP_DIR/album-auth.service" "$SERVICE_FILE"
        restore_regular_file "$BACKUP_DIR/nginx.conf" "$NGINX_FILE"
        systemctl daemon-reload 2>/dev/null || true
        systemctl start album-auth 2>/dev/null || true
        nginx -t >/dev/null 2>&1 && systemctl reload nginx 2>/dev/null || true
        echo "已执行回滚；失败版本保留在 $STAGE_DIR 供排查。" >&2
    fi
    exit "$exit_code"
}
trap rollback ERR

echo "[1/7] 安装系统依赖并准备目录"
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y \
    python3-venv nginx sqlite3 rsync openssl curl
install -d -o root -g root -m 755 "$APP_DIR" "$APP_DIR/releases"
install -d -o root -g root -m 700 "$APP_DIR/backups" "$BACKUP_DIR"
install -d -o www-data -g www-data -m 750 "$DATA_DIR"
install -d -o root -g www-data -m 750 "$CONFIG_DIR"
install -d -o www-data -g www-data -m 755 /var/www/letsencrypt
install -d -o root -g root -m 755 "$STAGE_DIR/server"

echo "[2/7] 创建或验证受限 EnvironmentFile"
if [ ! -f "$ENV_FILE" ]; then
    # 从旧 service 迁移令牌/邮件配置，避免部署时无意轮换令牌、踢掉全部登录。
    legacy_value() {
        local key="$1"
        if [ -f "$SERVICE_FILE" ]; then
            sed -n "s/^Environment=\"${key}=\(.*\)\"$/\1/p" "$SERVICE_FILE" | head -n 1
        fi
    }
    write_legacy_or_default() {
        local key="$1"
        local default_value="$2"
        local current_value
        current_value="$(legacy_value "$key")"
        printf '%s=%s\n' "$key" "${current_value:-$default_value}"
    }
    legacy_secret="$(legacy_value ALBUM_SERVER_SECRET)"
    if [ -z "$legacy_secret" ]; then
        legacy_secret="$(openssl rand -hex 32)"
    fi
    env_tmp="$(mktemp "$CONFIG_DIR/.album-auth.env.XXXXXX")"
    {
        write_legacy_or_default ALBUM_SERVER_HOST 127.0.0.1
        write_legacy_or_default ALBUM_SERVER_PORT 8000
        write_legacy_or_default ALBUM_SERVER_DATA /opt/album-auth/data
        write_legacy_or_default ALBUM_SERVER_DB /opt/album-auth/data/server.db
        write_legacy_or_default ALBUM_SERVER_PRIVATE_KEY /etc/album-auth/private_key.pem
        printf 'ALBUM_SERVER_SECRET=%s\n' "$legacy_secret"
        for key in ALBUM_MAIL_HOST ALBUM_MAIL_PORT ALBUM_MAIL_USER ALBUM_MAIL_PASS; do
            value="$(legacy_value "$key")"
            if [ -n "$value" ]; then
                printf '%s=%s\n' "$key" "$value"
            fi
        done
    } > "$env_tmp"
    chown root:www-data "$env_tmp"
    chmod 640 "$env_tmp"
    mv "$env_tmp" "$ENV_FILE"
fi
chown root:www-data "$ENV_FILE"
chmod 640 "$ENV_FILE"
secret_line="$(sed -n 's/^ALBUM_SERVER_SECRET=//p' "$ENV_FILE" | tail -n 1)"
secret_line="${secret_line%\"}"
secret_line="${secret_line#\"}"
if [ "${#secret_line}" -lt 32 ]; then
    echo "错误：$ENV_FILE 中缺少至少 32 字符的 ALBUM_SERVER_SECRET。" >&2
    exit 1
fi
unset secret_line legacy_secret value
if [ -f "$CONFIG_DIR/private_key.pem" ]; then
    chown root:www-data "$CONFIG_DIR/private_key.pem"
    chmod 640 "$CONFIG_DIR/private_key.pem"
else
    echo "提醒：未发现授权签名私钥；登录可用，但付费授权签发前必须安全放入 $CONFIG_DIR/private_key.pem。"
fi

echo "[3/7] 备份数据库、代码和服务配置"
if [ -f "$DATA_DIR/server.db" ]; then
    sqlite3 "$DATA_DIR/server.db" ".backup '$BACKUP_DIR/server.db'"
    chmod 600 "$BACKUP_DIR/server.db"
    integrity="$(sqlite3 "$BACKUP_DIR/server.db" 'PRAGMA quick_check;')"
    if [ "$integrity" != "ok" ]; then
        echo "错误：部署前数据库备份校验失败。" >&2
        exit 1
    fi
fi
[ ! -f "$SERVICE_FILE" ] || cp -a "$SERVICE_FILE" "$BACKUP_DIR/album-auth.service"
[ ! -f "$NGINX_FILE" ] || cp -a "$NGINX_FILE" "$BACKUP_DIR/nginx.conf"
cp -a "$ENV_FILE" "$BACKUP_DIR/album-auth.env"
chmod 600 "$BACKUP_DIR/album-auth.env"

echo "[4/7] 灰度复制、依赖安装和静态检查"
rsync -a --delete \
    --exclude '__pycache__/' --exclude '*.pyc' --exclude 'data/' \
    --exclude '*.db' --exclude '*.pem' --exclude '.env' \
    "$SERVER_SRC/" "$STAGE_DIR/server/"
if [ ! -x "$APP_DIR/venv/bin/python" ]; then
    python3 -m venv "$APP_DIR/venv"
fi
"$APP_DIR/venv/bin/pip" install --disable-pip-version-check -r "$STAGE_DIR/server/requirements.txt"
cd "$STAGE_DIR"
"$APP_DIR/venv/bin/python" -m py_compile \
    server/app.py server/config.py server/db.py server/mailer.py

echo "[5/7] 原子切换代码并安装 systemd 模板"
if systemctl is-active --quiet album-auth; then
    systemctl stop album-auth
fi
for db_file in "$DATA_DIR/server.db" "$DATA_DIR/server.db-wal" "$DATA_DIR/server.db-shm"; do
    if [ -f "$db_file" ]; then
        chown www-data:www-data "$db_file"
        chmod 640 "$db_file"
    fi
done
if [ -f "$DATA_DIR/.server_secret" ]; then
    chown root:www-data "$DATA_DIR/.server_secret"
    chmod 640 "$DATA_DIR/.server_secret"
fi
if [ -d "$CODE_DIR" ]; then
    mv "$CODE_DIR" "$BACKUP_DIR/server"
    OLD_CODE_BACKED_UP=1
fi
mv "$STAGE_DIR/server" "$CODE_DIR"
NEW_CODE_ACTIVE=1
SWITCHED=1
install -o root -g root -m 644 "$CODE_DIR/deploy/album-auth.service" "$SERVICE_FILE"
systemctl daemon-reload
systemctl enable album-auth >/dev/null

echo "[6/7] 保留现有 nginx；首次部署仅安装 HTTP/ACME 配置"
if [ ! -f "$NGINX_FILE" ]; then
    sed "s/__PUBLIC_IP__/$PUBLIC_HOST/g" "$CODE_DIR/deploy/nginx-http.conf" > "$STAGE_DIR/nginx-http.conf"
    install -o root -g root -m 644 "$STAGE_DIR/nginx-http.conf" "$NGINX_FILE"
fi
ln -sfn "$NGINX_FILE" /etc/nginx/sites-enabled/album-auth
nginx -t

echo "[7/7] 启动并执行本机健康检查"
systemctl start album-auth
for _ in $(seq 1 20); do
    me_status="$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/api/me || true)"
    product_status="$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/api/product-config || true)"
    if [ "$me_status" = "401" ] && [ "$product_status" = "200" ]; then
        break
    fi
    sleep 1
done
if [ "${me_status:-}" != "401" ] || [ "${product_status:-}" != "200" ]; then
    echo "错误：健康检查失败（me=${me_status:-none}, product=${product_status:-none}）。" >&2
    false
fi
systemctl reload nginx
SWITCHED=0
trap - ERR
echo "部署成功。备份：$BACKUP_DIR"
echo "旧版 HTTP 保持可用；确认 80/443 防火墙后，再执行 enable-https-ip.sh。"
