# -*- coding: utf-8 -*-
"""局域网媒体鉴权、空口令门禁、遗留删除口令指纹的负向契约。"""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app


LAN = {"REMOTE_ADDR": "192.168.1.50"}
LOOPBACK = {"REMOTE_ADDR": "127.0.0.1"}
ROOT = Path(__file__).resolve().parents[1]


class LanMediaSecurityTest(unittest.TestCase):
    def setUp(self):
        self.client = app.app.test_client()

    def test_unauthenticated_media_returns_401_and_keeps_traversal_guard(self):
        for path in (
            "/photos/SEC-UNIT/sample.jpg",
            "/thumbs/SEC-UNIT/sample.jpg",
            "/originals/SEC-UNIT/photo-1",
        ):
            response = self.client.get(path, environ_base=LOOPBACK)
            self.assertEqual(response.status_code, 401, path)
            body = response.get_json()
            self.assertFalse(body["ok"])
            self.assertIn("登录", body["error"])

        traversal = self.client.get("/photos/SEC-UNIT/%2e%2e", environ_base=LOOPBACK)
        self.assertEqual(traversal.status_code, 404)
        self.assertEqual(app._safe_media_name(".."), "")
        self.assertEqual(app._safe_media_name("../secret.jpg"), "secret.jpg")
        self.assertEqual(app._safe_media_name("..\\secret.jpg"), "")
        self.assertNotIn("/", app._safe_media_name("../secret.jpg"))
        self.assertNotIn("..", app._safe_media_name("../secret.jpg"))

        with tempfile.TemporaryDirectory() as temp_dir:
            photo_dir = Path(temp_dir)
            payload = b"\xff\xd8\xff\xd9"
            (photo_dir / "sample.jpg").write_bytes(payload)
            with self.client.session_transaction() as session:
                session["username"] = "本机看图"
            with patch.object(app.manager, "_photos_dir", return_value=photo_dir):
                allowed = self.client.get("/photos/SEC-UNIT/sample.jpg", environ_base=LOOPBACK)
            self.assertEqual(allowed.status_code, 200)
            self.assertEqual(allowed.data, payload)
            allowed.close()

    def test_empty_lan_password_rejects_remote_writes_and_media(self):
        empty = {"username": "", "password": ""}
        with patch.object(app, "lan_access_config", return_value=empty):
            login = self.client.post(
                "/api/auth/login",
                json={"username": "现场同事"},
                environ_base=LAN,
            )
            self.assertEqual(login.status_code, 403, login.get_json())

            write = self.client.post(
                "/api/projects",
                json={"project_code": "SHOULD-NOT-CREATE", "project_name": "不应写入"},
                environ_base=LAN,
            )
            self.assertEqual(write.status_code, 403)
            self.assertIn("访问口令", write.get_json()["error"])

            with self.client.session_transaction() as session:
                session["username"] = "现场同事"
            media = self.client.get("/photos/SEC-UNIT/sample.jpg", environ_base=LAN)
            self.assertEqual(media.status_code, 401)
            self.assertIn("访问口令", media.get_json()["error"])
            thumb = self.client.get("/thumbs/SEC-UNIT/sample.jpg", environ_base=LAN)
            self.assertEqual(thumb.status_code, 401)
            original = self.client.get("/originals/SEC-UNIT/photo-1", environ_base=LAN)
            self.assertEqual(original.status_code, 401)

    def test_loopback_stays_usable_and_configured_password_keeps_remote_login(self):
        with patch.object(app, "lan_access_config", return_value={"username": "", "password": ""}):
            local_login = self.client.post(
                "/api/auth/login",
                json={"username": "本机管理员", "remember": False},
                environ_base=LOOPBACK,
            )
            self.assertEqual(local_login.status_code, 200, local_login.get_json())
            local_write = self.client.post("/api/projects", json={}, environ_base=LOOPBACK)
            self.assertEqual(local_write.status_code, 400)

        with patch.object(
            app, "lan_access_config", return_value={"username": "", "password": "lan-door-9182"}
        ):
            missing = self.client.post(
                "/api/auth/login",
                json={"username": "现场同事"},
                environ_base=LAN,
            )
            self.assertEqual(missing.status_code, 401)
            allowed = self.client.post(
                "/api/auth/login",
                json={"username": "现场同事", "password": "lan-door-9182"},
                environ_base=LAN,
            )
            self.assertEqual(allowed.status_code, 200, allowed.get_json())
            media = self.client.get("/photos/SEC-UNIT/missing.jpg", environ_base=LAN)
            self.assertEqual(media.status_code, 404)

    def test_delete_password_blacklist_matches_fingerprint(self):
        fingerprint = app.LEGACY_DELETE_SAFETY_PASSWORD_SHA256
        self.assertRegex(fingerprint, r"^[0-9a-f]{64}$")
        source = Path(app.__file__).read_text(encoding="utf-8")
        self.assertNotRegex(source, r'LEGACY_DELETE_SAFETY_PASSWORD\s*=\s*["\']')
        self.assertIn(fingerprint, source)

        sample = "Sample9182"
        digest = hashlib.sha256(sample.encode("utf-8")).hexdigest()
        with patch.object(app, "LEGACY_DELETE_SAFETY_PASSWORD_SHA256", digest):
            self.assertTrue(app.is_legacy_blocked_delete_password(sample))
            self.assertFalse(app.is_legacy_blocked_delete_password("Other9182"))
            with self.assertRaises(ValueError):
                app.validate_engineering_delete_password(sample)
            self.assertEqual(app.validate_engineering_delete_password("Other9182"), "Other9182")

            with tempfile.TemporaryDirectory() as temp_dir:
                blocked_path = Path(temp_dir) / "blocked.json"
                blocked_path.write_text(
                    json.dumps(
                        {
                            "active_id": "p1",
                            "projects": [
                                {
                                    "id": "p1",
                                    "project_name": "指纹工程",
                                    "delete_password": sample,
                                }
                            ],
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                with patch.object(app, "ENGINEERING_PROJECTS_PATH", blocked_path):
                    blocked = app.read_engineering_projects()
                self.assertEqual(blocked["projects"][0].get("delete_password_hash"), "")
                blocked_saved = blocked_path.read_text(encoding="utf-8")
                self.assertNotIn(sample, blocked_saved)
                self.assertNotIn('"delete_password"', blocked_saved)

                allowed_path = Path(temp_dir) / "allowed.json"
                allowed_path.write_text(
                    json.dumps(
                        {
                            "active_id": "p2",
                            "projects": [
                                {
                                    "id": "p2",
                                    "project_name": "可迁移工程",
                                    "delete_password": "Other9182",
                                }
                            ],
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                with patch.object(app, "ENGINEERING_PROJECTS_PATH", allowed_path):
                    allowed_data = app.read_engineering_projects()
                stored_hash = allowed_data["projects"][0].get("delete_password_hash") or ""
                self.assertTrue(stored_hash)
                self.assertNotIn("Other9182", allowed_path.read_text(encoding="utf-8"))
                self.assertTrue(app.check_password_hash(stored_hash, "Other9182"))

    def test_public_samples_drop_live_host_and_local_paths(self):
        deployer = (ROOT / "deploy_auth.py").read_text(encoding="utf-8")
        self.assertIn("ALBUM_SERVER_HOST", deployer)
        self.assertIn("root@YOUR_SERVER_IP", deployer)
        self.assertNotRegex(deployer, r"root@\d+\.\d+\.\d+\.\d+")

        example = json.loads((ROOT / "album_config.example.json").read_text(encoding="utf-8"))
        blob = json.dumps(example, ensure_ascii=False)
        self.assertNotRegex(blob, r"[A-Za-z]:\\")
        self.assertEqual(example["portable_data_dir"], "data")
        self.assertIn("album_config.json", (ROOT / ".gitignore").read_text(encoding="utf-8"))

        mailer = (ROOT / "server" / "mailer.py").read_text(encoding="utf-8")
        self.assertIn("you@example.com", mailer)
        self.assertNotIn("@qq.com", mailer)


if __name__ == "__main__":
    unittest.main()
