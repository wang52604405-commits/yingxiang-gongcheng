#!/usr/bin/env bash
# SQLite 在线一致性备份。建议由 root 的 systemd timer/cron 每日执行。
set -Eeuo pipefail
umask 077

DB_PATH="${ALBUM_BACKUP_DB:-/opt/album-auth/data/server.db}"
BACKUP_DIR=/opt/album-auth/backups/database
RETENTION_DAYS="${ALBUM_BACKUP_RETENTION_DAYS:-30}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
TARGET="$BACKUP_DIR/server-$STAMP.db"
TEMP="$TARGET.tmp"

if [ "$(id -u)" -ne 0 ]; then
    echo "错误：请由 root 执行备份。" >&2
    exit 1
fi
if [[ ! "$RETENTION_DAYS" =~ ^[0-9]+$ ]] || [ "$RETENTION_DAYS" -lt 7 ]; then
    echo "错误：ALBUM_BACKUP_RETENTION_DAYS 必须是至少 7 天的整数。" >&2
    exit 1
fi
if [ ! -f "$DB_PATH" ]; then
    echo "错误：数据库不存在：$DB_PATH" >&2
    exit 1
fi

install -d -o root -g root -m 700 "$BACKUP_DIR"
cleanup() { rm -f "$TEMP"; }
trap cleanup EXIT
sqlite3 "$DB_PATH" ".backup '$TEMP'"
if [ "$(sqlite3 "$TEMP" 'PRAGMA quick_check;')" != "ok" ]; then
    echo "错误：备份 quick_check 失败，不会发布该备份。" >&2
    exit 1
fi
chmod 600 "$TEMP"
mv "$TEMP" "$TARGET"

# 只清理本备份专用目录中、符合固定命名的过期数据库文件。
find "$BACKUP_DIR" -maxdepth 1 -type f -name 'server-*.db' \
    -mtime "+$RETENTION_DAYS" -delete
echo "备份完成并校验通过：$TARGET"
