import hashlib
import re
import subprocess

raw = subprocess.check_output([
    'journalctl', '-u', 'album-auth', '--no-pager', '--since', '2026-09-14 00:00:00'
], text=True, errors='replace')
pattern = re.compile(r'(/api/desktop/v1/(?:inbox|project-snapshot)[^\s\"]*)')
mid = re.compile(r'(desktop_machine_id|machine_id)=([^&\s]+)')
out=[]
for line in raw.splitlines():
    m=pattern.search(line)
    if not m: continue
    path=m.group(1)
    def repl(match):
        value=match.group(2)
        digest=hashlib.sha256(value.upper().encode()).hexdigest()[:12]
        return match.group(1)+'='+digest
    path=mid.sub(repl,path)
    # Do not print IPs, usernames or full journal text; keep timestamp prefix and endpoint only.
    prefix=' '.join(line.split()[:3])
    out.append(prefix+' '+path[:500])
print('ACCESS_COUNT='+str(len(out)))
for row in out[-200:]: print('ACCESS='+row)
