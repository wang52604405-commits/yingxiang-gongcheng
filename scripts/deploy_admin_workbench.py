"""One-time guarded deployment. Run only on the named production server.

Upload app.py, db.py, admin_ops.py, admin.html beside this script in
/opt/album-auth/.deploy-admin-20260908. Backups never leave the server.
"""
from pathlib import Path
import hashlib
import json
import os
import py_compile
import shutil
import sqlite3
import subprocess
import time
import urllib.error
import urllib.request

ROOT = Path('/opt/album-auth')
STAGE = ROOT / '.deploy-admin-20260908'
BACKUP = Path('/var/backups/admin-dashboard-20260908')
FILES = {'app.py':'server/app.py', 'db.py':'server/db.py',
         'admin_ops.py':'server/admin_ops.py', 'admin.html':'server/templates/admin.html'}
EXPECTED = {'app.py':'19feeed35bbaaafa498ee94f91768089a9efcbe2d7be3d7985470178e0e95688',
            'db.py':'fca312dc2f4249194c59268a1d5d2c1a4a959e4633455bd46ee84d8ed0aa8bb9',
            'admin.html':'2a26e874fe15e8b09740218b8903264047572b3503527914b7ccf3b1527b893c'}

def main():
    if Path(__file__).resolve().parent != STAGE or not (ROOT/'venv/bin/gunicorn').exists():
        raise SystemExit('Wrong deployment environment')
    for name, relative in FILES.items():
        source, target = STAGE/name, ROOT/relative
        if not source.is_file(): raise RuntimeError('Missing staged file: '+name)
        if name in EXPECTED:
            if hashlib.sha256(target.read_bytes()).hexdigest()!=EXPECTED[name]:
                raise RuntimeError('Live code changed; abort: '+relative)
        elif target.exists():
            raise RuntimeError('New module already exists; abort')
        if name.endswith('.py'): py_compile.compile(str(source),doraise=True)
    BACKUP.mkdir(mode=0o700,exist_ok=False)
    for name, relative in FILES.items():
        if name in EXPECTED: shutil.copy2(ROOT/relative,BACKUP/name)
    source=sqlite3.connect('file:/opt/album-auth/data/server.db?mode=ro',uri=True)
    target=sqlite3.connect(BACKUP/'server.db')
    try: source.backup(target)
    finally: source.close();target.close()
    os.chmod(BACKUP/'server.db',0o600)
    try:
        for name,relative in FILES.items():
            os.chmod(STAGE/name,0o644)
            os.replace(STAGE/name,ROOT/relative)
        subprocess.run(['systemctl','kill','--kill-who=main','--signal=HUP','album-auth'],check=True)
        for attempt in range(30):
            try:
                with urllib.request.urlopen('http://127.0.0.1:8000/admin',timeout=2) as response:
                    assert 'usageStats' in response.read().decode()
                try:
                    urllib.request.urlopen('http://127.0.0.1:8000/api/admin/dashboard',timeout=2)
                    raise RuntimeError('Dashboard unexpectedly public')
                except urllib.error.HTTPError as error:
                    assert error.code==403
                conn=sqlite3.connect('file:/opt/album-auth/data/server.db?mode=ro',uri=True)
                try: conn.execute('SELECT day FROM admin_usage_daily LIMIT 1').fetchall()
                finally: conn.close()
                break
            except (AssertionError,urllib.error.URLError,sqlite3.Error):
                if attempt==29: raise
                time.sleep(0.5)
        subprocess.run(['systemctl','is-active','album-auth'],check=True)
    except Exception:
        # Revert only code; never restore an old database over live new uploads.
        for name,relative in FILES.items():
            if name in EXPECTED: shutil.copy2(BACKUP/name,ROOT/relative)
        subprocess.run(['systemctl','kill','--kill-who=main','--signal=HUP','album-auth'],check=True)
        raise
    print(json.dumps({'backup':str(BACKUP),'files':{relative:hashlib.sha256((ROOT/relative).read_bytes()).hexdigest() for relative in FILES.values()}}))

if __name__=='__main__': main()
