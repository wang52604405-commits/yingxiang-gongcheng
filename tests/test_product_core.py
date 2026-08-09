# -*- coding: utf-8 -*-
"""工程影像平台关键产品契约回归测试（标准库 unittest 可直接运行）。"""

from __future__ import annotations

import base64
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class ServerProductContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="album-server-test-")
        os.environ["ALBUM_SERVER_DATA"] = cls.temp.name
        os.environ["ALBUM_SERVER_DB"] = str(Path(cls.temp.name) / "server.db")
        os.environ["ALBUM_ADMIN_USER"] = "test_admin"
        os.environ["ALBUM_ADMIN_PASS"] = "TestAdmin2026Secure"
        from server.app import create_app

        cls.app = create_app()
        cls.client = cls.app.test_client()

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def post(self, path, data, token=""):
        headers = {"Authorization": "Bearer " + token} if token else {}
        return self.client.post(path, json=data, headers=headers)

    def login(self, username, password):
        response = self.post("/api/login", {"username": username, "password": password})
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()["token"]

    def test_product_config_invite_qualification_and_telemetry(self):
        product = self.client.get("/api/product-config").get_json()["product"]
        self.assertEqual(product["free"]["photo_limit"], 300)
        self.assertFalse(product["free"]["upload_expiry_enabled"])
        self.assertFalse(product["free"]["watermark_enabled"])
        self.assertEqual(product["pricing"]["price_label"], "内测会员价")
        self.assertEqual(product["logging"]["retention_days"], 90)
        self.assertEqual(product["logging"]["max_records"], 5000)

        weak = self.post("/api/register", {"username": "weak", "password": "123456"})
        self.assertEqual(weak.status_code, 400)
        inviter = self.post(
            "/api/register",
            {"username": "inviter", "password": "Invite1234", "email": "a@example.com"},
        ).get_json()
        invite_code = inviter["account"]["invite_code"]
        inviter_token = self.login("inviter", "Invite1234")

        self.post(
            "/api/register",
            {"username": "invitee1", "password": "Invitee1234", "invite_code": invite_code},
        )
        first_token = self.login("invitee1", "Invitee1234")
        self.post("/api/activate", {"machine_id": "TEST-MACHINE-001"}, first_token)

        self.post(
            "/api/register",
            {"username": "invitee2", "password": "Invitee2234", "invite_code": invite_code},
        )
        second_token = self.login("invitee2", "Invitee2234")
        self.post("/api/activate", {"machine_id": "TEST-MACHINE-001"}, second_token)

        status = self.client.get(
            "/api/invite-status", headers={"Authorization": "Bearer " + inviter_token}
        ).get_json()
        self.assertEqual(status["registered_count"], 2)
        self.assertEqual(status["qualified_count"], 1)

        self.post(
            "/api/client-errors",
            {
                "source": "unittest",
                "message": "password=DoNotStore failed",
                "context": {
                    "token": "secret-token",
                    "photo_b64": "data:image/png;base64,AAAA",
                },
            },
        )
        admin_token = self.login("test_admin", "TestAdmin2026Secure")
        before_404 = self.client.get(
            "/api/admin/errors?resolved=0",
            headers={"Authorization": "Bearer " + admin_token},
        ).get_json()["summary"]["unresolved"]
        self.assertEqual(self.client.get("/definitely-not-a-real-route").status_code, 404)
        errors = self.client.get(
            "/api/admin/errors?resolved=0",
            headers={"Authorization": "Bearer " + admin_token},
        ).get_json()
        self.assertEqual(errors["summary"]["unresolved"], before_404)
        serialized = json.dumps(errors, ensure_ascii=False)
        self.assertNotIn("DoNotStore", serialized)
        self.assertNotIn("secret-token", serialized)
        self.assertNotIn("data:image", serialized)

        changed = self.post(
            "/api/admin/product-config",
            {"product": {"cloud_preview": {"thumb_max_side": 760}}},
            admin_token,
        ).get_json()["product"]
        self.assertEqual(changed["cloud_preview"]["thumb_max_side"], 760)
        self.assertEqual(changed["config_version"], 2)

        self.post(
            "/api/admin/version",
            {
                "version": "A20260809-9.99",
                "download_url": "https://example.invalid/update.exe",
                "sha256": "a" * 64,
                "size": 123456,
            },
            admin_token,
        )
        update = self.client.get("/api/check-update?current=A20260809-2.26").get_json()
        self.assertTrue(update["has_update"])
        self.assertEqual(update["sha256"], "a" * 64)
        self.assertEqual(update["size"], 123456)


class DesktopSecurityContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="album-desktop-test-")
        os.environ["ALBUM_DATA_DIR"] = cls.temp.name
        os.environ["ALBUM_TRIAL_FILE"] = str(Path(cls.temp.name) / "trial.json")
        os.environ["ALBUM_LICENSE_FILE"] = str(Path(cls.temp.name) / "license.dat")
        import app as desktop_app

        cls.desktop = desktop_app
        cls.client = desktop_app.app.test_client()

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_delete_password_is_hashed_and_cloud_thumb_is_recognizable(self):
        from PIL import Image

        with self.client.session_transaction() as session:
            session["username"] = "测试员"
        with patch.object(self.desktop.cloud_client, "report_error", return_value={"ok": True}):
            public = self.client.get("/api/project-info").get_json()
            self.assertFalse(public["project_info"]["delete_password_set"])
            self.assertNotIn("delete_password_hash", json.dumps(public))

            base = {"project_name": "测试工程", "project_code": "TEST-001"}
            self.assertEqual(self.client.post("/api/project-info", json=base).status_code, 400)
            self.assertEqual(
                self.client.post(
                    "/api/project-info", json={**base, "delete_password": "114405"}
                ).status_code,
                400,
            )
            password = "Delete7286"
            saved = self.client.post(
                "/api/project-info", json={**base, "delete_password": password}
            )
            self.assertEqual(saved.status_code, 200, saved.get_json())
            raw = Path(self.desktop.ENGINEERING_PROJECTS_PATH).read_text(encoding="utf-8")
            self.assertNotIn(password, raw)
            self.assertIn("delete_password_hash", raw)

        photos = self.desktop.manager._photos_dir("TEST-THUMB")
        photos.mkdir(parents=True, exist_ok=True)
        original = photos / "sample.jpg"
        Image.new("RGB", (2000, 1200), (42, 110, 160)).save(original, "JPEG", quality=92)
        with patch.object(self.desktop.cloud_client, "report_error", return_value={"ok": True}):
            raw_thumb = self.desktop._cloud_thumbnail_bytes(
                "TEST-THUMB",
                "sample.jpg",
                {"thumb_max_side": 720, "thumb_quality": 76, "max_thumb_b64": 600000},
            )
        self.assertLess(len(base64.b64encode(raw_thumb)), 600000)
        with Image.open(io.BytesIO(raw_thumb)) as image:
            self.assertEqual(max(image.size), 720)

    def test_ocr_prefers_construction_content_and_free_export_has_no_watermark(self):
        lines = [
            "洺河龙泉缓洪工程",
            "施工区域：请输入内容…",
            "施 工 内 容：左岸连接堤",
            "拍摄时间：2026.06.05 15:34",
        ]
        fields = self.desktop.watermark_ocr.extract_fields(lines)
        self.assertEqual(fields["title"], "左岸连接堤")
        self.assertEqual(fields["photo_date"], "2026-06-05")
        self.assertEqual(self.desktop.watermark_text_for_user(), "")


if __name__ == "__main__":
    unittest.main()
