"""Isolated SQLite + real Flask endpoint tests; never contacts production."""
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch
from werkzeug.security import generate_password_hash
from server import app as server_app, config, db
from server.admin_ops import dashboard, record_activity


@contextmanager
def test_connection():
    conn = db.connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


class AdminOpsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='album-admin-test-')
        root = Path(self.temp.name)
        self.patches = [patch.object(config, k, v) for k, v in {
            'DB_PATH': root/'test.db', 'DATA_DIR': root,
            'ADMIN_USERNAME': '', 'ADMIN_PASSWORD': '',
            'MOBILE_STORAGE_BACKEND': 'local', 'MOBILE_STORAGE_DIR': root/'objects',
        }.items()]
        for p in self.patches: p.start()
        self.addCleanup(self.cleanup)
        self.app = server_app.create_app()
        self.client = self.app.test_client()
        server_app._rate_hits.clear()
        with test_connection() as conn:
            conn.executemany('INSERT INTO accounts(id,username,password_hash,role,status) VALUES (?,?,?,?,?)',
                [(1,'admin',generate_password_hash('test-only'),'admin','active'),
                 (2,'customer',generate_password_hash('test-only'),'user','active'),
                 (3,'another',generate_password_hash('test-only'),'user','active')])
            conn.execute("INSERT INTO licenses(account_id,license_type,expires_at,active) VALUES(2,'term','2000-01-01T00:00:00Z',1)")
            conn.execute("INSERT INTO machines(account_id,machine_id,active) VALUES(2,'TEST',1)")
        self.admin = server_app._token_for(1)
        self.user = server_app._token_for(2)

    def cleanup(self):
        for p in reversed(self.patches): p.stop()
        self.temp.cleanup()

    def headers(self, token): return {'Authorization': 'Bearer '+token}

    def status(self, status, account=2, token=None):
        return self.client.post(f'/api/admin/accounts/{account}/status',
            headers=self.headers(token or self.admin), json={'status': status, 'note':'验收备注'})

    def test_admin_only_and_validation(self):
        self.assertEqual(self.client.get('/api/admin/dashboard').status_code,403)
        self.assertEqual(self.client.get('/api/admin/dashboard', headers=self.headers(self.user)).status_code,403)
        self.assertEqual(self.status('disabled',token=self.user).status_code,403)
        self.assertEqual(self.status('disabled',account=1).status_code,400)
        self.assertEqual(self.status('disabled',account=999).status_code,404)
        self.assertEqual(self.status(['disabled']).status_code,400)

    def test_archive_recovery_and_old_token_invalidation(self):
        legacy=server_app.serializer.dumps({'uid':2},salt='album-auth')
        self.assertEqual(self.client.get('/api/me',headers=self.headers(legacy)).status_code,200)
        self.assertEqual(self.status('disabled').status_code,200)
        for token in [legacy,self.user]:
            self.assertEqual(self.client.get('/api/me',headers=self.headers(token)).status_code,401)
        self.assertEqual(self.client.post('/api/login',json={'username':'customer','password':'test-only'}).status_code,403)
        self.assertFalse(self.status('disabled').json['changed'])
        self.assertEqual(self.status('active').status_code,200)
        for token in [legacy,self.user]:
            self.assertEqual(self.client.get('/api/me',headers=self.headers(token)).status_code,401)
        login=self.client.post('/api/login',json={'username':'customer','password':'test-only'})
        self.assertEqual(login.status_code,200)
        self.assertEqual(self.client.get('/api/me',headers=self.headers(login.json['token'])).status_code,200)
        with test_connection() as conn:
            lic=conn.execute('SELECT * FROM licenses WHERE account_id=2').fetchone()
            self.assertEqual(lic['expires_at'],'2000-01-01T00:00:00Z')
            self.assertEqual(lic['active'],1)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM machines WHERE account_id=2').fetchone()[0],1)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM admin_account_audit').fetchone()[0],2)

    def test_mobile_old_token_invalid_after_restore(self):
        with test_connection() as conn:
            conn.execute("INSERT INTO wechat_bindings(id,account_id,app_id,openid,created_at,last_login_at) VALUES(1,2,'test','test','now','now')")
        token=server_app._token_for(2,scope='mobile',binding_id=1,mobile_auth_version=0)
        self.assertIsNotNone(server_app._user_from_token(token))
        self.status('disabled');self.status('active')
        self.assertIsNone(server_app._user_from_token(token))

    def test_daily_dedup_timezone_missing_history(self):
        before=datetime(2026,9,7,15,59,tzinfo=timezone.utc)
        current=datetime(2026,9,7,16,1,tzinfo=timezone.utc)
        user={'id':2,'role':'user','status':'active','_token_scope':'desktop'}
        record_activity(user,before.timestamp())
        record_activity(user,current.timestamp());record_activity(user,current.timestamp())
        record_activity({**user,'_token_scope':'mobile'},current.timestamp())
        record_activity({**user,'id':1,'role':'admin'},current.timestamp())
        record_activity({**user,'id':3,'status':'disabled'},current.timestamp())
        with test_connection() as conn:
            conn.execute("UPDATE admin_metrics_meta SET value='2026-09-07T00:00:00Z' WHERE key='started_at'")
            data=dashboard(conn,current)
        self.assertEqual(data['day'],'2026-09-08')
        self.assertEqual(data['today_active'],1)
        self.assertEqual(data['week_active'],1)
        self.assertEqual(data['recent_active'],1)
        self.assertEqual(sum(x['active'] for x in data['channels']),2)
        self.assertIsNone(data['trend'][0]['active'])
        self.assertEqual(data['trend'][-2]['active'],1)

    def test_real_request_collection_excludes_admin_and_failures(self):
        self.client.get('/api/me',headers=self.headers(self.user))
        self.client.get('/api/me',headers=self.headers(self.user))
        self.client.get('/api/admin/dashboard',headers=self.headers(self.admin))
        self.client.get('/api/admin/accounts',headers=self.headers(server_app._token_for(3)))
        with test_connection() as conn:
            rows=conn.execute('SELECT account_id FROM admin_usage_daily').fetchall()
        self.assertEqual([x[0] for x in rows],[2])

    def test_legacy_local_timestamps_not_shifted_twice(self):
        with test_connection() as conn:
            conn.execute("UPDATE accounts SET created_at='2026-09-07 23:59:00'")
            conn.execute("INSERT INTO client_error_logs(created_at) VALUES('2026-09-07 23:59:00')")
            data=dashboard(conn,datetime(2026,9,7,16,1,tzinfo=timezone.utc))
        self.assertEqual(data['registered_today'],0)
        self.assertEqual(data['errors_today'],0)

    def test_metrics_failure_does_not_break_login(self):
        with patch('server.admin_ops.record_activity',side_effect=RuntimeError('test failure')):
            self.assertEqual(self.client.get('/api/me',headers=self.headers(self.user)).status_code,200)

    def test_accounts_excludes_password_hash_and_includes_audit(self):
        self.status('disabled')
        data=self.client.get('/api/admin/accounts',headers=self.headers(self.admin)).json
        account=next(x['account'] for x in data['accounts'] if x['account']['id']==2)
        self.assertNotIn('password_hash',account)
        self.assertEqual(account['status'],'disabled')
        self.assertEqual(account['last_status_change']['note'],'验收备注')


if __name__=='__main__': unittest.main()
