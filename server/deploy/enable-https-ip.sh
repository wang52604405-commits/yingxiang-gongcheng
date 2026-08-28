#!/usr/bin/env bash
# 为公网 IPv4 申请 Let's Encrypt 6 天短期证书，并安全启用 443。
# 官方要求：Certbot >= 5.4、webroot、--ip-address、shortlived profile。
set -Eeuo pipefail

APP_DIR=/opt/album-auth
NGINX_HTTP_FILE=/etc/nginx/sites-available/album-auth
NGINX_HTTPS_FILE=/etc/nginx/sites-available/album-auth-ip-https
WEBROOT=/var/www/letsencrypt
CERTBOT=/snap/bin/certbot
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PUBLIC_IP="${1:-}"
EMAIL="${2:-}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_DIR="$APP_DIR/backups/tls-$STAMP"
STAGING_CONFIG=/var/lib/letsencrypt-staging/config
STAGING_WORK=/var/lib/letsencrypt-staging/work
STAGING_LOG=/var/log/letsencrypt-staging
HTTP_CHANGED=0
HTTPS_CHANGED=0
HTTPS_LINK_EXISTED=0
[ ! -L /etc/nginx/sites-enabled/album-auth-ip-https ] || HTTPS_LINK_EXISTED=1

if [ "$(id -u)" -ne 0 ]; then
    echo "错误：请用 root 执行。" >&2
    exit 1
fi
if [ -z "$PUBLIC_IP" ] || [ -z "$EMAIL" ]; then
    echo "用法：sudo bash enable-https-ip.sh <公网IPv4> <证书通知邮箱>" >&2
    exit 1
fi
python3 - "$PUBLIC_IP" <<'PY'
import ipaddress
import sys

value = ipaddress.ip_address(sys.argv[1])
if value.version != 4 or not value.is_global:
    raise SystemExit("错误：必须提供可公开验证的公网 IPv4。")
PY
if [[ ! "$EMAIL" =~ ^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$ ]]; then
    echo "错误：证书通知邮箱格式不正确。" >&2
    exit 1
fi
if [ ! -f "$SCRIPT_DIR/nginx.conf" ]; then
    echo "错误：缺少 nginx 模板，请从已部署版本的 server/deploy 目录执行。" >&2
    exit 1
fi
if [ ! -f "$NGINX_HTTP_FILE" ]; then
    echo "错误：未找到线上 nginx 配置，请先执行 deploy.sh。" >&2
    exit 1
fi

rollback_nginx() {
    local exit_code=$?
    trap - ERR
    if [ "$HTTP_CHANGED" -eq 1 ] && [ -f "$BACKUP_DIR/nginx-http.conf" ]; then
        install -o root -g root -m 644 "$BACKUP_DIR/nginx-http.conf" "$NGINX_HTTP_FILE"
    fi
    if [ "$HTTPS_CHANGED" -eq 1 ]; then
        if [ -f "$BACKUP_DIR/nginx-https.conf" ]; then
            install -o root -g root -m 644 "$BACKUP_DIR/nginx-https.conf" "$NGINX_HTTPS_FILE"
        else
            rm -f "$NGINX_HTTPS_FILE"
        fi
        if [ "$HTTPS_LINK_EXISTED" -eq 1 ]; then
            ln -sfn "$NGINX_HTTPS_FILE" /etc/nginx/sites-enabled/album-auth-ip-https
        else
            rm -f /etc/nginx/sites-enabled/album-auth-ip-https
        fi
    fi
    if [ "$HTTP_CHANGED" -eq 1 ] || [ "$HTTPS_CHANGED" -eq 1 ]; then
        nginx -t >/dev/null 2>&1 && systemctl reload nginx 2>/dev/null || true
        echo "HTTPS 启用失败，已恢复原 nginx 配置；证书文件保留供排查/重试。" >&2
    fi
    exit "$exit_code"
}
trap rollback_nginx ERR

echo "[1/6] 验证 HTTP/ACME webroot"
install -d -o www-data -g www-data -m 755 "$WEBROOT/.well-known/acme-challenge"
if ! grep -q 'well-known/acme-challenge' "$NGINX_HTTP_FILE"; then
    install -d -o root -g root -m 700 "$BACKUP_DIR"
    cp -a "$NGINX_HTTP_FILE" "$BACKUP_DIR/nginx-http.conf"
    python3 "$SCRIPT_DIR/inject_acme_location.py" \
        "$NGINX_HTTP_FILE" "$BACKUP_DIR/nginx-http-with-acme.conf"
    install -o root -g root -m 644 "$BACKUP_DIR/nginx-http-with-acme.conf" "$NGINX_HTTP_FILE"
    HTTP_CHANGED=1
    nginx -t
    systemctl reload nginx
