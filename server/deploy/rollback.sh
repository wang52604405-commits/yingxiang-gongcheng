#!/usr/bin/env bash
# 回退到 deploy.sh 生成的某个代码备份；不自动回退数据库，避免丢失新业务数据。
set -Eeuo pipefail

APP_DIR=/opt/album-auth
CODE_DIR="$APP_DIR/server"
VENV="$APP_DIR/venv"
BACKUP_ROOT="$APP_DIR/backups"
REQUESTED="${1:-}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
PRE_DIR="$BACKUP_ROOT/pre-rollback-$STAMP"
SWITCHED=0

if [ "$(id -u)" -ne 0 ]; then
    echo "错误：请用 root 执行。" >&2
    exit 1
fi
if [ -z "$REQUESTED" ]; then
    echo "用法：sudo bash rollback.sh /opt/album-auth/backups/deploy-<时间>" >&2
    exit 1
fi
root_real="$(realpath -e "$BACKUP_ROOT")"
target_real="$(realpath -e "$REQUESTED")"
case "$target_real" in
    "$root_real"/deploy-*) ;;
    *) echo "错误：只允许选择 $BACKUP_ROOT/deploy-* 备份。" >&2; exit 1 ;;
esac
if [ ! -f "$target_real/server/app.py" ] || \
   [ ! -f "$target_real/server/requirements.txt" ]; then
    echo "错误：目标备份缺少完整 server 代码。" >&2
    exit 1
fi

recover_current() {
    local exit_code=$?
    trap - ERR
    if [ "$SWITCHED" -eq 1 ] && [ -d "$PRE_DIR/server" ]; then
        systemctl stop album-auth 2>/dev/null || true
        [ ! -d "$CODE_DIR" ] || mv "$CODE_DIR" "$PRE_DIR/failed-target"
        mv "$PRE_DIR/server" "$CODE_DIR"
        systemctl start album-auth 2>/dev/null || true
        echo "回退版本未通过健康检查，已恢复回退前代码。" >&2
    fi
    exit "$exit_code"
}
trap recover_current ERR

install -d -o root -g root -m 700 "$PRE_DIR"
cd "$target_real"
"$VENV/bin/python" -m py_compile \
    server/app.py server/config.py server/db.py server/mailer.py
"$VENV/bin/pip" install --disable-pip-version-check -r server/requirements.txt

systemctl stop album-auth
mv "$CODE_DIR" "$PRE_DIR/server"
SWITCHED=1
cp -a "$target_real/server" "$CODE_DIR"
systemctl start album-auth
for _ in $(seq 1 20); do
    me_status="$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/api/me || true)"
    product_status="$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/api/product-config || true)"
    [ "$me_status" != "401" ] || [ "$product_status" != "200" ] || break
    sleep 1
done
if [ "${me_status:-}" != "401" ] || [ "${product_status:-}" != "200" ]; then
    false
fi
SWITCHED=0
trap - ERR
echo "代码已回退到：$target_real"
echo "回退前代码保留在：$PRE_DIR/server"
echo "数据库未回退；如确需恢复数据库，必须先停服务并单独确认数据影响。"
