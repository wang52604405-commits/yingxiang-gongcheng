import os
import sqlite3
import subprocess
from pathlib import Path

TARGET = "2ED2E5FE-E887-4094-A095-EEB3B0B4D16D".upper()

pid = subprocess.check_output(
    ["systemctl", "show", "--property=MainPID", "--value", "album-auth"],
    text=True,
).strip()
env = {}
for item in Path(f"/proc/{pid}/environ").read_bytes().split(b"\0"):
    key, sep, value = item.partition(b"=")
    if sep:
        env[key.decode("utf-8", "surrogateescape")] = value.decode("utf-8", "surrogateescape")
cwd = Path(os.readlink(f"/proc/{pid}/cwd"))
db = Path(env.get("ALBUM_SERVER_DB") or (Path(env["ALBUM_SERVER_DATA"]) / "server.db" if env.get("ALBUM_SERVER_DATA") else cwd / "data" / "server.db"))
if not db.is_absolute():
    db = cwd / db
conn = sqlite3.connect(f"file:{db.resolve()}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row

matches = []
for table_row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
    table = table_row[0]
    cols = [row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')]
    for col in cols:
        try:
            rows = conn.execute(
                f'SELECT rowid,* FROM "{table}" WHERE UPPER(CAST("{col}" AS TEXT))=? LIMIT 20',
                (TARGET,),
            ).fetchall()
        except sqlite3.DatabaseError:
            continue
        for row in rows:
            payload = {"table": table, "column": col, "rowid": row[0]}
            for key in ("id","account_id","project_owner_account_id","project_id","machine_id","client_id","desktop_machine_id","target_machine_id","active","status","bound_at","last_seen","created_at","updated_at"):
                if key in row.keys():
                    payload[key] = row[key]
            matches.append(payload)

print("MATCHES=" + repr(matches))
print("ACCOUNT40_MACHINES=" + repr([
    dict(row) for row in conn.execute(
        "SELECT id,machine_id,active,bound_at,last_seen FROM machines WHERE account_id=40 ORDER BY id"
    ).fetchall()
]))
conn.close()
