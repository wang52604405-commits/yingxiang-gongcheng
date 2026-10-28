"""Security regression: account password recovery and non-destructive username release."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from werkzeug.security import check_password_hash, generate_password_hash

from server import app as server_app, config, db


class AccountLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="album-lifecycle-")
        root = Path(self.tmp.name)
        self.patches = [
            patch.object(config, key, value) for key, value in {
                "DB_PATH": root / "auth.sqlite",
                "DATA_DIR": root,
                "ADMIN_USERNAME": "",
                "ADMIN_PASSWORD": "",
                "MOBILE_STORAGE_BACKEND": "local",
                "MOBILE_STORAGE_DIR": root / "objects",
            }.items()
        ]
        for p in self.patches:
            p.start()
        self.addCleanup(self._cleanup)
        self.client = server_app.create_app().test_client()
        server_app._rate_hits.clear()
        conn = db.connect()
        try:
            conn.execute(
                "INSERT INTO accounts(id,username,password_hash,role,status,email) "
                "VALUES (1,'admin',?,'admin','active','')",
                (generate_password_hash("AdminTest2026"),),
            )
            conn.execute(
                "INSERT INTO accounts(id,username,password_hash,role,status,email) "
                "VALUES (2,'customer',?,'user','active','')",
                (generate_password_hash("OldPassword2026"),),
            )
            conn.execute(
                "INSERT INTO machines(account_id,machine_id,active) VALUES(2,'MY-OLD-PC',1)"
            )
            conn.execute(
                "INSERT INTO licenses(account_id,license_type,expires_at,active) "
                "VALUES(2,'term','2029-12-30T00:00:00Z',1)"
            )
            conn.execute(
                "INSERT INTO cloud_projects(account_id,project_code,project_name) "
                "VALUES(2,'PROJ1','历史工程')"
            )
            conn.execute(
                "INSERT INTO wechat_bindings(id,account_id,app_id,openid,created_at,last_login_at) "
                "VALUES(1,2,'miniapp','openid-1','now','now')"
            )
            conn.execute(
                "INSERT INTO mail_codes(code_key,code,expires_at) VALUES('reset:customer','123456',9999999999)"
            )
            conn.commit()
        finally:
            conn.close()
        self.admin = server_app._token_for(1)
        self.old = server_app._token_for(2)
        self.mobile = server_app._token_for(2,scope="mobile",binding_id=1,mobile_auth_version=0)

    def _cleanup(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def h(self, token=None):
        return {"Authorization": "Bearer " + (token if token is not None else self.admin)}

    def post(self, route, *, username="customer", note="用户核实已联系", token=None):
        return self.client.post(
            "/api/admin/accounts/2/" + route,
            json={"confirm_username": username, "note": note},
            headers=self.h(token),
        )

    def test_no_privilege_or_admin_target(self):
        for route in ("reset-login-password", "retire"):
            self.assertEqual(
                self.client.post("/api/admin/accounts/2/" + route,
                                 json={"confirm_username":"customer", "note":"support"}).status_code,
                403,
            )
            self.assertEqual(self.post(route, token=self.old).status_code, 403)
            self.assertEqual(self.client.post(
                "/api/admin/accounts/1/" + route,
                headers=self.h(),
                json={"confirm_username":"admin","note":"support"},
            ).status_code, 403)
        self.assertEqual(self.post("reset-login-password",username="wrong").status_code,400)
        self.assertEqual(self.post("reset-login-password",note="").status_code,400)

    def test_reset_only_active_and_revokes_all_old_tokens(self):
        reset = self.post("reset-login-password")
        self.assertEqual(reset.status_code,200,reset.json)
        password = reset.json["temporary_password"]
        self.assertGreaterEqual(len(password),20)
        self.assertIn("7",password)
        self.assertEqual(self.client.get("/api/me",headers=self.h(self.old)).status_code,401)
        self.assertIsNone(server_app._user_from_token(self.mobile))
        self.assertEqual(self.client.post(
            "/api/login",json={"username":"customer","password":"OldPassword2026"}
        ).status_code,401)
        new_login = self.client.post(
            "/api/login",json={"username":"customer","password":password}
        )
        self.assertEqual(new_login.status_code,200,new_login.json)
        conn=db.connect()
        try:
            row=conn.execute("SELECT password_hash FROM accounts WHERE id=2").fetchone()
            self.assertTrue(check_password_hash(row["password_hash"],password))
            audit=conn.execute("SELECT note,status FROM admin_account_audit ORDER BY id DESC LIMIT 1").fetchone()
            self.assertEqual(audit["status"],"password_reset")
            self.assertNotIn(password,audit["note"])
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM cloud_projects WHERE account_id=2").fetchone()[0],1)
        finally:
            conn.close()

    def test_retirement_requires_disabled_exact_confirmation(self):
        self.assertEqual(self.post("retire").status_code,409)
        self.client.post("/api/admin/accounts/2/status",
                         headers=self.h(),json={"status":"disabled","note":"归档确认"})
        self.assertEqual(self.post("retire",username="another").status_code,400)
        self.assertEqual(self.post("retire",note="").status_code,400)
        self.assertEqual(self.post("reset-login-password").status_code,409)
        retired=self.post("retire")
        self.assertEqual(retired.status_code,200,retired.json)
        self.assertEqual(retired.json["released_username"],"customer")
        self.assertEqual(self.post("retire").status_code,409)
        self.assertIsNone(server_app._user_from_token(self.mobile))
        self.assertEqual(self.client.get("/api/me",headers=self.h(self.old)).status_code,401)
        self.assertEqual(self.client.post(
            "/api/login",json={"username":"customer","password":"OldPassword2026"}
        ).status_code,401)
        self.assertEqual(self.client.post("/api/admin/accounts/2/status",
                         headers=self.h(),json={"status":"active","note":"try restore"}).status_code,409)
        # An archived account must not be restored by the ordinary status route:
        # status remains retired (regression gate).
        conn=db.connect()
        try:
            row=conn.execute("SELECT username,status FROM accounts WHERE id=2").fetchone()
            self.assertEqual(row["status"],"retired")
            self.assertTrue(row["username"].startswith("__retired_2_"))
            self.assertEqual(conn.execute("SELECT active FROM machines WHERE account_id=2").fetchone()[0],0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM wechat_bindings WHERE account_id=2").fetchone()[0],0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM mail_codes WHERE code_key='reset:customer'").fetchone()[0],0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM cloud_projects WHERE account_id=2").fetchone()[0],1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM licenses WHERE account_id=2").fetchone()[0],1)
        finally:
            conn.close()

    def test_reused_username_creates_distinct_new_identity(self):
        self.client.post("/api/admin/accounts/2/status",
                         headers=self.h(),json={"status":"disabled","note":"support"})
        self.assertEqual(self.post("retire").status_code,200)
        create=self.client.post("/api/register",json={
            "username":"customer","password":"NewUser2026",
        })
        self.assertEqual(create.status_code,200,create.json)
        login=self.client.post("/api/login",json={
            "username":"customer","password":"NewUser2026",
        })
        self.assertEqual(login.status_code,200,login.json)
        self.assertNotEqual(login.json["account"]["id"],2)
        conn=db.connect()
        try:
            new_id=login.json["account"]["id"]
            self.assertEqual(conn.execute(
                "SELECT COUNT(*) FROM cloud_projects WHERE account_id=?",(new_id,)
            ).fetchone()[0],0)
            self.assertEqual(conn.execute(
                "SELECT COUNT(*) FROM cloud_projects WHERE account_id=2"
            ).fetchone()[0],1)
            self.assertEqual(conn.execute(
                "SELECT COUNT(*) FROM licenses WHERE account_id=?",(new_id,)
            ).fetchone()[0],0)
        finally:
            conn.close()

    def test_admin_ui_has_explicit_recovery_and_retire_controls(self):
        html=self.client.get("/admin").data.decode("utf-8")
        self.assertIn("id=\"recoveryDialog\"",html)
        self.assertIn("reset-login-password",html)
        self.assertIn("注销释放账号",html)


if __name__ == "__main__":
    unittest.main()
