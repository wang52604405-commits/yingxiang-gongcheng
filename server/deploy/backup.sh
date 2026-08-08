#!/usr/bin/env bash
# 每日备份数据库（配合 cron 使用）
# crontab -e:  0 3 * * * bash /opt/album-auth/deploy/backup.sh
set -euo pipefail

TS=$(date +%Y%m%d-%H%M%S)
BACKUP_DIR=/opt/album-auth/backups
mkdir -p "$BACKUP_DIR"

sqlite3 /opt/album-auth/data/server.db ".backup '$BACKUP_DIR/server-$TS.db'"
find "$BACKUP_DIR" -name "server-*.db" -mtime +30 -delete
echo "备份完成: $BACKUP_DIR/server-$TS.db"
