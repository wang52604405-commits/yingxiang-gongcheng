import hashlib
import json
import os
import sqlite3
import subprocess
from pathlib import Path

pid = subprocess.check_output([
    'systemctl', 'show', '--property=MainPID', '--value', 'album-auth'
], text=True).strip()
if not pid or pid == '0':
    raise SystemExit('album-auth not running')
env = {}
for item in Path(f'/proc/{pid}/environ').read_bytes().split(b'\0'):
    key, sep, value = item.partition(b'=')
    if sep:
        env[key.decode('utf-8', 'surrogateescape')] = value.decode('utf-8', 'surrogateescape')
cwd = Path(os.readlink(f'/proc/{pid}/cwd'))
db = Path(env.get('ALBUM_SERVER_DB') or ((Path(env['ALBUM_SERVER_DATA']) / 'server.db') if env.get('ALBUM_SERVER_DATA') else (cwd / 'data' / 'server.db')))
if not db.is_absolute():
    db = cwd / db
con = sqlite3.connect(f'file:{db.resolve()}?mode=ro', uri=True)
con.row_factory = sqlite3.Row
h = lambda value: hashlib.sha256(str(value or '').encode()).hexdigest()[:12] if value else ''

rows = con.execute(
    "SELECT project_owner_account_id owner_id,status,COUNT(*) n,"
    "SUM(CASE WHEN deleted_at<>'' THEN 1 ELSE 0 END) deleted_n,"
    "MIN(created_at) first_at,MAX(created_at) last_at,MAX(updated_at) last_update "
    "FROM cloud_photos WHERE source='mobile' "
    "GROUP BY project_owner_account_id,status ORDER BY project_owner_account_id,status"
).fetchall()
print('GLOBAL=' + json.dumps([dict(row) for row in rows], ensure_ascii=True))

rows = con.execute(
    "SELECT project_owner_account_id owner_id,target_machine_id,COUNT(*) n,"
    "SUM(CASE WHEN status='desktop_imported' THEN 1 ELSE 0 END) imported_n,"
    "SUM(CASE WHEN deleted_at<>'' THEN 1 ELSE 0 END) deleted_n,MAX(updated_at) last_update "
    "FROM cloud_photos WHERE source='mobile' "
    "GROUP BY project_owner_account_id,target_machine_id ORDER BY n DESC LIMIT 100"
).fetchall()
items = []
for row in rows:
    item = dict(row)
    item['target_machine_hash'] = h(item.pop('target_machine_id'))
    items.append(item)
print('MACHINES=' + json.dumps(items, ensure_ascii=True))

rows = con.execute(
    "SELECT id,batch_id,photo_uuid,status,local_project_code,local_photo_id,created_at,updated_at,"
    "desktop_imported_at,deleted_at,deleted_by_machine_id,deleted_by_account_id,error_code,error_message,"
    "target_machine_id,original_cleanup_status,original_deleted_at,preview_storage_key,original_storage_key,storage_key "
    "FROM cloud_photos WHERE source='mobile' AND project_owner_account_id=1 ORDER BY id DESC LIMIT 30"
).fetchall()
items = []
for row in rows:
    item = dict(row)
    item['uuid_hash'] = h(item.pop('photo_uuid'))
    item['target_machine_hash'] = h(item.pop('target_machine_id'))
    item['deleted_by_machine_hash'] = h(item.pop('deleted_by_machine_id'))
    item['has_preview'] = bool(item.pop('preview_storage_key'))
    item['has_original_storage_key'] = bool(item.pop('original_storage_key'))
    item['has_storage_key'] = bool(item.pop('storage_key'))
    items.append(item)
print('ACCOUNT1=' + json.dumps(items, ensure_ascii=True))

rows = con.execute(
    "SELECT c.id,c.photo_uuid,c.action,c.actor_account_id,c.created_at,c.payload_json "
    "FROM mobile_photo_changes c JOIN cloud_photos p ON p.photo_uuid=c.photo_uuid "
    "WHERE p.source='mobile' AND p.project_owner_account_id=1 ORDER BY c.id DESC LIMIT 100"
).fetchall()
changes = []
for row in rows:
    item = dict(row)
    try:
        payload = json.loads(item.pop('payload_json') or '{}')
    except Exception:
        payload = {}
    changes.append({
        'id': item['id'],
        'uuid_hash': h(item['photo_uuid']),
        'action': item['action'],
        'actor_account_id': item['actor_account_id'],
        'created_at': item['created_at'],
        'payload_keys': sorted(payload.keys()),
        'local_project_code': payload.get('local_project_code'),
        'local_photo_id': payload.get('local_photo_id'),
    })
print('CHANGES=' + json.dumps(changes, ensure_ascii=True))