fi
probe="album-auth-$STAMP"
printf '%s' "$probe" > "$WEBROOT/.well-known/acme-challenge/$probe"
served="$(curl -fsS -H "Host: $PUBLIC_IP" "http://127.0.0.1/.well-known/acme-challenge/$probe")"
rm -f "$WEBROOT/.well-known/acme-challenge/$probe"
if [ "$served" != "$probe" ]; then
    echo "错误：本机 ACME webroot 校验失败。" >&2
    exit 1
fi
echo "请确保公网 80 端口已放行并指向本机；证书机构会从公网再次校验。"

echo "[2/6] 安装/更新官方 snap 版 Certbot"
if ! command -v snap >/dev/null 2>&1; then
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y snapd
fi
if snap list certbot >/dev/null 2>&1; then
    snap refresh certbot
else
    snap install certbot --classic
fi
version="$($CERTBOT --version 2>&1 | sed -n 's/^certbot //p')"
python3 - "$version" <<'PY'
import re
import sys

parts = tuple(int(x) for x in re.findall(r"\d+", sys.argv[1])[:2])
if parts < (5, 4):
    raise SystemExit("错误：公网 IP webroot 证书要求 Certbot >= 5.4。")
PY

echo "[3/6] 用隔离目录申请 staging 证书（不污染正式 lineage）"
install -d -o root -g root -m 700 "$STAGING_CONFIG" "$STAGING_WORK" "$STAGING_LOG"
if [ "${ALBUM_SKIP_STAGING:-0}" != "1" ]; then
    "$CERTBOT" certonly --staging --non-interactive --agree-tos \
        --email "$EMAIL" --preferred-profile shortlived \
        --webroot --webroot-path "$WEBROOT" --ip-address "$PUBLIC_IP" \
        --config-dir "$STAGING_CONFIG" --work-dir "$STAGING_WORK" --logs-dir "$STAGING_LOG"
fi

echo "[4/6] 申请正式 6 天公网 IP 证书"
"$CERTBOT" certonly --non-interactive --agree-tos \
    --email "$EMAIL" --preferred-profile shortlived \
    --webroot --webroot-path "$WEBROOT" --ip-address "$PUBLIC_IP"
if [ ! -s "/etc/letsencrypt/live/$PUBLIC_IP/fullchain.pem" ] || \
   [ ! -s "/etc/letsencrypt/live/$PUBLIC_IP/privkey.pem" ]; then
    echo "错误：证书签发命令成功，但未找到预期证书文件。" >&2
    exit 1
fi

echo "[5/6] 备份并启用 HTTPS；80 端口继续反代旧客户端"
install -d -o root -g root -m 700 "$BACKUP_DIR"
[ ! -f "$NGINX_HTTPS_FILE" ] || cp -a "$NGINX_HTTPS_FILE" "$BACKUP_DIR/nginx-https.conf"
sed "s/__PUBLIC_IP__/$PUBLIC_IP/g" "$SCRIPT_DIR/nginx.conf" > "$BACKUP_DIR/nginx-https-new.conf"
install -o root -g root -m 644 "$BACKUP_DIR/nginx-https-new.conf" "$NGINX_HTTPS_FILE"
ln -sfn "$NGINX_HTTPS_FILE" /etc/nginx/sites-enabled/album-auth-ip-https
HTTPS_CHANGED=1
nginx -t
systemctl reload nginx
http_status="$(curl -sS --resolve "$PUBLIC_IP:80:127.0.0.1" \
    -o /dev/null -w '%{http_code}' "http://$PUBLIC_IP/api/me" || true)"
https_status="$(curl -sS --resolve "$PUBLIC_IP:443:127.0.0.1" \
    -o /dev/null -w '%{http_code}' "https://$PUBLIC_IP/api/me" || true)"
if [ "$http_status" != "401" ] || [ "$https_status" != "401" ]; then
    echo "错误：协议健康检查失败（http=$http_status, https=$https_status）。" >&2
    false
fi

echo "[6/6] 安装续期 reload hook 并确认定时器"
install -d -o root -g root -m 755 /etc/letsencrypt/renewal-hooks/deploy
hook=/etc/letsencrypt/renewal-hooks/deploy/reload-album-auth-nginx
printf '%s\n' '#!/usr/bin/env bash' 'set -euo pipefail' \
    'nginx -t' 'systemctl reload nginx' > "$hook"
chown root:root "$hook"
chmod 755 "$hook"
"$CERTBOT" renew --dry-run --cert-name "$PUBLIC_IP"
systemctl enable --now snap.certbot.renew.timer >/dev/null
systemctl is-enabled --quiet snap.certbot.renew.timer
systemctl is-active --quiet snap.certbot.renew.timer
HTTP_CHANGED=0
HTTPS_CHANGED=0
trap - ERR
echo "HTTPS 已启用；HTTP 未跳转，旧客户端继续兼容。备份：$BACKUP_DIR"
