#!/usr/bin/env bash
# 完全隔离的移动端测试环境。只允许操作 staging 专用路径与 service。
set -Eeuo pipefail
umask 077

APP_DIR=/opt/album-auth-staging
SERVER_DIR="$APP_DIR/server"
VENV_DIR="$APP_DIR/venv"
DATA_DIR=/var/lib/album-auth-staging
DB_PATH="$DATA_DIR/staging.db"
STORAGE_DIR="$DATA_DIR/mobile_objects"
CHUNK_DIR="$DATA_DIR/mobile_chunks"
CONFIG_DIR=/etc/album-auth-staging
SERVER_ENV="$CONFIG_DIR/server.env"
MOBILE_ENV="$CONFIG_DIR/mobile.env"
POLICY_ENV="$CONFIG_DIR/staging-policy.env"
PRIVATE_KEY="$CONFIG_DIR/private_key.pem"
BACKUP_DIR=/var/backups/album-auth-staging
SERVICE_NAME=album-auth-staging
SERVICE_USER=album-auth-staging
SERVICE_GROUP=album-auth-staging
UNIT_PATH="/etc/systemd/system/$SERVICE_NAME.service"
DROPIN_DIR="$UNIT_PATH.d"
LOCK_PATH=/run/lock/album-auth-staging-deploy.lock
SRC_DIR="$(cd -P "$(dirname "$0")/.." && pwd -P)"

PRODUCTION_ROOTS=(
    /opt/album-auth
    /etc/album-auth
    /var/lib/album-auth
)

die() {
    echo "staging 隔离检查失败：$*" >&2
    exit 1
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || die "缺少命令 $1"
}

is_within() {
    local path="$1"
    local root="$2"
    [[ "$path" == "$root" || "$path" == "$root/"* ]]
}

reject_production_path() {
    local path="$1"
    local resolved
    resolved="$(readlink -f -- "$path")" || die "无法解析路径：$path"
    local production
    for production in "${PRODUCTION_ROOTS[@]}"; do
        if is_within "$resolved" "$production"; then
            die "staging 路径落入正式目录：$resolved"
        fi
    done
}

reject_symlink_if_present() {
    local path="$1"
    if [[ -L "$path" ]]; then
        die "拒绝符号链接：$path -> $(readlink -- "$path")"
    fi
}

reject_hardlink_if_present() {
    local path="$1"
    if [[ -f "$path" ]] && [[ "$(stat -c '%h' -- "$path")" != "1" ]]; then
        die "拒绝硬链接文件：$path"
    fi
}

assert_tree_has_no_links() {
    local root="$1"
    local symlink
    local hardlink
    symlink="$(find "$root" -xdev -type l -print -quit)"
    [[ -z "$symlink" ]] || die "目录不得包含符号链接：$symlink"
    hardlink="$(find "$root" -xdev -type f -links +1 -print -quit)"
    [[ -z "$hardlink" ]] || die "目录不得包含硬链接文件：$hardlink"
}

assert_exact_directory() {
    local path="$1"
    local expected="$2"
    [[ -d "$path" ]] || die "目录不存在：$path"
    reject_symlink_if_present "$path"
    local resolved
    resolved="$(readlink -f -- "$path")" || die "无法解析目录：$path"
    [[ "$resolved" == "$expected" ]] || die "目录解析结果异常：$path -> $resolved"
    reject_production_path "$path"
}

assert_private_file() {
    local path="$1"
    local expected_owner="$2"
    local expected_group="$3"
    local expected_mode="$4"
    [[ -f "$path" ]] || die "文件不存在：$path"
    reject_symlink_if_present "$path"
    [[ "$(stat -c '%h' -- "$path")" == "1" ]] || die "敏感文件存在硬链接：$path"
    assert_mount_not_from_production "$path"
    local actual
    actual="$(stat -c '%U:%G:%a' -- "$path")"
    [[ "$actual" == "$expected_owner:$expected_group:$expected_mode" ]] || \
        die "文件权限必须为 $expected_owner:$expected_group $expected_mode：$path（当前 $actual）"
}

