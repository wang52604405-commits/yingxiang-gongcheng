# -*- coding: utf-8 -*-
"""登录、注册和找回密码的体验契约。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server import app as server_app
from server import config, db


class AccountExperienceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="album-experience-")
        root = Path(self.tmp.name)
        self.patches = [
            patch.object(config, key, value)
            for key, value in {
                "DB_PATH": root / "auth.sqlite",
                "DATA_DIR": root,
                "ADMIN_USERNAME": "",
                "ADMIN_PASSWORD": "",
                "MOBILE_STORAGE_BACKEND": "local",
                "MOBILE_STORAGE_DIR": root / "objects",
            }.items()
        ]
        for item in self.patches:
            item.start()
        self.addCleanup(self._cleanup)
        self.client = server_app.create_app().test_client()
        server_app._rate_hits.clear()

    def _cleanup(self):
        for item in reversed(self.patches):
            item.stop()
        self.tmp.cleanup()

    def login(self, username, password):
        response = self.client.post("/api/login", json={"username": username, "password": password})
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def test_email_username_is_saved_for_recovery_and_weak_password_stays_rejected(self):
        weak = self.client.post("/api/register", json={"username": "owner@example.com", "password": "password"})
        self.assertEqual(weak.status_code, 400)
        self.assertIn("至少 8 位", weak.get_json()["error"])
        self.assertIn("字母和数字", weak.get_json()["error"])
        created = self.client.post("/api/register", json={"username": "owner@example.com", "password": "Passw0rd"})
        self.assertEqual(created.status_code, 200, created.get_json())
        conn = db.connect()
        try:
            row = conn.execute("SELECT email FROM accounts WHERE username = 'owner@example.com'").fetchone()
            self.assertEqual(row["email"], "owner@example.com")
        finally:
            conn.close()
        me = self.login("owner@example.com", "Passw0rd")
        self.assertTrue(me["account"]["email_bound"])
        self.assertNotIn("owner@example.com", me["account"]["recovery_email"])
        self.assertIn("@", me["account"]["recovery_email"])

    def test_recovery_accepts_bound_email_and_hides_mail_errors(self):
        self.client.post("/api/register", json={
            "username": "13800001111",
            "password": "Passw0rd",
            "email": "findme@example.com",
        })
        with patch("server.mailer.send_code_email", return_value=None) as sender:
            sent = self.client.post("/api/forgot-password", json={"account": "findme@example.com"})
        self.assertEqual(sent.status_code, 200, sent.get_json())
        self.assertIn("***", sent.get_json()["email"])
        self.assertNotIn("findme@example.com", sent.get_json()["email"])
        sender.assert_called_once()
        conn = db.connect()
        try:
            row = conn.execute("SELECT code_key, code FROM mail_codes").fetchone()
            self.assertEqual(row["code_key"], "reset:13800001111")
            code = row["code"]
        finally:
            conn.close()
        weak = self.client.post("/api/reset-password", json={
            "account": "findme@example.com", "code": code, "new_password": "short",
        })
        self.assertEqual(weak.status_code, 400)
        self.assertIn("至少 8 位", weak.get_json()["error"])
        reset = self.client.post("/api/reset-password", json={
            "account": "findme@example.com", "code": code, "new_password": "NewPassw0rd",
        })
        self.assertEqual(reset.status_code, 200, reset.get_json())
        self.assertIn("新密码", reset.get_json()["message"])
        self.assertEqual(self.client.post("/api/login", json={
            "username": "13800001111", "password": "Passw0rd",
        }).status_code, 401)
        self.assertEqual(self.client.post("/api/login", json={
            "username": "13800001111", "password": "NewPassw0rd",
        }).status_code, 200)

        missing = self.client.post("/api/forgot-password", json={"account": "nobody-here"})
        self.assertIn("没有找到这个账号", missing.get_json()["error"])
        plain = self.client.post("/api/register", json={"username": "13900002222", "password": "Passw0rd"})
        self.assertEqual(plain.status_code, 200, plain.get_json())
        unbound = self.client.post("/api/forgot-password", json={"account": "13900002222"})
        self.assertIn("未绑定邮箱", unbound.get_json()["error"])
        self.assertIn("管理员", unbound.get_json()["error"])
        with patch("server.mailer.send_code_email", side_effect=RuntimeError("smtp secret findme@example.com")):
            failed = self.client.post("/api/forgot-password", json={"account": "findme@example.com"})
        self.assertEqual(failed.status_code, 400)
        self.assertNotIn("secret", failed.get_json()["error"])
        self.assertNotIn("findme@example.com", failed.get_json()["error"])
        self.assertIn("稍后再试", failed.get_json()["error"])

    def test_recovery_email_can_be_added_once_after_login(self):
        self.client.post("/api/register", json={"username": "13900003333", "password": "Passw0rd"})
        token = self.login("13900003333", "Passw0rd")["token"]
        headers = {"Authorization": "Bearer " + token}
        denied = self.client.post("/api/account/recovery-email", json={"email": "later@example.com"})
        self.assertEqual(denied.status_code, 401)
        saved = self.client.post(
            "/api/account/recovery-email",
            json={"email": "later@example.com"},
            headers=headers,
        )
        self.assertEqual(saved.status_code, 200, saved.get_json())
        again = self.client.post(
            "/api/account/recovery-email",
            json={"email": "other@example.com"},
            headers=headers,
        )
        self.assertEqual(again.status_code, 400)
        self.assertIn("已经绑定", again.get_json()["error"])

    def test_cloud_thumbs_page_without_removing_the_full_list(self):
        self.client.post("/api/register", json={"username": "13900004444", "password": "Passw0rd"})
        token = self.login("13900004444", "Passw0rd")["token"]
        headers = {"Authorization": "Bearer " + token}
        conn = db.connect()
        try:
            account_id = conn.execute("SELECT id FROM accounts WHERE username = '13900004444'").fetchone()["id"]
            cur = conn.execute(
                "INSERT INTO cloud_projects (account_id, project_code, project_name, thumb_count) VALUES (?, 'P1', '预览工程', 3)",
                (account_id,),
            )
            project_id = cur.lastrowid
            for index, name in enumerate(("a.webp", "b.webp", "c.webp")):
                conn.execute(
                    "INSERT INTO cloud_thumbs (project_id, photo_name, thumb_b64, order_index) VALUES (?, ?, ?, ?)",
                    (project_id, name, "QUJD" + str(index), index),
                )
            conn.commit()
        finally:
            conn.close()
        full = self.client.get(f"/api/cloud/thumbs?project_id={project_id}", headers=headers)
        self.assertEqual(full.status_code, 200, full.get_json())
        self.assertEqual(full.get_json()["total"], 3)
        self.assertEqual(len(full.get_json()["thumbs"]), 3)
        self.assertNotIn("limit", full.get_json())
        page = self.client.get(f"/api/cloud/thumbs?project_id={project_id}&limit=2&offset=0", headers=headers)
        self.assertEqual([item["photo_name"] for item in page.get_json()["thumbs"]], ["a.webp", "b.webp"])
        self.assertEqual(page.get_json()["total"], 3)
        rest = self.client.get(f"/api/cloud/thumbs?project_id={project_id}&limit=2&offset=2", headers=headers)
        self.assertEqual([item["photo_name"] for item in rest.get_json()["thumbs"]], ["c.webp"])
        bad = self.client.get(f"/api/cloud/thumbs?project_id={project_id}&limit=99", headers=headers)
        self.assertEqual(bad.status_code, 400)
        self.assertIn("60", bad.get_json()["error"])

    def test_login_pages_keep_clear_steps_and_password_rule(self):
        root = Path(__file__).resolve().parents[1]
        cloud = (root / "server" / "templates" / "cloud.html").read_text(encoding="utf-8")
        member = (root / "server" / "templates" / "member_center.html").read_text(encoding="utf-8")
        license_page = (root / "templates" / "license.html").read_text(encoding="utf-8")
        self.assertIn("手机原图仅短期中转到绑定电脑", cloud)
        self.assertIn("电脑确认归档后服务器删除原图", cloud)
        self.assertNotIn("平台只同步缩略图，不上传工程原图", cloud)
        self.assertIn("Promise.all([loadProduct(), checkAuth()])", cloud)
        self.assertIn("limit=", cloud)
        self.assertIn("重新发送", cloud)
        self.assertNotIn("regDeleteAck", cloud)
        self.assertIn("登录密码至少 8 位，并同时包含字母和数字", cloud)
        self.assertIn('function showAccountPanel(panel, updateHash = true)', member)
        self.assertIn('location.hash === "#register" ? "register"', member)
        self.assertIn('history.replaceState(null, "", location.pathname);', member)
        self.assertIn('window.scrollTo(0, 0);', member)
        self.assertIn("Promise.all([loadProduct(), refreshCloud()])", member)
        self.assertNotIn("regDeleteAck", member)
        self.assertIn('let registrationRequested = new URLSearchParams(location.search).get("register") === "1"', license_page)
        self.assertIn("if (registrationRequested) showRegistrationForm();", license_page)
        self.assertIn("重新发送", license_page)
        self.assertIn("id=\"regDeletePass\"", license_page)
        self.assertIn("请勿使用过于简单的数字", license_page)
        index = (root / "templates" / "index.html").read_text(encoding="utf-8")
        desktop_js = next((root / "assets").glob("app-A*.js")).read_text(encoding="utf-8")
        self.assertIn('id="gateRegisterBtn" href="https://shuiliyingxiang.cn/member#register"', index)
        self.assertIn('id="gateForgotBtn" href="https://shuiliyingxiang.cn/member#forgot"', index)
        self.assertIn('["gateUsername", "gatePassword"]', desktop_js)
        self.assertIn("请填写账号和密码", desktop_js)
        mini = (root / "miniprogram" / "src" / "pages" / "auth" / "bind.vue").read_text(encoding="utf-8")
        self.assertIn("重新发送", mini)


if __name__ == "__main__":
    unittest.main()
