#!/usr/bin/env bash
# SQLite 在线一致性备份。建议由 root 的 systemd timer/cron 每日执行。
set -Eeuo pipefail
umask 077

DB_PATH="${ALBUM_BACKUP_DB:-/opt/album-auth/data/server.db}"
BACKUP_DIR=/opt/album-auth/backups/database
# 保留全部历史副本。容量不足时停止，不自动清理恢复资料。
MIN_FREE_KB=$((128 * 1024))
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"

if [ "$(id -u)" -ne 0 ]; then
    echo "错误：请由 root 执行备份。" >&2
    exit 1
fi
if [ ! -f "$DB_PATH" ]; then
    echo "错误：数据库不存在：$DB_PATH" >&2
    exit 1
fi

# page_count 包含当前连接能看到的 WAL 页面；不能只用主库文件的大小估算。
pages="$(sqlite3 "$DB_PATH" 'PRAGMA page_count;')"
page_size="$(sqlite3 "$DB_PATH" 'PRAGMA page_size;')"
if [[ ! "$pages" =~ ^[0-9]+$ ]] || [[ ! "$page_size" =~ ^[0-9]+$ ]]; then
    echo "错误：无法确认数据库大小，历史备份保持不变。" >&2
    exit 1
fi
space_root="$BACKUP_DIR"
while [ ! -d "$space_root" ]; do space_root="$(dirname "$space_root")"; done
available_kb="$(df -Pk "$space_root" | awk 'NR==2 {print $4}')"
required_kb=$(( (pages * page_size + 1023) / 1024 + MIN_FREE_KB ))
if [[ ! "$available_kb" =~ ^[0-9]+$ ]] || [ "$available_kb" -lt "$required_kb" ]; then
    echo "错误：备份空间不足或无法确认容量，已停止；全部历史副本保持不变。" >&2
    exit 1
fi

install -d -o root -g root -m 700 "$BACKUP_DIR"
# 每次运行排他创建目录，避免同秒触发或重试时覆盖已有备份。
WORK_DIR="$(mktemp -d "$BACKUP_DIR/server-$STAMP-XXXXXXXX")"
TARGET="$WORK_DIR/server.db"
TEMP="$WORK_DIR/.pending.db"
PUBLISHED=0
cleanup() {
    rm -f -- "$TEMP" "$TEMP-journal" "$TEMP-wal" "$TEMP-shm"
    if [ "$PUBLISHED" -eq 0 ]; then rmdir -- "$WORK_DIR" 2>/dev/null || true; fi
}
trap cleanup EXIT
sqlite3 "$DB_PATH" ".backup '$TEMP'"
if [ "$(sqlite3 "$TEMP" 'PRAGMA quick_check;')" != "ok" ]; then
    echo "错误：备份 quick_check 失败，不会发布该备份。" >&2
    exit 1
fi
chmod 600 "$TEMP"
mv "$TEMP" "$TARGET"
PUBLISHED=1

echo "备份完成并校验通过：$TARGET"