assert_mount_not_from_production() {
    local path="$1"
    local source
    source="$(findmnt -n -o SOURCE --target "$path" 2>/dev/null || true)"
    # ext4 子目录会显示为 /dev/vdaX[/var/lib/...]。必须提取方括号内的
    # 实际子路径再做目录边界判断；直接做字符串包含会把
    # album-auth-staging 误判成 album-auth 的子目录。
    local source_path="$source"
    if [[ "$source" =~ \[(.*)\]$ ]]; then
        source_path="${BASH_REMATCH[1]}"
    fi
    local production
    for production in "${PRODUCTION_ROOTS[@]}"; do
        if is_within "$source_path" "$production"; then
            die "staging 路径由正式目录挂载：$path <- $source"
        fi
    done
}

assert_safe_database_if_present() {
    [[ -e "$DB_PATH" ]] || return 0
    [[ -f "$DB_PATH" && ! -L "$DB_PATH" ]] || die "staging.db 必须是普通非链接文件"
    [[ "$(stat -c '%h' -- "$DB_PATH")" == "1" ]] || die "staging.db 存在硬链接"
    assert_mount_not_from_production "$DB_PATH"
    local owner_group
    owner_group="$(stat -c '%U:%G' -- "$DB_PATH")"
    [[ "$owner_group" == "$SERVICE_USER:$SERVICE_GROUP" ]] || \
        die "staging.db 属主必须为 $SERVICE_USER:$SERVICE_GROUP（当前 $owner_group）"
    local mode
    mode="$(stat -c '%a' -- "$DB_PATH")"
    if (( (8#$mode & 0022) != 0 )); then
        die "staging.db 不得允许组/其它用户写入（当前权限 $mode）"
    fi
}

validate_env_files() {
    python3 - "$SERVER_ENV" "$MOBILE_ENV" "$POLICY_ENV" <<'PY'
from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import urlsplit


server_path, mobile_path, policy_path = map(Path, sys.argv[1:4])
server_allowed = {"ALBUM_SERVER_SECRET"}
mobile_allowed = {
    "ALBUM_WECHAT_APP_ID",
    "ALBUM_WECHAT_APP_SECRET",
    "ALBUM_WECHAT_BIND_TICKET_MAX_AGE",
    "ALBUM_WECHAT_MOCK_ENABLED",
    "ALBUM_MOBILE_STORAGE_BACKEND",
    "ALBUM_MOBILE_CHUNK_TTL_SECONDS",
    "ALBUM_MOBILE_CHUNK_MAX_ACTIVE_PER_ACCOUNT",
    "ALBUM_MOBILE_CHUNK_MAX_ACTIVE_GLOBAL",
    "ALBUM_MOBILE_CHUNK_MAX_RESERVED_PER_ACCOUNT",
    "ALBUM_MOBILE_CHUNK_MAX_RESERVED_GLOBAL",
    "ALBUM_MOBILE_ANALYSIS_STALE_SECONDS",
    "ALBUM_MOBILE_MAX_ORIGINAL_PIXELS",
    "ALBUM_MOBILE_MAX_ORIGINAL_EDGE",
    "ALBUM_MOBILE_DOWNLOAD_URL_TTL",
    "ALBUM_OSS_REGION",
    "ALBUM_OSS_BUCKET",
    "ALBUM_OSS_PREVIEW_BUCKET",
    "ALBUM_OSS_ORIGINAL_BUCKET",
    "ALBUM_OSS_ENDPOINT",
}
policy_allowed = {
    "STAGING_WECHAT_APP_ID",
    "PRODUCTION_WECHAT_APP_ID",
    "STAGING_OSS_ORIGINAL_BUCKET",
    "STAGING_OSS_PREVIEW_BUCKET",
    "PRODUCTION_OSS_BUCKETS",
}
production_path = re.compile(r"/(?:opt|etc|var/lib)/album-auth(?:/|$)")


def fail(message: str) -> None:
    raise SystemExit(f"staging 环境文件拒绝启动：{message}")


def read_env(path: Path, allowed: set[str], *, optional: bool = False) -> dict[str, str]:
    if not path.exists():
        if optional:
            return {}
        fail(f"缺少 {path}")
    if path.is_symlink() or not path.is_file():
        fail(f"必须是普通非链接文件：{path}")
    raw = path.read_text(encoding="utf-8")
    if "\r" in raw or "\x00" in raw:
        fail(f"文件包含 CR/NUL：{path}")
    result: dict[str, str] = {}
    for line_number, line in enumerate(raw.splitlines(), 1):
        if not line or line.startswith("#"):
            continue
        if line != line.strip() or "=" not in line:
            fail(f"{path}:{line_number} 只允许 KEY=VALUE 单行格式")
        key, value = line.split("=", 1)
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            fail(f"{path}:{line_number} 变量名无效")
        if key not in allowed:
            fail(f"{path}:{line_number} 不允许变量 {key}")
        if key in result:
            fail(f"{path}:{line_number} 重复变量 {key}")
        if value != value.strip() or any(char in value for char in "\\\"'"):
            fail(f"{path}:{line_number} 值不得使用引号、反斜杠或首尾空格")
        if production_path.search(value):
            fail(f"{path}:{line_number} 值指向正式目录")
        result[key] = value
    return result


server = read_env(server_path, server_allowed)
mobile = read_env(mobile_path, mobile_allowed, optional=True)
policy = read_env(policy_path, policy_allowed)

secret = server.get("ALBUM_SERVER_SECRET", "")
if len(secret) < 32 or secret in {"dev-only-secret-change-me", "change-me", "请改成强随机字符串"}:
    fail("ALBUM_SERVER_SECRET 缺失、过短或仍为占位值")

backend = mobile.get("ALBUM_MOBILE_STORAGE_BACKEND", "local").lower()
if backend not in {"local", "oss"}:
    fail("ALBUM_MOBILE_STORAGE_BACKEND 只允许 local 或 oss")
if mobile.get("ALBUM_WECHAT_MOCK_ENABLED", "0") not in {"0", "1"}:
    fail("ALBUM_WECHAT_MOCK_ENABLED 只允许 0 或 1")

app_id = mobile.get("ALBUM_WECHAT_APP_ID", "")
app_secret = mobile.get("ALBUM_WECHAT_APP_SECRET", "")
pinned_app_id = policy.get("STAGING_WECHAT_APP_ID", "")
production_app_id = policy.get("PRODUCTION_WECHAT_APP_ID", "")
if app_id:
    if not pinned_app_id or app_id != pinned_app_id:
        fail("微信 AppID 未被 staging-policy.env 精确批准")
    if not production_app_id:
        fail("启用微信前必须在 staging-policy.env 登记正式 AppID 以阻止误用")
    if app_id == production_app_id:
        fail("staging 微信 AppID 与正式 AppID 相同")
    if not re.fullmatch(r"wx[0-9A-Za-z]{8,}", app_id):
        fail("微信 AppID 格式无效")
    if not app_secret and mobile.get("ALBUM_WECHAT_MOCK_ENABLED", "0") != "1":
        fail("真实微信登录缺少独立 staging AppSecret")
elif app_secret:
    fail("配置了 AppSecret 但缺少 AppID")

original_bucket = mobile.get("ALBUM_OSS_ORIGINAL_BUCKET", "")
explicit_preview_bucket = mobile.get("ALBUM_OSS_PREVIEW_BUCKET", "")
legacy_preview_bucket = mobile.get("ALBUM_OSS_BUCKET", "")
if explicit_preview_bucket and legacy_preview_bucket and explicit_preview_bucket != legacy_preview_bucket:
    fail("ALBUM_OSS_BUCKET 与 ALBUM_OSS_PREVIEW_BUCKET 冲突")
preview_bucket = explicit_preview_bucket or legacy_preview_bucket
pinned_original = policy.get("STAGING_OSS_ORIGINAL_BUCKET", "")
pinned_preview = policy.get("STAGING_OSS_PREVIEW_BUCKET", "")
production_buckets = {
    bucket for bucket in policy.get("PRODUCTION_OSS_BUCKETS", "").split(",") if bucket
}
if original_bucket or preview_bucket or backend == "oss":
    if not original_bucket or not preview_bucket:
        fail("OSS staging 必须分别配置原图桶和预览桶")
    if original_bucket == preview_bucket:
        fail("OSS staging 原图桶与预览桶必须不同")
    if original_bucket != pinned_original or preview_bucket != pinned_preview:
        fail("OSS Bucket 未被 staging-policy.env 精确批准")
    if not production_buckets:
        fail("启用 OSS 前必须在 staging-policy.env 登记全部正式 Bucket 以阻止误用")
    if original_bucket in production_buckets or preview_bucket in production_buckets:
        fail("staging OSS Bucket 与正式 Bucket 相同")
    for bucket in (original_bucket, preview_bucket):
        lowered = bucket.lower()
        if "staging" not in lowered and "test" not in lowered:
            fail(f"Bucket 名称缺少 staging/test 标记：{bucket}")

endpoint = mobile.get("ALBUM_OSS_ENDPOINT", "")
if endpoint:
    parsed = urlsplit(endpoint)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or not (host == "aliyuncs.com" or host.endswith(".aliyuncs.com")):
        fail("ALBUM_OSS_ENDPOINT 必须是阿里云官方 HTTPS 主机")
if backend == "oss" and mobile.get("ALBUM_OSS_REGION", "cn-beijing") != "cn-beijing":
    fail("首版 staging OSS 地域必须为 cn-beijing")
PY
}

assert_ed25519_key() {
    openssl pkey -in "$PRIVATE_KEY" -check -noout >/dev/null
    "$VENV_DIR/bin/python" - "$PRIVATE_KEY" <<'PY'
import sys
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

key = serialization.load_pem_private_key(Path(sys.argv[1]).read_bytes(), password=None)
if not isinstance(key, Ed25519PrivateKey):
    raise SystemExit("staging 授权私钥必须是独立 Ed25519 私钥；RSA 与当前签名接口不兼容")
PY
}

runtime_checks() {
    require_command python3
    require_command readlink
    require_command stat
    require_command findmnt
    require_command openssl
    assert_exact_directory "$APP_DIR" "$APP_DIR"
    assert_exact_directory "$SERVER_DIR" "$SERVER_DIR"
    assert_exact_directory "$DATA_DIR" "$DATA_DIR"
    assert_exact_directory "$STORAGE_DIR" "$STORAGE_DIR"
    assert_exact_directory "$CHUNK_DIR" "$CHUNK_DIR"
    assert_exact_directory "$CONFIG_DIR" "$CONFIG_DIR"
    for path in "$APP_DIR" "$SERVER_DIR" "$DATA_DIR" "$STORAGE_DIR" "$CHUNK_DIR" "$CONFIG_DIR"; do
        assert_mount_not_from_production "$path"
    done
    assert_private_file "$SERVER_ENV" root "$SERVICE_GROUP" 640
    assert_private_file "$POLICY_ENV" root "$SERVICE_GROUP" 640
    assert_private_file "$PRIVATE_KEY" root "$SERVICE_GROUP" 640
    if [[ -e "$MOBILE_ENV" ]]; then
        assert_private_file "$MOBILE_ENV" root "$SERVICE_GROUP" 640
    fi
    [[ "$(stat -c '%U:%G:%a' -- "$DATA_DIR")" == "$SERVICE_USER:$SERVICE_GROUP:750" ]] || \
        die "数据目录权限必须为 $SERVICE_USER:$SERVICE_GROUP 750"
    [[ -x "$VENV_DIR/bin/python" && -x "$VENV_DIR/bin/gunicorn" ]] || \
        die "staging 虚拟环境不完整"
    assert_safe_database_if_present
    validate_env_files
    assert_ed25519_key
}

if [[ "${1:-}" == "--runtime-check" ]]; then
    [[ $# -eq 1 ]] || die "--runtime-check 不接受其它参数"
    [[ "$(id -un)" == "$SERVICE_USER" && "$(id -gn)" == "$SERVICE_GROUP" ]] || \
        die "runtime-check 必须以独立 staging 用户运行"
    if id -nG | tr ' ' '\n' | grep -Fxq www-data; then
        die "runtime-check 进程不得继承 www-data 组"
    fi
    runtime_checks
    exit 0
fi
[[ $# -eq 0 ]] || die "未知参数：$*"
[[ "${EUID:-$(id -u)}" -eq 0 ]] || die "部署脚本必须由 root 运行"

require_command flock
require_command stat
require_command chown
require_command chmod
reject_symlink_if_present "$LOCK_PATH"
reject_hardlink_if_present "$LOCK_PATH"
if [[ -e "$LOCK_PATH" ]]; then
    [[ -f "$LOCK_PATH" ]] || die "部署锁必须是普通文件：$LOCK_PATH"
    [[ "$(stat -c '%U:%G:%a' -- "$LOCK_PATH")" == "root:root:600" ]] || \
        die "部署锁权限必须为 root:root 600：$LOCK_PATH"
else
    (set -o noclobber; : > "$LOCK_PATH") || die "无法排他创建部署锁：$LOCK_PATH"
    chown root:root "$LOCK_PATH"
    chmod 600 "$LOCK_PATH"
fi
exec 9<>"$LOCK_PATH"
flock -n 9 || die "已有 staging 部署正在执行"

for command in apt-get find getent groupadd useradd install readlink stat findmnt systemctl; do
    require_command "$command"
done

reject_production_path "$SRC_DIR"
assert_mount_not_from_production "$SRC_DIR"
[[ "$SRC_DIR" != "$SERVER_DIR" ]] || die "部署源码必须位于 staging 安装目录之外"
assert_tree_has_no_links "$SRC_DIR"
for path in "$APP_DIR" "$SERVER_DIR" "$VENV_DIR" "$DATA_DIR" "$STORAGE_DIR" \
    "$CHUNK_DIR" "$CONFIG_DIR" "$BACKUP_DIR" "$UNIT_PATH" "$DROPIN_DIR" \
    "$SERVER_ENV" "$MOBILE_ENV" "$POLICY_ENV" "$PRIVATE_KEY" "$DB_PATH"; do
    reject_symlink_if_present "$path"
    reject_hardlink_if_present "$path"
done

if [[ -e "$UNIT_PATH" ]]; then
    [[ -f "$UNIT_PATH" && ! -L "$UNIT_PATH" ]] || die "staging unit 必须是普通非链接文件"
    [[ "$(stat -c '%h' -- "$UNIT_PATH")" == "1" ]] || die "staging unit 存在硬链接"
    production_unit=/etc/systemd/system/album-auth.service
    if [[ -e "$production_unit" ]] && [[ "$UNIT_PATH" -ef "$production_unit" ]]; then
        die "staging unit 与正式 unit 指向同一 inode"
    fi
fi

if [[ -d "$DROPIN_DIR" ]] && [[ -n "$(find "$DROPIN_DIR" -mindepth 1 -print -quit)" ]]; then
    die "发现未审核的 staging systemd drop-in：$DROPIN_DIR"
fi
fragment="$(systemctl show "$SERVICE_NAME.service" -p FragmentPath --value 2>/dev/null || true)"
if [[ -n "$fragment" ]]; then
    [[ "$(readlink -f -- "$fragment")" == "$UNIT_PATH" ]] || \
        die "staging service 指向未知 unit：$fragment"
fi
dropins="$(systemctl show "$SERVICE_NAME.service" -p DropInPaths --value 2>/dev/null || true)"
[[ -z "$dropins" ]] || die "staging service 存在未审核 drop-in：$dropins"

apt-get update
apt-get install -y \
    ca-certificates curl openssl python3-venv rsync sqlite3 util-linux
for command in curl openssl python3 rsync sqlite3 systemd-analyze; do
    require_command "$command"
done

if ! getent group "$SERVICE_GROUP" >/dev/null; then
    groupadd --system "$SERVICE_GROUP"
fi
if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
    useradd --system --gid "$SERVICE_GROUP" --home-dir "$APP_DIR" \
        --shell /usr/sbin/nologin --no-create-home "$SERVICE_USER"
fi
[[ "$(id -gn "$SERVICE_USER")" == "$SERVICE_GROUP" ]] || \
    die "staging 用户主组不是 $SERVICE_GROUP"
if id -u www-data >/dev/null 2>&1; then
    [[ "$(id -u "$SERVICE_USER")" != "$(id -u www-data)" ]] || \
        die "staging 用户与 www-data 共用 UID"
fi
if id -nG "$SERVICE_USER" | tr ' ' '\n' | grep -Fxq www-data; then
    die "staging 用户不得加入生产常用组 www-data"
fi

install -d -o root -g "$SERVICE_GROUP" -m 0750 "$APP_DIR" "$SERVER_DIR" "$CONFIG_DIR"
install -d -o "$SERVICE_USER" -g "$SERVICE_GROUP" -m 0750 \
    "$DATA_DIR" "$STORAGE_DIR" "$CHUNK_DIR"
install -d -o root -g root -m 0700 "$BACKUP_DIR"
assert_exact_directory "$APP_DIR" "$APP_DIR"
assert_exact_directory "$SERVER_DIR" "$SERVER_DIR"
assert_exact_directory "$DATA_DIR" "$DATA_DIR"
assert_exact_directory "$STORAGE_DIR" "$STORAGE_DIR"
assert_exact_directory "$CHUNK_DIR" "$CHUNK_DIR"
assert_exact_directory "$CONFIG_DIR" "$CONFIG_DIR"
assert_exact_directory "$BACKUP_DIR" "$BACKUP_DIR"
for path in "$APP_DIR" "$SERVER_DIR" "$DATA_DIR" "$STORAGE_DIR" "$CHUNK_DIR" \
    "$CONFIG_DIR" "$BACKUP_DIR"; do
    assert_mount_not_from_production "$path"
done

assert_safe_database_if_present
if [[ -s "$DB_PATH" ]]; then
    backup_path="$(mktemp "$BACKUP_DIR/staging-$(date -u +%Y%m%dT%H%M%SZ)-XXXXXXXX.db")"
    chmod 600 "$backup_path"
    sqlite3 "$DB_PATH" ".backup '$backup_path'"
    [[ "$(sqlite3 "$backup_path" 'PRAGMA integrity_check;')" == "ok" ]] || \
        die "staging 数据库备份完整性检查失败：$backup_path"
    echo "已创建 root-only staging 数据库备份：$backup_path"
fi

assert_tree_has_no_links "$SERVER_DIR"
if [[ -d "$SERVER_DIR/data" ]] && [[ -n "$(find "$SERVER_DIR/data" -mindepth 1 -print -quit)" ]]; then
    die "staging 源码目录残留 data/ 内容；请先人工隔离，脚本不会删除"
fi
if systemctl is-active --quiet "$SERVICE_NAME"; then
    systemctl stop "$SERVICE_NAME"
fi
rsync -a --delete-delay \
    --exclude '/data/' --exclude '__pycache__/' --exclude '*.pem' --exclude '*.key' \
    "$SRC_DIR/" "$SERVER_DIR/"

python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --disable-pip-version-check \
    -r "$SERVER_DIR/requirements.txt"
mapfile -d '' python_modules < <(find "$SERVER_DIR" -maxdepth 1 -type f -name '*.py' -print0)
[[ "${#python_modules[@]}" -gt 0 ]] || die "server 目录没有 Python 模块"
"$VENV_DIR/bin/python" -m py_compile "${python_modules[@]}"
"$VENV_DIR/bin/gunicorn" --help | grep -Fq -- '--no-control-socket' || \
    die "当前 gunicorn 不支持 --no-control-socket，请检查 requirements 版本锁定"

if [[ ! -s "$SERVER_ENV" ]]; then
    temporary_env="$(mktemp "$CONFIG_DIR/.server.env.XXXXXXXX")"
    printf 'ALBUM_SERVER_SECRET=%s\n' "$(openssl rand -hex 32)" > "$temporary_env"
    install -o root -g "$SERVICE_GROUP" -m 0640 "$temporary_env" "$SERVER_ENV"
    rm -f -- "$temporary_env"
fi
if [[ ! -e "$POLICY_ENV" ]]; then
    temporary_policy="$(mktemp "$CONFIG_DIR/.staging-policy.XXXXXXXX")"
    {
        echo '# 必须先在这里钉住测试资源，mobile.env 才能启用对应 AppID/Bucket。'
        echo 'STAGING_WECHAT_APP_ID='
        echo 'PRODUCTION_WECHAT_APP_ID='
        echo 'STAGING_OSS_ORIGINAL_BUCKET='
        echo 'STAGING_OSS_PREVIEW_BUCKET='
        echo 'PRODUCTION_OSS_BUCKETS='
    } > "$temporary_policy"
    install -o root -g "$SERVICE_GROUP" -m 0640 "$temporary_policy" "$POLICY_ENV"
    rm -f -- "$temporary_policy"
fi
if [[ ! -s "$PRIVATE_KEY" ]]; then
    temporary_key="$(mktemp "$CONFIG_DIR/.private-key.XXXXXXXX")"
    openssl genpkey -algorithm Ed25519 -out "$temporary_key"
    install -o root -g "$SERVICE_GROUP" -m 0640 "$temporary_key" "$PRIVATE_KEY"
    rm -f -- "$temporary_key"
fi

for file in "$SERVER_ENV" "$POLICY_ENV" "$PRIVATE_KEY"; do
    reject_symlink_if_present "$file"
    chown root:"$SERVICE_GROUP" "$file"
    chmod 640 "$file"
done
if [[ -e "$MOBILE_ENV" ]]; then
    reject_symlink_if_present "$MOBILE_ENV"
    chown root:"$SERVICE_GROUP" "$MOBILE_ENV"
    chmod 640 "$MOBILE_ENV"
fi
find "$APP_DIR" -xdev ! -type l -exec chown root:"$SERVICE_GROUP" {} +
# 上传源文件可能受 root 的 077 umask 影响而只有 0600/0700。staging
# 进程使用独立用户，必须让其主组可读代码、可遍历目录，并继承原有可执行位。
find "$APP_DIR" -xdev ! -type l -exec chmod g+rX,o-rwx {} +
find "$DATA_DIR" -xdev ! -type l -exec chown "$SERVICE_USER":"$SERVICE_GROUP" {} +
find "$DATA_DIR" -xdev ! -type l -exec chmod o-rwx {} +
chmod 750 "$DATA_DIR" "$STORAGE_DIR" "$CHUNK_DIR"

runtime_checks
install -o root -g root -m 0644 \
    "$SERVER_DIR/deploy/album-auth-staging.service" "$UNIT_PATH"
systemd-analyze verify "$UNIT_PATH"
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

legacy_health=000
mobile_health=000
for _attempt in $(seq 1 15); do
    if legacy_health="$(curl --silent --show-error --max-time 5 -o /dev/null \
        -w '%{http_code}' http://127.0.0.1:18080/api/me)" && \
       mobile_health="$(curl --silent --show-error --max-time 5 -o /dev/null \
        -w '%{http_code}' http://127.0.0.1:18080/api/mobile/v1/projects)" && \
       [[ "$legacy_health" == "401" && "$mobile_health" == "401" ]]; then
        break
    fi
    sleep 1
done
if [[ "$legacy_health" != "401" || "$mobile_health" != "401" ]]; then
    journalctl -u "$SERVICE_NAME" -n 80 --no-pager >&2 || true
    systemctl stop "$SERVICE_NAME" || true
    die "健康检查失败，已停止 staging：legacy=$legacy_health mobile=$mobile_health"
fi

echo "staging 已启动：service=$SERVICE_NAME port=18080 data=$DATA_DIR"
echo "微信/OSS 资源必须先写入 $POLICY_ENV，再写入 $MOBILE_ENV。"
