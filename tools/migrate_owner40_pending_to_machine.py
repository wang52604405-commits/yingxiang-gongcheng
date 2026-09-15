import os
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ACCOUNT_ID = 40
PROJECT_ID = "FN2023GC0046"
# 用户提供的 GUID 不是服务器授权表中的 machine_id；服务器今天新绑定的
# 归档电脑为下面这个 HDYX 机器号，且旧工程仍绑定在上一台电脑。
TARGET_MACHINE_ID = "HDYX-D3AE-10AF-BFEC-183E"

pid = subprocess.check_output(
    ["systemctl", "show", "--property=MainPID", "--value", "album-auth"],
    text=True,
).strip()
if not pid or pid == "0":
    raise SystemExit("album-auth not running")

env = {}
for item in Path(f"/proc/{pid}/environ").read_bytes().split(b"\0"):
    key, sep, value = item.partition(b"=")
    if sep:
        env[key.decode("utf-8", "surrogateescape")] = value.decode("utf-8", "surrogateescape")

cwd = Path(os.readlink(f"/proc/{pid}/cwd"))
db_path = Path(
    env.get("ALBUM_SERVER_DB")
    or (
        Path(env["ALBUM_SERVER_DATA"]) / "server.db"
        if env.get("ALBUM_SERVER_DATA")
        else cwd / "data" / "server.db"
    )
)
if not db_path.is_absolute():
    db_path = cwd / db_path

db_path = db_path.resolve()
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

bound = conn.execute(
    "SELECT id, machine_id, active, bound_at, last_seen FROM machines WHERE account_id=? ORDER BY id",
    (ACCOUNT_ID,),
).fetchall()
print("BOUND_MACHINES=" + repr([dict(row) for row in bound]))

machine = conn.execute(
    "SELECT id, account_id, machine_id, active, bound_at, last_seen FROM machines "
    "WHERE account_id=? AND UPPER(machine_id)=?",
    (ACCOUNT_ID, TARGET_MACHINE_ID.upper()),
).fetchone()
if not machine:
    conn.close()
    raise SystemExit("ABORT: target machine is not bound to account 40")
if not int(machine["active"] or 0):
    conn.close()
    raise SystemExit("ABORT: target machine is bound but inactive")

project = conn.execute(
    "SELECT account_id, project_id, project_code, project_name, desktop_machine_id, active "
    "FROM cloud_engineering_projects WHERE account_id=? AND project_id=?",
    (ACCOUNT_ID, PROJECT_ID),
).fetchone()
if not project or not int(project["active"] or 0):
    conn.close()
    raise SystemExit("ABORT: target project is missing or inactive")

before_pending = conn.execute(
    "SELECT COUNT(*) FROM cloud_photos WHERE project_owner_account_id=? AND project_id=? "
    "AND source='mobile' AND status='desktop_pending' AND deleted_at=''",
    (ACCOUNT_ID, PROJECT_ID),
).fetchone()[0]

before_imported = conn.execute(
    "SELECT COUNT(*) FROM cloud_photos WHERE project_owner_account_id=? AND project_id=? "
    "AND source='mobile' AND status='desktop_imported' AND deleted_at=''",
    (ACCOUNT_ID, PROJECT_ID),
).fetchone()[0]

before_uncommitted = conn.execute(
    "SELECT COUNT(*) FROM cloud_photos WHERE project_owner_account_id=? AND project_id=? "
    "AND source='mobile' AND status IN ('server_saved','analyzing','needs_review') AND deleted_at=''",
    (ACCOUNT_ID, PROJECT_ID),
).fetchone()[0]

print(f"PROJECT={project['project_name']}")
print(f"TARGET_MACHINE_BOUND=1 ACTIVE={machine['active']}")
print(f"BEFORE_PENDING={before_pending} BEFORE_IMPORTED={before_imported} BEFORE_UNCOMMITTED={before_uncommitted}")
print(f"OLD_PROJECT_MACHINE={project['desktop_machine_id']}")

