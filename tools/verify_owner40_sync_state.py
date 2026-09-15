import os
import sqlite3
import subprocess
from pathlib import Path

ACCOUNT_ID=40
PROJECT_ID='FN2023GC0046'
NEW_MACHINE='HDYX-D3AE-10AF-BFEC-183E'
OLD_MACHINE='HDYX-1D35-A93B-5E1C-05AD'

pid=subprocess.check_output(['systemctl','show','--property=MainPID','--value','album-auth'],text=True).strip()
env={}
for item in Path(f'/proc/{pid}/environ').read_bytes().split(b'\0'):
    k,sep,v=item.partition(b'=')
    if sep:
        env[k.decode('utf-8','surrogateescape')]=v.decode('utf-8','surrogateescape')
cwd=Path(os.readlink(f'/proc/{pid}/cwd'))
db=Path(env.get('ALBUM_SERVER_DB') or (Path(env['ALBUM_SERVER_DATA'])/'server.db' if env.get('ALBUM_SERVER_DATA') else cwd/'data'/'server.db'))
if not db.is_absolute(): db=cwd/db
con=sqlite3.connect(f'file:{db.resolve()}?mode=ro',uri=True); con.row_factory=sqlite3.Row
project=con.execute('SELECT project_id,project_name,desktop_machine_id,updated_at FROM cloud_engineering_projects WHERE account_id=? AND project_id=?',(ACCOUNT_ID,PROJECT_ID)).fetchone()
print('PROJECT='+repr(dict(project) if project else None))
rows=con.execute("SELECT status,target_machine_id,COUNT(*) n,SUM(CASE WHEN deleted_at<>'' THEN 1 ELSE 0 END) deleted_n,MIN(desktop_imported_at) first_imported,MAX(desktop_imported_at) last_imported FROM cloud_photos WHERE project_owner_account_id=? AND project_id=? AND source='mobile' GROUP BY status,target_machine_id ORDER BY status,target_machine_id",(ACCOUNT_ID,PROJECT_ID)).fetchall()
print('GROUPS='+repr([dict(r) for r in rows]))
for label,machine in [('NEW',NEW_MACHINE),('OLD',OLD_MACHINE)]:
    row=con.execute("SELECT COUNT(*) total,SUM(CASE WHEN status='desktop_imported' AND deleted_at='' THEN 1 ELSE 0 END) imported,SUM(CASE WHEN status='desktop_pending' AND deleted_at='' THEN 1 ELSE 0 END) pending,SUM(CASE WHEN local_project_code<>'' AND local_photo_id<>'' THEN 1 ELSE 0 END) located FROM cloud_photos WHERE project_owner_account_id=? AND project_id=? AND source='mobile' AND target_machine_id=?",(ACCOUNT_ID,PROJECT_ID,machine)).fetchone()
    print(label+'='+repr(dict(row)))
print('BATCHES='+repr([dict(r) for r in con.execute("SELECT status,target_machine_id,COUNT(*) n FROM mobile_batches WHERE project_owner_account_id=? AND project_id=? GROUP BY status,target_machine_id ORDER BY status,target_machine_id",(ACCOUNT_ID,PROJECT_ID)).fetchall()]))
con.close()
