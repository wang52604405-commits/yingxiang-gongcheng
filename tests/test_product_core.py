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


class DesktopUpdateCommandTest(unittest.TestCase):
    def test_update_targets_the_running_install_directory(self):
        from desktop_launcher import build_update_command

        temp_root = Path(tempfile.gettempdir())
        installer = temp_root / "album update.exe"
        install_dir = temp_root / "工程影像 客户安装目录"
        command = build_update_command(installer, install_dir)

        self.assertEqual(command[0], str(installer.resolve()))
        # 引号由 subprocess 自动添加：参数内嵌引号会被 Inno 当成路径的一部分，
        # 导致“文件夹名称不能包含下列任何字符”更新失败（v2.62 修复后契约）。
        self.assertIn("/DIR=" + str(install_dir.resolve()), command)
        self.assertFalse(any('"/DIR=' in arg for arg in command), "参数内不应内嵌引号")
        self.assertIn("/CLOSEAPPLICATIONS", command)


class VersionAssetSafetyTest(unittest.TestCase):
    def test_version_bump_never_cleans_assets_before_both_sources_exist(self):
        import bump_version

        with tempfile.TemporaryDirectory(prefix="album-version-assets-") as temp_dir:
            assets = Path(temp_dir)
            old_js = assets / "app-A20260822-2.64.js"
            old_gz = assets / "app-A20260822-2.64.js.gz"
            old_js.write_text("console.log('v1')", encoding="utf-8")
            old_gz.write_bytes(b"old-gzip-sentinel")
            with patch.object(bump_version, "ASSETS", assets):
                with self.assertRaisesRegex(SystemExit, "css 前端资源候选"):
                    bump_version._sync_asset_fingerprint("A20260825-2.65")
            self.assertTrue(old_js.exists(), "缺少 CSS 时不得提前重命名 JS")
            self.assertEqual(old_gz.read_bytes(), b"old-gzip-sentinel")

            old_css = assets / "app-A20260822-2.64.css"
            old_css.write_text("body{color:#123}", encoding="utf-8")
            with patch.object(bump_version, "ASSETS", assets):
                bump_version._sync_asset_fingerprint("A20260825-2.65")
            new_js = assets / "app-A20260825-2.65.js"
            new_css = assets / "app-A20260825-2.65.css"
            self.assertTrue(new_js.exists())
            self.assertTrue(new_css.exists())
            import gzip
            self.assertEqual(gzip.decompress((assets / f"{new_js.name}.gz").read_bytes()), new_js.read_bytes())
            self.assertEqual(gzip.decompress((assets / f"{new_css.name}.gz").read_bytes()), new_css.read_bytes())


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

    def test_login_and_me_return_same_stable_account_id(self):
        response = self.post(
            "/api/login",
            {"username": "test_admin", "password": "TestAdmin2026Secure"},
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        payload = response.get_json()
        self.assertIsInstance(payload["account"]["id"], int)
        # 新字段只能做加法，旧桌面端依赖的账号字段必须原样保留。
        self.assertTrue(
            {"username", "display_name", "role"}.issubset(payload["account"])
        )
        me = self.client.get(
            "/api/me",
            headers={"Authorization": "Bearer " + payload["token"]},
        )
        self.assertEqual(me.status_code, 200, me.get_json())
        me_payload = me.get_json()
        self.assertEqual(me_payload["account"]["id"], payload["account"]["id"])
        self.assertTrue(
            {"username", "display_name", "role"}.issubset(me_payload["account"])
        )
        self.assertIn("license", me_payload)

        # 同一账号重复登录时 subject 不随 token 或会话变化。
        second = self.post(
            "/api/login",
            {"username": "test_admin", "password": "TestAdmin2026Secure"},
        ).get_json()
        self.assertEqual(second["account"]["id"], payload["account"]["id"])

        # 模拟服务重启后重新建 Flask app，数据库里的稳定 ID 仍保持不变。
        from server.app import create_app

        restarted = create_app().test_client().post(
            "/api/login",
            json={"username": "test_admin", "password": "TestAdmin2026Secure"},
        )
        self.assertEqual(restarted.status_code, 200, restarted.get_json())
        self.assertEqual(
            restarted.get_json()["account"]["id"], payload["account"]["id"]
        )

    def test_product_config_invite_qualification_and_telemetry(self):
        product = self.client.get("/api/product-config").get_json()["product"]
        self.assertEqual(product["free"]["photo_limit"], 300)
        self.assertFalse(product["free"]["upload_expiry_enabled"])
        self.assertFalse(product["free"]["watermark_enabled"])
        self.assertEqual(product["pricing"]["price_label"], "原价")
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
        self.assertLessEqual(len(raw_thumb), 99 * 1024)
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

        delegated_fields = {**fields, "title": "共享模块题名"}
        with patch.object(
            self.desktop.watermark_ocr._shared,
            "extract_fields",
            return_value=delegated_fields,
        ) as delegated_extract:
            self.assertIs(
                self.desktop.watermark_ocr.extract_fields(["测试水印"]),
                delegated_fields,
            )
            delegated_extract.assert_called_once_with(["测试水印"])

        with patch.object(
            self.desktop.mobile_recognition,
            "normalize_match_text",
            return_value="shared-normalized",
        ) as delegated_normalize:
            self.assertEqual(self.desktop.normalize_match_text("原始文本"), "shared-normalized")
            delegated_normalize.assert_called_once_with("原始文本")
        with patch.object(
            self.desktop.mobile_recognition,
            "match_signal_score",
            return_value=777,
        ) as delegated_score:
            self.assertEqual(
                self.desktop._match_signal_score("信号", "候选", "area", "unit"),
                777,
            )
            delegated_score.assert_called_once_with("信号", "候选", "area", "unit")

        shared_match = {
            "project_code": "YNLQ-SHARED",
            "project_name": "共享匹配单元",
            "confidence": "high",
            "confidence_label": "高",
            "ambiguous": False,
            "score": 980,
            "reasons": ["施工区域匹配单元“共享匹配单元”"],
            "alternatives": [{
                "unit_code": "YNLQ-SHARED",
                "project_code": "YNLQ-SHARED",
                "display_project_code": "YNLQ-SHARED",
                "project_name": "共享匹配单元",
                "unit_name": "共享单位工程",
                "part_name": "共享分部工程",
                "score": 980,
                "reasons": ["共享规则"],
            }],
            "candidates": ["不应泄露到旧返回契约"],
        }
        with patch.object(
            self.desktop.mobile_recognition,
            "match_photo",
            return_value=shared_match,
        ) as delegated_match, patch.object(
            self.desktop.manager,
            "list_projects",
            return_value=[{"project_code": "YNLQ-SHARED"}],
        ):
            compatible = self.desktop.match_photo_to_projects("现场.jpg", "现场/现场.jpg", {})
        delegated_match.assert_called_once()
        self.assertEqual(compatible["project_code"], "YNLQ-SHARED")
        self.assertEqual(set(compatible), {
            "project_code", "project_name", "confidence", "confidence_label",
            "ambiguous", "score", "reasons", "alternatives",
        })
        self.assertNotIn("unit_code", compatible["alternatives"][0])

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
        self.assertIn("复制施工照片", html)
        self.assertIn("4寸（10.2×7.6cm）", html)
        self.assertIn("审核批量导入结果", html)
        self.assertIn("默认打印", html)
        self.assertIn("每页照片数量", html)
        self.assertIn("文字标签位置", html)
        self.assertIn("printSetupMarginTop", html)

    def test_default_print_is_four_5inch_photos_and_upload_is_optimized(self):
        import hashlib
        import uuid

        from PIL import Image
        from werkzeug.datastructures import FileStorage

        photos = [
            {"id": f"SY-{index}", "detail_rows": [{"label": "题名", "value": f"照片{index}"}]}
            for index in range(1, 5)
        ]
        settings = {
            "print_margin_top_mm": 4,
            "print_margin_right_mm": 4,
            "print_margin_bottom_mm": 4,
            "print_margin_left_mm": 4,
            "print_horizontal_gap_mm": 2,
            "print_vertical_gap_mm": 2,
            "print_caption_position": "bottom",
            "print_caption_size_mm": 7,
            "print_show_page_title": True,
        }
        pages = self.desktop.layout_fixed_photo_pages(
            photos,
            layout="landscape",
            page_size=4,
            photo_width_mm=127,
            photo_height_mm=89,
            print_settings=settings,
        )
        self.assertEqual(len(pages), 1)
        self.assertEqual(len(pages[0]), 4)
        self.assertTrue(all(item["_caption_position"] == "bottom" for item in pages[0]))

        source = io.BytesIO()
        Image.effect_noise((4200, 2800), 48).convert("RGB").save(source, "JPEG", quality=100)
        source_bytes = source.getvalue()
        source.seek(0)
        target = self.desktop.manager._photos_dir("OPT-CHECK") / "optimized-upload.jpg"
        result = self.desktop.manager._save_optimized_upload(
            FileStorage(stream=source, filename="现场原图.jpg"), target
        )
        self.assertTrue(result["optimized"])
        self.assertLess(target.stat().st_size, len(source_bytes))
        self.assertLessEqual(target.stat().st_size, 300 * 1024)
        backup = self.desktop.manager._original_path("OPT-CHECK", result["original_backup"])
        self.assertTrue(backup.exists())
        self.assertEqual(backup.stat().st_size, len(source_bytes))
        self.assertTrue(self.desktop.manager._ensure_thumbnail("OPT-CHECK", target.name))
        self.assertTrue((target.parent / self.desktop.manager._thumb_filename(target.name)).exists())
        with Image.open(target) as optimized:
            self.assertLessEqual(max(optimized.size), 3200)

        # 手机上传改为服务器短期中转原图：即使文件明显大于 200KB，
        # 桌面端也必须原字节归档，后续优化入口不得再次编码。
        mobile_project = self.desktop.manager.create_project(
            "MOBILE-ORIGINAL-CHECK",
            "手机原图验收单元",
            source_fields={"单元工程编码": "MOBILE-ORIGINAL-CHECK"},
        )
        mobile_source = io.BytesIO()
        Image.effect_noise((1800, 1200), 72).convert("RGB").save(
            mobile_source, "JPEG", quality=98
        )
        mobile_raw = mobile_source.getvalue()
        self.assertGreater(len(mobile_raw), 200 * 1024)
        mobile_uuid = str(uuid.uuid4())
        mobile_name = f"mobile-{mobile_uuid}.jpg"
        added = self.desktop.manager.add_photos(
            mobile_project["project_code"],
            [FileStorage(stream=io.BytesIO(mobile_raw), filename=mobile_name)],
            category="construction",
            per_file_meta={mobile_name: {
                "photo_uuid": mobile_uuid,
                "preserve_mobile_original": True,
                "mobile_original_received": True,
                "source_original_name": "IMG_20260825_090000.jpg",
                "sha256": hashlib.sha256(mobile_raw).hexdigest(),
                "pixel_width": 1800,
                "pixel_height": 1200,
            }},
        )
        saved = self.desktop.manager.get_project(mobile_project["project_code"])["photos"][0]
        mobile_target = (
            self.desktop.manager._photos_dir(mobile_project["project_code"])
            / saved["filename"]
        )
        self.assertEqual(mobile_target.read_bytes(), mobile_raw)
        self.assertFalse(saved["optimized"])
        self.assertTrue(saved["mobile_original_received"])
        self.desktop.manager.optimize_existing_photo(
            mobile_project["project_code"], added[0]["id"]
        )
        self.assertEqual(mobile_target.read_bytes(), mobile_raw)
        self.assertEqual(
            hashlib.sha256(mobile_target.read_bytes()).hexdigest(),
            hashlib.sha256(mobile_raw).hexdigest(),
        )
        mobile_target.write_bytes(b"tampered-local-original")
        repaired = self.desktop.manager.repair_mobile_original(
            mobile_project["project_code"],
            mobile_uuid,
            mobile_raw,
            {
                "sha256": hashlib.sha256(mobile_raw).hexdigest(),
                "size_bytes": len(mobile_raw),
                "mime_type": "image/jpeg",
                "extension": ".jpg",
                "width": 1800,
                "height": 1200,
            },
            "IMG_20260825_090000.jpg",
        )
        self.assertEqual(mobile_target.read_bytes(), mobile_raw)
        self.assertEqual(repaired["sha256"], hashlib.sha256(mobile_raw).hexdigest())
        repair_backup = (
            self.desktop.manager._project_dir(mobile_project["project_code"])
            / "_mobile_sync_backups"
            / repaired["mobile_repair_backup"]
        )
        self.assertEqual(repair_backup.read_bytes(), b"tampered-local-original")

        png_project = self.desktop.manager.create_project(
            "MOBILE-PNG-CHECK",
            "手机 PNG 原图验收单元",
            source_fields={"单元工程编码": "MOBILE-PNG-CHECK"},
        )
        png_source = io.BytesIO()
        Image.effect_noise((900, 700), 68).convert("RGB").save(png_source, "PNG")
        png_raw = png_source.getvalue()
        png_uuid = str(uuid.uuid4())
        png_name = f"mobile-{png_uuid}.png"
        self.desktop.manager.add_photos(
            png_project["project_code"],
            [FileStorage(stream=io.BytesIO(png_raw), filename=png_name)],
            per_file_meta={png_name: {
                "photo_uuid": png_uuid,
                "preserve_mobile_original": True,
                "mobile_original_received": True,
                "sha256": hashlib.sha256(png_raw).hexdigest(),
                "pixel_width": 900,
                "pixel_height": 700,
            }},
        )
        png_saved = self.desktop.manager.get_project(png_project["project_code"])["photos"][0]
        png_target = self.desktop.manager._photos_dir(png_project["project_code"]) / png_saved["filename"]
        self.assertEqual(png_target.read_bytes(), png_raw)
        self.assertEqual(
            hashlib.sha256(png_target.read_bytes()).hexdigest(),
            hashlib.sha256(png_raw).hexdigest(),
        )

        failure_project = self.desktop.manager.create_project(
            "MOBILE-WRITE-FAIL-CHECK",
            "手机原图失败清理单元",
            source_fields={"单元工程编码": "MOBILE-WRITE-FAIL-CHECK"},
        )
        failure_name = f"mobile-{uuid.uuid4()}.jpg"
        with patch.object(
            self.desktop.manager, "_write_metadata", side_effect=OSError("metadata full")
        ):
            with self.assertRaises(OSError):
                self.desktop.manager.add_photos(
                    failure_project["project_code"],
                    [FileStorage(stream=io.BytesIO(mobile_raw), filename=failure_name)],
                    per_file_meta={failure_name: {
                        "photo_uuid": str(uuid.uuid4()),
                        "preserve_mobile_original": True,
                        "mobile_original_received": True,
                    }},
                )
        failure_dir = self.desktop.manager._photos_dir(failure_project["project_code"])
        self.assertFalse(list(failure_dir.glob("*.mobile.tmp")))
        self.assertFalse([
            path for path in failure_dir.iterdir()
            if path.suffix.lower() in {".jpg", ".jpeg", ".png"}
        ])

        replace_target = failure_dir / "replace-failure.jpg"
        with patch.object(self.desktop.os, "replace", side_effect=OSError("replace blocked")):
            with self.assertRaises(OSError):
                self.desktop.manager._save_exact_mobile_original(
                    FileStorage(stream=io.BytesIO(mobile_raw), filename="replace-failure.jpg"),
                    replace_target,
                )
        self.assertFalse(replace_target.exists())
        self.assertFalse(replace_target.with_suffix(".jpg.mobile.tmp").exists())

    def test_bootstrap_is_compact_paginated_and_assets_are_cached(self):
        with self.client.session_transaction() as session:
            session["username"] = "性能验收用户"
        for index in range(1, 26):
            self.desktop.manager.create_project(
                f"PERF-{index:03d}",
                f"性能单元{index:03d}",
                source_fields={
                    "合同工程名称": "性能测试合同",
                    "单位工程名称": "性能测试单位工程",
                    "单位工程编码": "PERF-U",
                    "分部工程名称": "性能测试分部",
                    "分部工程编码": "PERF-P",
                    "单元工程名称": f"性能单元{index:03d}",
                    "单元工程编码": f"PERF-{index:03d}",
                },
                project_order=index,
            )
        response = self.client.get("/api/bootstrap")
        self.assertEqual(response.status_code, 200)
        self.assertLess(len(response.data), 150 * 1024)
        data = response.get_json()
        parts = [
            part
            for contract in data["hierarchy"]
            for unit in contract["units"]
            for part in unit["parts"]
            if part["name"] == "性能测试分部"
        ]
        self.assertEqual(len(parts), 1)
        units = self.client.get(
            f"/api/units?part_key={parts[0]['part_key']}&page=1&page_size=20"
        ).get_json()
        self.assertEqual(units["total"], 25)
        self.assertEqual(len(units["projects"]), 20)
        self.assertEqual(units["pages"], 2)

        index_response = self.client.get("/", headers={"Accept-Encoding": "gzip"})
        self.assertEqual(index_response.headers.get("Content-Encoding"), "gzip")
        # 从 index.html 提取版本化 asset 文件名，避免 bump 版本后硬编码失效
        import gzip as _gzip
        import re as _re
        index_html = _gzip.decompress(index_response.data).decode("utf-8")
        asset_match = _re.search(r"/assets/(app-A\d{8}-\d+\.\d+\.js)", index_html)
        self.assertIsNotNone(asset_match, "index.html 中未找到版本化 JS asset")
        asset_name = asset_match.group(1)
        asset_response = self.client.get(
            f"/assets/{asset_name}", headers={"Accept-Encoding": "gzip"}
        )
        self.assertEqual(asset_response.headers.get("Content-Encoding"), "gzip")
        self.assertIn("immutable", asset_response.headers.get("Cache-Control", ""))
        asset_body = _gzip.decompress(asset_response.data)
        self.assertEqual(
            asset_body,
            (self.desktop.BASE_DIR / "assets" / asset_name).read_bytes(),
            "预压缩 JS 必须与当前源码完全一致，不能把旧界面缓存一年",
        )
        asset_text = asset_body.decode("utf-8")
        self.assertIn("/api/cloud/project-ownership", asset_text)
        self.assertIn("/api/cloud/wechat-binding", asset_text)
        self.assertIn("已阻止串号", asset_text)
        asset_response.close()
        index_response.close()

    def test_z_cloud_project_ownership_is_backed_up_and_cannot_cross_accounts(self):
        project = self.desktop.default_engineering_project()
        project.update({
            "id": "ownership-test",
            "project_code": "OWN-001",
            "project_name": "账号归属测试工程",
            "delete_password_hash": self.desktop.generate_password_hash("OwnSafe2026"),
            "cloud_owner_id": "",
            "cloud_owner_username": "",
            "cloud_owner_claimed_at": "",
        })
        self.desktop.write_engineering_projects({
            "active_id": project["id"],
            "projects": [project],
        })

        with patch.object(
            self.desktop.cloud_client, "desktop_sync_account_id", return_value="account-A"
        ), patch.object(
            self.desktop.cloud_client,
            "desktop_sync_account_username",
            return_value="tenant_a",
        ):
            claimed = self.desktop.claim_current_project_cloud_ownership()
            self.assertEqual(claimed["state"], "matched")
            backup_dir = Path(claimed["backup_dir"])
            self.assertTrue((backup_dir / self.desktop.ENGINEERING_PROJECTS_PATH.name).exists())
            self.assertTrue((backup_dir / self.desktop.PROJECT_INFO_PATH.name).exists())

            with self.client.session_transaction() as session:
                session["username"] = "tenant_a"
            saved = self.client.post(
                "/api/project-info",
                json={
                    "id": "ownership-test",
                    "project_code": "OWN-001",
                    "project_name": "账号归属测试工程（编辑后）",
                },
            )
            self.assertEqual(saved.status_code, 200, saved.get_json())
            preserved = self.desktop.current_engineering_project()
            self.assertEqual(preserved["cloud_owner_id"], "account-A")
            self.assertEqual(preserved["cloud_owner_username"], "tenant_a")

        with patch.object(
            self.desktop.cloud_client, "desktop_sync_account_id", return_value="account-B"
        ), patch.object(
            self.desktop.cloud_client,
            "desktop_sync_account_username",
            return_value="tenant_b",
        ):
            status = self.desktop.current_project_cloud_ownership()
            self.assertEqual(status["state"], "mismatch")
            self.assertFalse(status["sync_allowed"])
            with self.assertRaisesRegex(ValueError, "不能直接改绑"):
                self.desktop.claim_current_project_cloud_ownership()


if __name__ == "__main__":
    unittest.main()
