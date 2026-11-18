#!/usr/bin/env bash
# 只回退白名单应用代码。数据库、原片、预览图、分块及部署配置都原地保留。
set -Eeuo pipefail
umask 077

APP_DIR=/opt/album-auth
VENV="$APP_DIR/venv"
BACKUP_ROOT="$APP_DIR/backups"
REQUESTED="${1:-}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
PRE_DIR="$BACKUP_ROOT/pre-rollback-$STAMP"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
HELPER="$SCRIPT_DIR/code_rollback.py"
SWITCHED=0

if [ "$(id -u)" -ne 0 ]; then
    echo "错误：请用 root 执行。" >&2
    exit 1
fi
if [ -z "$REQUESTED" ]; then
    echo "用法：sudo bash rollback.sh /opt/album-auth/backups/deploy-<时间>" >&2
    exit 1
fi

# 使用当前版本的可信工具，不导入备份代码，也不执行备份中的脚本或依赖安装。
# prepare 校验路径、备份和依赖，并独占保存当前代码；失败时服务尚未停止。
"$VENV/bin/python" "$HELPER" prepare --app-root "$APP_DIR" \
    --backup "$REQUESTED" --state "$PRE_DIR"
"$VENV/bin/python" -B "$SCRIPT_DIR/check_dependencies.py" \
    --requirements "$PRE_DIR/target/server/requirements.txt"

recover_current() {
    local exit_code=$?
    trap - ERR
    if [ "$SWITCHED" -eq 1 ]; then
        if ! systemctl stop album-auth || \
           ! "$VENV/bin/python" "$HELPER" recover --app-root "$APP_DIR" --state "$PRE_DIR" || \
           ! systemctl start album-auth; then
            echo "恢复回退前代码失败，请人工检查：$PRE_DIR；业务数据未回退。" >&2
            exit 1
        fi
        echo "回退未通过，已恢复回退前代码；业务数据未回退。" >&2
    fi
    exit "$exit_code"
}
trap recover_current ERR

systemctl stop album-auth
SWITCHED=1
"$VENV/bin/python" "$HELPER" apply --app-root "$APP_DIR" --state "$PRE_DIR"
systemctl start album-auth
for _ in $(seq 1 20); do
    me_status="$(curl -sS --max-time 5 -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/api/me || true)"
    product_status="$(curl -sS --max-time 5 -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/api/product-config || true)"
    [ "$me_status" != "401" ] || [ "$product_status" != "200" ] || break
    sleep 1
done
if [ "${me_status:-}" != "401" ] || [ "${product_status:-}" != "200" ]; then
    false
fi
SWITCHED=0
trap - ERR
echo "白名单应用代码已回退到：$REQUESTED"
echo "回退前代码及校验记录保留在：$PRE_DIR"
echo "数据库、原片、预览图及分块未回退；部署配置未修改。"
