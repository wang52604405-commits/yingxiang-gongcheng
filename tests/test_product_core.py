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
        self.assertEqual(fields["construction_content"], "左岸连接堤")
        self.assertEqual(fields["construction_area"], "")
        self.assertEqual(fields["project_name"], "洺河龙泉缓洪工程")
        self.assertEqual(fields["photo_date"], "2026-06-05")
        self.assertEqual(self.desktop.watermark_text_for_user(), "")

    def test_multi_rule_match_process_disabled_and_print_presets(self):
        from PIL import Image
        from werkzeug.datastructures import FileStorage

        project = self.desktop.manager.create_project(
            "YNLQ-001-01-001",
            "左岸连接堤",
            source_fields={
                "合同工程名称": "洺河龙泉缓洪工程",
                "单位工程名称": "龙泉河单位工程",
                "分部工程名称": "左岸连接工程",
                "单元工程名称": "左岸连接堤",
                "单元工程编码": "YNLQ-001-01-001",
                "划分类型": "划分工序单元",
                "工序名称列表": "普通混凝土备仓、普通混凝土浇筑",
            },
        )
        self.assertEqual(project["division_type"], "unit")
        self.assertEqual(project["processes"], [])
        self.assertEqual(project["source_fields"]["工序名称列表"], "")

        result = self.desktop.match_photo_to_projects(
            "IMG_20260605.jpg",
            "批量照片/左岸连接堤/IMG_20260605.jpg",
            {
                "construction_area": "左岸连接堤",
                "construction_content": "混凝土浇筑完成",
                "project_name": "洺河龙泉缓洪工程",
            },
        )
        self.assertEqual(result["project_code"], project["project_code"])
        self.assertEqual(result["confidence"], "high")
        self.assertTrue(any("施工区域匹配单元" in reason for reason in result["reasons"]))

        image_bytes = io.BytesIO()
        Image.new("RGB", (640, 480), (100, 120, 140)).save(image_bytes, "JPEG")
        image_bytes.seek(0)
        self.desktop.manager.add_photos(
            project["project_code"],
            [FileStorage(stream=image_bytes, filename="施工照片.jpg")],
            category="construction",
            title="基槽验收",
            photo_date="2026-08-09",
        )
        copied = self.desktop.manager.copy_construction_to_supervision(project["project_code"])
        self.assertEqual(len(copied), 1)
        photos = self.desktop.manager.get_project(project["project_code"])["photos"]
        self.assertEqual(sum(photo["category"] == "construction" for photo in photos), 1)
        self.assertEqual(sum(photo["category"] == "supervision" for photo in photos), 1)

        with self.desktop.app.test_request_context("/?photo_preset=6inch"):
            settings = self.desktop.print_settings_from_request()
        self.assertEqual(settings["print_photo_preset"], "6inch")
        self.assertEqual(settings["print_photo_width_cm"], 15.2)
        self.assertEqual(settings["print_photo_height_cm"], 10.2)

    def test_remember_login_and_required_product_controls_are_visible(self):
        response = self.client.post(
            "/api/auth/login",
            json={"username": "长期登录测试员", "remember": True},
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        with self.client.session_transaction() as session:
            self.assertTrue(session.permanent)
            self.assertEqual(session.get("username"), "长期登录测试员")

        html = self.client.get("/").get_data(as_text=True)
        self.assertIn("记住登录（30 天内免重复登录）", html)
        self.assertIn("复制施工照片", html)
        self.assertIn("4寸（10.2×7.6cm）", html)
        self.assertIn("审核批量导入结果", html)


if __name__ == "__main__":
    unittest.main()