if before_pending <= 0 and before_uncommitted <= 0:
    print("NO_MIGRATION_NEEDED")
    conn.close()
    raise SystemExit(0)

backup_dir = db_path.parent / "migration-backups"
backup_dir.mkdir(parents=True, exist_ok=True)
stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
backup_path = backup_dir / f"server-before-owner40-{PROJECT_ID}-machine-{stamp}.db"
backup_conn = sqlite3.connect(backup_path)
try:
    conn.backup(backup_conn)
finally:
    backup_conn.close()
print(f"BACKUP={backup_path}")

timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
try:
    conn.execute("BEGIN IMMEDIATE")

    project_changed = conn.execute(
        "UPDATE cloud_engineering_projects SET desktop_machine_id=?, updated_at=? "
        "WHERE account_id=? AND project_id=? AND active=1",
        (TARGET_MACHINE_ID, timestamp, ACCOUNT_ID, PROJECT_ID),
    ).rowcount

    photos_changed = conn.execute(
        "UPDATE cloud_photos SET target_machine_id=?, updated_at=? "
        "WHERE project_owner_account_id=? AND project_id=? AND source='mobile' "
        "AND status IN ('server_saved','analyzing','needs_review','desktop_pending') "
        "AND deleted_at=''",
        (TARGET_MACHINE_ID, timestamp, ACCOUNT_ID, PROJECT_ID),
    ).rowcount

    batches_changed = conn.execute(
        "UPDATE mobile_batches SET target_machine_id=?, updated_at=? "
        "WHERE project_owner_account_id=? AND project_id=? "
        "AND status!='desktop_imported'",
        (TARGET_MACHINE_ID, timestamp, ACCOUNT_ID, PROJECT_ID),
    ).rowcount

    sessions_changed = conn.execute(
        "UPDATE mobile_upload_sessions SET target_machine_id=?, updated_at=? "
        "WHERE project_owner_account_id=? AND project_id=? "
        "AND status IN ('active','finalizing')",
        (TARGET_MACHINE_ID, timestamp, ACCOUNT_ID, PROJECT_ID),
    ).rowcount

    conn.commit()
except Exception:
    conn.rollback()
    raise

pending_target = conn.execute(
    "SELECT COUNT(*) FROM cloud_photos WHERE project_owner_account_id=? AND project_id=? "
    "AND source='mobile' AND status='desktop_pending' AND deleted_at='' AND UPPER(target_machine_id)=?",
    (ACCOUNT_ID, PROJECT_ID, TARGET_MACHINE_ID.upper()),
).fetchone()[0]

pending_other = conn.execute(
    "SELECT COUNT(*) FROM cloud_photos WHERE project_owner_account_id=? AND project_id=? "
    "AND source='mobile' AND status='desktop_pending' AND deleted_at='' AND UPPER(target_machine_id)<>?",
    (ACCOUNT_ID, PROJECT_ID, TARGET_MACHINE_ID.upper()),
).fetchone()[0]

imported_after = conn.execute(
    "SELECT COUNT(*) FROM cloud_photos WHERE project_owner_account_id=? AND project_id=? "
    "AND source='mobile' AND status='desktop_imported' AND deleted_at=''",
    (ACCOUNT_ID, PROJECT_ID),
).fetchone()[0]

print(
    "MIGRATION_OK "
    f"project_changed={project_changed} photos_changed={photos_changed} "
    f"batches_changed={batches_changed} sessions_changed={sessions_changed}"
)
print(
    f"AFTER_PENDING_TARGET={pending_target} AFTER_PENDING_OTHER={pending_other} "
    f"AFTER_IMPORTED={imported_after}"
)

if pending_other != 0:
    raise SystemExit("ABORT_AFTER_COMMIT: pending photos still point to another machine")
if imported_after != before_imported:
    raise SystemExit("ABORT_AFTER_COMMIT: imported photo count changed unexpectedly")

conn.close()
