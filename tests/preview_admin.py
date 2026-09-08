"""Loopback-only UI fixture; never deploy this server or its synthetic data."""
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import json
HTML = Path(__file__).resolve().parents[1] / 'server/templates/admin.html'
class Preview(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def do_GET(self):
        if self.path=='/admin':
            self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8');self.end_headers();self.wfile.write(HTML.read_bytes());return
        if self.path.startswith('/api/admin/accounts'):
            data={'accounts':[{'account':{'id':i,'username':name,'display_name':'测试客户','status':'active'},'license':{'has_license':i!=3,'license_type':'lifetime' if i==2 else 'term','expires_at':'2026-01-01T00:00:00Z' if i==4 else '2027-09-08T00:00:00Z','machine_limit':3,'machine_count':1,'machines':[{'machine_id':'TEST-DEVICE-'+str(i)}]},'invite_code':'DEMO'+str(i),'invite_qualified_count':i,'invite_count':i} for i,name in enumerate(['水利项目测试','房建项目测试','免费账号测试','过期账号测试'],1)]}
        elif self.path.startswith('/api/admin/errors'):
            data={'summary':{'total':3,'unresolved':3,'critical':1},'errors':[{'id':i,'fingerprint':'network' if i<3 else 'server','source':'desktop','severity':'error' if i<3 else 'critical','username':'测试客户','account_id':1,'app_version':'测试版本','machine_id':'脱敏测试标识','message':'照片同步请求超时' if i<3 else '读取项目失败','error_type':'TimeoutError' if i<3 else 'HTTPError','context':{'url':'/api/cloud/sync' if i<3 else '/api/projects','method':'POST' if i<3 else 'GET','status':504 if i<3 else 500},'created_at':'2026-09-08T07:00:00Z','resolved':0,'resolution_note':''} for i in range(3,0,-1)]}
        elif self.path.startswith('/api/product-config'): data={'product':{'free':{'photo_limit':0},'invite':{'reward_days':0}}}
        elif self.path.startswith('/api/me'): data={'account':{'role':'admin','username':'界面验收（测试数据）'}}
        else: data={}
        self.respond(data)
    def do_POST(self):
        self.rfile.read(int(self.headers.get('Content-Length',0)))
        self.respond({'token':'preview-only','account':{'role':'admin','username':'界面验收（测试数据）'}})
    def respond(self,data):
        self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(json.dumps({'ok':True,**data}).encode())
if __name__=='__main__':HTTPServer(('127.0.0.1',8769),Preview).serve_forever()
