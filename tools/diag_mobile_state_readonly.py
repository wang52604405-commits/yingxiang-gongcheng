import hashlib
import json
import os
import sqlite3
import subprocess
from pathlib import Path

pid = subprocess.check_output(['systemctl','show','--property=MainPID','--value','album-auth'], text=True).strip()
if not pid or pid == '0': raise SystemExit('album-auth not running')
env={}
for item in Path(f'/proc/{pid}/environ').read_bytes().split(b'\0'):
    key,sep,value=item.partition(b'=')
    if sep: env[key.decode('utf-8','surrogateescape')]=value.decode('utf-8','surrogateescape')
cwd=Path(os.readlink(f'/proc/{pid}/cwd'))
db=Path(env.get('ALBUM_SERVER_DB') or ((Path(env['ALBUM_SERVER_DATA'])/'server.db') if env.get('ALBUM_SERVER_DATA') else (cwd/'data'/'server.db')))
if not db.is_absolute(): db=cwd/db
con=sqlite3.connect(f'file:{db.resolve()}?mode=ro',uri=True); con.row_factory=sqlite3.Row
h=lambda v: hashlib.sha256(str(v or '').encode()).hexdigest()[:12] if v else ''
def dump(label, rows): print(label+'='+json.dumps(rows,ensure_ascii=True))

rows=con.execute("SELECT project_owner_account_id owner_id,status,COUNT(*) n,SUM(CASE WHEN deleted_at<>'' THEN 1 ELSE 0 END) deleted_n,MIN(created_at) first_at,MAX(created_at) last_at,MAX(updated_at) last_update FROM cloud_photos WHERE source='mobile' GROUP BY project_owner_account_id,status ORDER BY project_owner_account_id,status").fetchall()
dump('GLOBAL',[dict(r) for r in rows])
rows=con.execute("SELECT project_owner_account_id owner_id,target_machine_id,COUNT(*) n,SUM(CASE WHEN status='desktop_imported' THEN 1 ELSE 0 END) imported_n,SUM(CASE WHEN deleted_at<>'' THEN 1 ELSE 0 END) deleted_n,MAX(updated_at) last_update FROM cloud_photos WHERE source='mobile' GROUP BY project_owner_account_id,target_machine_id ORDER BY n DESC LIMIT 100").fetchall()
out=[]
for r in rows:
    d=dict(r); d['target_machine_hash']=h(d.pop('target_machine_id')); out.append(d)
dump('MACHINES',out)

rows=con.execute("SELECT id,account_id,machine_id,active,bound_at,last_seen FROM machines WHERE account_id=40 ORDER BY id").fetchall()
out=[]
for r in rows:
    d=dict(r); d['machine_hash']=h(d.pop('machine_id')); out.append(d)
dump('OWNER40_MACHINE_ROWS',out)
rows=con.execute("SELECT account_id,project_id,project_code,project_name,revision,desktop_machine_id,active,created_at,updated_at FROM cloud_engineering_projects WHERE account_id=40 ORDER BY updated_at DESC").fetchall()
out=[]
for r in rows:
    d=dict(r); d['desktop_machine_hash']=h(d.pop('desktop_machine_id')); out.append(d)
dump('OWNER40_PROJECTS',out)
rows=con.execute("SELECT account_id,client_id,snapshot_id,snapshot_revision,updated_at FROM desktop_sync_cursors WHERE account_id=40 ORDER BY updated_at DESC").fetchall()
out=[]
for r in rows:
    d=dict(r); d['client_hash']=h(d.pop('client_id')); d['snapshot_id_hash']=h(d.pop('snapshot_id')); out.append(d)
dump('OWNER40_SYNC_CURSORS',out)

rows=con.execute("SELECT id,batch_id,photo_uuid,project_id,status,target_machine_id,scope,category,assignment_json,title,photo_date,original_size_bytes,original_mime_type,original_cleanup_status,created_at,updated_at,error_code,error_message FROM cloud_photos WHERE source='mobile' AND project_owner_account_id=40 AND status='desktop_pending' AND deleted_at='' ORDER BY id LIMIT 15").fetchall()
out=[]
for r in rows:
    d=dict(r)
    try: assignment=json.loads(d.pop('assignment_json') or '{}')
    except Exception: assignment={}
    d['uuid_hash']=h(d.pop('photo_uuid')); d['target_machine_hash']=h(d.pop('target_machine_id')); d['assignment']=assignment
    out.append(d)
dump('OWNER40_FIRST_PENDING',out)

rows=con.execute("SELECT id,batch_id,photo_uuid,local_project_code,local_photo_id,scope,category,assignment_json,title,photo_date,original_size_bytes,created_at,desktop_imported_at FROM cloud_photos WHERE source='mobile' AND project_owner_account_id=40 AND status='desktop_imported' ORDER BY id LIMIT 20").fetchall()
out=[]
for r in rows:
    d=dict(r)
    try: assignment=json.loads(d.pop('assignment_json') or '{}')
    except Exception: assignment={}
    d['uuid_hash']=h(d.pop('photo_uuid')); d['assignment']=assignment; out.append(d)
dump('OWNER40_IMPORTED',out)

pending_rows=con.execute("SELECT id,scope,assignment_json,project_id FROM cloud_photos WHERE source='mobile' AND project_owner_account_id=40 AND status='desktop_pending' AND deleted_at='' ORDER BY id LIMIT 15").fetchall()
checks=[]
for r in pending_rows:
    try: a=json.loads(r['assignment_json'] or '{}')
    except Exception: a={}
    unit=str(a.get('unit_code') or a.get('other_node_code') or '')
    process=str(a.get('process_name') or '')
    unit_row=con.execute("SELECT active,name FROM cloud_units WHERE account_id=40 AND project_id=? AND scope=? AND node_code=? ORDER BY id DESC LIMIT 1",(r['project_id'],r['scope'],unit)).fetchone() if unit else None
    process_active=None
    if process and r['scope']=='engineering':
        pr=con.execute("SELECT active FROM cloud_units WHERE account_id=40 AND project_id=? AND scope='engineering' AND node_type='process' AND name=? AND parent_code=? ORDER BY id DESC LIMIT 1",(r['project_id'],process,unit)).fetchone()
        process_active=int(pr['active']) if pr else None
    checks.append({'id':r['id'],'unit_code':unit,'process_name':process,'unit_active':int(unit_row['active']) if unit_row else None,'process_active':process_active})
dump('OWNER40_ASSIGNMENT_CHECKS',checks)

rows=con.execute("SELECT id,source,severity,error_type,message,app_version,machine_id,client_time,created_at FROM client_error_logs WHERE account_id=40 ORDER BY id DESC LIMIT 30").fetchall()
out=[]
for r in rows:
    d=dict(r); d['machine_hash']=h(d.pop('machine_id')); d['message']=str(d.get('message') or '')[:300]; out.append(d)
dump('OWNER40_ERRORS',out)
