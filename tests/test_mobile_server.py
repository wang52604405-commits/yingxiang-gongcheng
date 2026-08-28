# -*- coding: utf-8 -*-
"""移动端/桌面同步服务器契约测试（标准库 unittest 可运行）。"""

from __future__ import annotations

import hashlib
import io
import os
import ast
import sys
import tempfile
import threading
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from PIL import Image


class MobileServerContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="album-mobile-server-")
        cls.env_names = [
            "ALBUM_SERVER_DATA",
            "ALBUM_SERVER_DB",
            "ALBUM_SERVER_SECRET",
            "ALBUM_ADMIN_USER",
            "ALBUM_ADMIN_PASS",
            "ALBUM_MOBILE_STORAGE_BACKEND",
            "ALBUM_MOBILE_STORAGE_DIR",
            "ALBUM_WECHAT_MOCK_ENABLED",
        ]
        cls.old_env = {name: os.environ.get(name) for name in cls.env_names}
        os.environ.update(
            {
                "ALBUM_SERVER_DATA": cls.temp.name,
                "ALBUM_SERVER_DB": str(Path(cls.temp.name) / "server.db"),
                "ALBUM_SERVER_SECRET": "mobile-test-secret-2026-strong",
                "ALBUM_ADMIN_USER": "",
                "ALBUM_ADMIN_PASS": "",
                "ALBUM_MOBILE_STORAGE_BACKEND": "local",
                "ALBUM_MOBILE_STORAGE_DIR": str(Path(cls.temp.name) / "objects"),
                "ALBUM_WECHAT_MOCK_ENABLED": "1",
            }
        )
        from server import config, db
        from server import app as server_app

        cls.old_config = {
            "DATA_DIR": config.DATA_DIR,
            "DB_PATH": config.DB_PATH,
            "MOBILE_STORAGE_BACKEND": config.MOBILE_STORAGE_BACKEND,
            "MOBILE_STORAGE_DIR": config.MOBILE_STORAGE_DIR,
            "WECHAT_MOCK_ENABLED": config.WECHAT_MOCK_ENABLED,
            "ADMIN_USERNAME": config.ADMIN_USERNAME,
            "ADMIN_PASSWORD": config.ADMIN_PASSWORD,
        }
        config.DATA_DIR = Path(cls.temp.name)
        config.DB_PATH = Path(cls.temp.name) / "server.db"
        config.MOBILE_STORAGE_BACKEND = "local"
        config.MOBILE_STORAGE_DIR = Path(cls.temp.name) / "objects"
        config.WECHAT_MOCK_ENABLED = True
        config.ADMIN_USERNAME = ""
        config.ADMIN_PASSWORD = ""
        server_app._rate_hits.clear()

        cls.db = db
        cls.app = server_app.create_app()
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()
        cls._register("tenant_a", "TenantA2026")
        cls._register("tenant_b", "TenantB2026")
        cls.token_a = cls._login("tenant_a", "TenantA2026")
        cls.token_b = cls._login("tenant_b", "TenantB2026")
        conn = cls.db.connect()
        try:
            account_a = conn.execute(
                "SELECT id FROM accounts WHERE username = 'tenant_a'"
            ).fetchone()["id"]
            account_b = conn.execute(
                "SELECT id FROM accounts WHERE username = 'tenant_b'"
            ).fetchone()["id"]
            conn.executemany(
                "INSERT INTO machines (account_id, machine_id, active) VALUES (?, ?, 1)",
                (
                    (account_a, "MACHINE-A"),
                    (account_a, "MACHINE-A-ALT"),
                    (account_b, "MACHINE-B"),
                ),
            )
            conn.commit()
        finally:
            conn.close()
        cls.desktop_token_a = cls._activate(cls.token_a, "MACHINE-A")
        cls.desktop_token_a_alt = cls._activate(cls.token_a, "MACHINE-A-ALT")
        cls.desktop_token_b = cls._activate(cls.token_b, "MACHINE-B")
        cls._snapshot(cls.desktop_token_a, "甲账号工程")
        cls._snapshot(
            cls.desktop_token_b,
            "乙账号工程",
            desktop_machine_id="MACHINE-B",
        )

    @classmethod
    def tearDownClass(cls):
        try:
            from server import config

            for name, value in cls.old_config.items():
                setattr(config, name, value)
        except ImportError:
            pass
        cls.temp.cleanup()
        for name, value in cls.old_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        # 不污染同一测试进程中随后运行的旧服务器测试；它们会按自己的环境
        # 重新载入配置。
        for module_name in list(sys.modules):
            if module_name == "server" or module_name.startswith("server."):
                sys.modules.pop(module_name, None)

    @classmethod
    def _headers(cls, token):
        return {"Authorization": "Bearer " + token}

    @classmethod
    def _register(cls, username, password):
        response = cls.client.post(
            "/api/register", json={"username": username, "password": password}
        )
        if response.status_code != 200:
            raise AssertionError(response.get_json())

    @classmethod
    def _login(cls, username, password):
        response = cls.client.post(
            "/api/login", json={"username": username, "password": password}
        )
        if response.status_code != 200:
            raise AssertionError(response.get_json())
        return response.get_json()["token"]

    @classmethod
    def _activate(cls, token, machine_id):
        response = cls.client.post(
            "/api/activate",
            json={"machine_id": machine_id},
            headers=cls._headers(token),
        )
        if response.status_code != 200:
            raise AssertionError(response.get_json())
        return response.get_json()["desktop_sync_token"]

    @classmethod
    def _snapshot(
        cls,
        token,
        project_name,
        project_id="default",
        desktop_machine_id="MACHINE-A",
        revision=7,
        requirements=None,
    ):
        # 大多数测试传账号登录令牌以表示租户；新桌面契约
        # 实际上传必须换成与请求机器一致的 desktop_sync_token。
        if token == getattr(cls, "token_a", None):
            token = (
                cls.desktop_token_a_alt
                if desktop_machine_id == "MACHINE-A-ALT"
                else cls.desktop_token_a
            )
        elif token == getattr(cls, "token_b", None):
            token = cls.desktop_token_b
        payload = {
            "snapshot_id": str(uuid.uuid4()),
            "revision": revision,
            "desktop_machine_id": desktop_machine_id,
            "project": {
                "id": project_id,
                "project_code": "YNLQ",
                "project_name": project_name,
            },
            "tree": [
                {
                    "code": "YNLQ-C",
                    "name": "洺河龙泉缓洪工程",
                    "unit_projects": [
                        {
                            "code": "YNLQ-U",
                            "name": "龙泉河单位工程",
                            "parts": [
                                {
                                    "code": "YNLQ-P",
                                    "name": "左岸连接工程",
                                    "units": [
                                        {
                                            "unit_code": "YNLQ-001-01-001",
                                            "internal_project_code": "LOCAL-001",
                                            "name": "左岸连接堤",
                                            "division_type": "unit",
                                            "processes": ["土方填筑"],
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ],
            "other_tree": [
                {
                    "node_code": "OTHER-ROOT",
                    "name": "其它影像",
                    "children": [{"node_code": "OTHER-SITE", "name": "现场记录"}],
                }
            ],
        }
        if requirements is not None:
            payload["requirements"] = requirements
            payload["requirement_summary"] = {
                "total": len(requirements),
                "required": sum(1 for item in requirements if item.get("required_type") == "required"),
                "conditional": sum(1 for item in requirements if item.get("required_type") == "conditional"),
                "recommended": sum(1 for item in requirements if item.get("required_type") == "recommended"),
            }
        response = cls.client.post(
            "/api/desktop/v1/project-snapshot",
            json=payload,
            headers=cls._headers(token),
        )
        if response.status_code != 200:
            raise AssertionError(response.get_json())

    @staticmethod
    def _jpeg(color=(34, 110, 154), size=(640, 480)):
        stream = io.BytesIO()
        Image.new("RGB", size, color).save(stream, "JPEG", quality=80)
        return stream.getvalue()

    @staticmethod
    def _png(color=(34, 110, 154, 180), size=(640, 480)):
        stream = io.BytesIO()
        Image.new("RGBA", size, color).save(stream, "PNG")
        return stream.getvalue()

    def _create_batch(
        self, token, mode="direct", scope="engineering", project_id="default"
    ):
        assignment = (
            {"unit_code": "YNLQ-001-01-001", "process_name": ""}
            if scope == "engineering"
            else {"other_node_code": "OTHER-SITE"}
        )
        response = self.client.post(
            "/api/mobile/v1/batches",
            json={
                "client_batch_id": str(uuid.uuid4()),
                "project_id": project_id,
                "scope": scope,
                "category": "construction" if scope == "engineering" else "",
                "mode": mode,
                "assignment": assignment if mode == "direct" else {},
            },
            headers=self._headers(token),
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()["batch"]["batch_id"]

    def _upload(
        self,
        token,
        batch_id,
        photo_uuid,
        content,
        sha=None,
        filename="现场.jpg",
        original_size_bytes=None,
        original_filename=None,
    ):
        return self.client.post(
            f"/api/mobile/v1/batches/{batch_id}/photos",
            data={
                "file": (io.BytesIO(content), filename),
                "photo_uuid": photo_uuid,
                "client_captured_at": "2026-08-25T01:02:03Z",
                "orientation": "1",
                "width": "640",
                "height": "480",
                "sha256": sha or hashlib.sha256(content).hexdigest(),
                "original_size_bytes": str(
                    len(content) if original_size_bytes is None else original_size_bytes
                ),
                "original_filename": (
                    filename if original_filename is None else original_filename
                ),
            },
            headers=self._headers(token),
            content_type="multipart/form-data",
        )

    def _analyze_and_wait(self, token, batch_id, attempts=200):
        accepted = self.client.post(
            f"/api/mobile/v1/batches/{batch_id}/analyze",
            headers=self._headers(token),
        )
        self.assertEqual(accepted.status_code, 202, accepted.get_json())
        job_id = accepted.get_json()["job"]["job_id"]
        latest = None
        for _ in range(attempts):
            latest = self.client.get(
                f"/api/mobile/v1/jobs/{job_id}",
                headers=self._headers(token),
            )
            self.assertEqual(latest.status_code, 200, latest.get_json())
            if latest.get_json()["job"]["status"] in {"completed", "failed"}:
                return accepted, latest
            time.sleep(0.01)
        self.fail(f"识别任务未在测试时限内完成: {latest.get_json() if latest else job_id}")

    def _chunk_init(
        self,
        token,
        batch_id,
        photo_uuid,
        content,
        *,
        chunk_size,
        sha=None,
        filename="分片原图.jpg",
    ):
        return self.client.post(
            f"/api/mobile/v1/batches/{batch_id}/chunked-uploads/init",
            json={
                "photo_uuid": photo_uuid,
                "sha256": sha or hashlib.sha256(content).hexdigest(),
                "original_size_bytes": len(content),
                "original_filename": filename,
                "chunk_size_bytes": chunk_size,
                "total_chunks": (len(content) + chunk_size - 1) // chunk_size,
                "client_captured_at": "2026-08-25T01:02:03Z",
                "orientation": 1,
                "width": 640,
                "height": 480,
                "title": "分片现场影像",
                "photo_date": "2026-08-25",
            },
            headers=self._headers(token),
        )

    def _put_chunk(self, token, batch_id, photo_uuid, index, content, sha=None):
        return self.client.put(
            f"/api/mobile/v1/batches/{batch_id}/chunked-uploads/"
            f"{photo_uuid}/chunks/{index}",
            data=content,
            content_type="application/octet-stream",
            headers={
                **self._headers(token),
                "X-Chunk-SHA256": sha or hashlib.sha256(content).hexdigest(),
            },
        )

    def test_instance_sentinel_is_public_non_sensitive_and_production_default(self):
        from server import config

        response = self.client.get("/api/instance")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(
            payload,
            {
                "ok": True,
                "environment": config.SERVER_ENVIRONMENT,
                "instance_id": config.SERVER_INSTANCE_ID,
            },
        )
        self.assertNotEqual(config.SERVER_INSTANCE_ID, "album-auth-staging")

    def test_schema_is_additive_and_wechat_binding_uses_existing_account(self):
        conn = self.db.connect()
        try:
            account_id = conn.execute(
                "SELECT id FROM accounts WHERE username = 'tenant_a'"
            ).fetchone()["id"]
            conn.execute(
                "INSERT INTO cloud_projects (account_id, project_code, project_name) "
                "VALUES (?, 'LEGACY-001', '旧云预览工程')",
                (account_id,),
            )
            conn.commit()
            counts_before = {
                table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("accounts", "cloud_projects", "cloud_thumbs")
            }
        finally:
            conn.close()
        self.db.init_db()
        conn = self.db.connect()
        try:
            counts_after = {
                table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("accounts", "cloud_projects", "cloud_thumbs")
            }
            mobile_tables = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            upload_session_columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(mobile_upload_sessions)")
            }
        finally:
            conn.close()
        self.assertEqual(counts_after, counts_before)
        self.assertTrue(
            {
                "wechat_bindings",
                "cloud_engineering_projects",
                "cloud_units",
                "mobile_batches",
                "cloud_photos",
                "mobile_jobs",
                "desktop_sync_cursors",
                "mobile_upload_sessions",
                "mobile_upload_chunks",
            }.issubset(mobile_tables)
        )
        self.assertTrue(
            {"cleanup_status", "cleanup_error"}.issubset(upload_session_columns)
        )

        first = self.client.post(
            "/api/mobile/v1/auth/wechat-login",
            json={"code": "temporary-code-a", "app_id": "wx-test"},
        )
        self.assertTrue(first.get_json()["binding_required"])
        bound = self.client.post(
            "/api/mobile/v1/auth/wechat-bind",
            json={
                "binding_ticket": first.get_json()["binding_ticket"],
                "username": "tenant_a",
                "password": "TenantA2026",
            },
        )
        self.assertEqual(bound.status_code, 200, bound.get_json())
        mobile_token = bound.get_json()["token"]
        blocked_inbox = self.client.get(
            "/api/desktop/v1/inbox?desktop_machine_id=MACHINE-A",
            headers=self._headers(mobile_token),
        )
        self.assertEqual(blocked_inbox.status_code, 403)
        self.assertEqual(
            blocked_inbox.get_json()["code"], "desktop_sync_token_required"
        )
        ordinary_desktop_token_blocked = self.client.get(
            "/api/desktop/v1/inbox?desktop_machine_id=MACHINE-A",
            headers=self._headers(self.token_a),
        )
        self.assertEqual(ordinary_desktop_token_blocked.status_code, 403)
        self.assertEqual(
            ordinary_desktop_token_blocked.get_json()["code"],
            "desktop_sync_token_required",
        )
        blocked_activate = self.client.post(
            "/api/activate",
            json={"machine_id": "MACHINE-A"},
            headers=self._headers(mobile_token),
        )
        self.assertEqual(blocked_activate.status_code, 403)
        blocked_snapshot = self.client.post(
            "/api/desktop/v1/project-snapshot",
            json={
                "snapshot_id": str(uuid.uuid4()),
                "revision": 99,
                "desktop_machine_id": "MACHINE-A",
                "project": {"id": "mobile-must-not-write", "project_name": "越权"},
                "tree": [],
                "other_tree": [],
            },
            headers=self._headers(mobile_token),
        )
        self.assertEqual(blocked_snapshot.status_code, 403)
        self.assertEqual(
            blocked_snapshot.get_json()["code"], "desktop_sync_token_required"
        )
        blocked_cloud_clear = self.client.post(
            "/api/cloud/clear",
            json={"project_id": 0},
            headers=self._headers(mobile_token),
        )
        self.assertEqual(blocked_cloud_clear.status_code, 403)
        self.assertEqual(blocked_cloud_clear.get_json()["code"], "mobile_scope_forbidden")

        activated = self.client.post(
            "/api/activate",
            json={"machine_id": "MACHINE-A"},
            headers=self._headers(self.token_a),
        )
        self.assertEqual(activated.status_code, 200, activated.get_json())
        sync_token = activated.get_json()["desktop_sync_token"]
        wrong_bound_machine = self.client.get(
            "/api/desktop/v1/inbox?desktop_machine_id=MACHINE-A-ALT",
            headers=self._headers(sync_token),
        )
        self.assertEqual(wrong_bound_machine.status_code, 403)
        self.assertEqual(
            wrong_bound_machine.get_json()["code"],
            "desktop_token_machine_mismatch",
        )
        correct_bound_machine = self.client.get(
            "/api/desktop/v1/inbox?desktop_machine_id=MACHINE-A",
            headers=self._headers(sync_token),
        )
        self.assertEqual(correct_bound_machine.status_code, 200)
        blocked_mobile_api = self.client.get(
            "/api/mobile/v1/projects", headers=self._headers(sync_token)
        )
        self.assertEqual(blocked_mobile_api.status_code, 403)
        self.assertEqual(
            blocked_mobile_api.get_json()["code"], "desktop_sync_scope_forbidden"
        )
        blocked_legacy_cloud_write = self.client.post(
            "/api/cloud/clear",
            json={"project_id": 0},
            headers=self._headers(sync_token),
        )
        self.assertEqual(blocked_legacy_cloud_write.status_code, 403)

        conn = self.db.connect()
        try:
            conn.execute("UPDATE accounts SET role = 'admin' WHERE id = ?", (account_id,))
            conn.commit()
        finally:
            conn.close()
        try:
            scoped_admin = self.client.get(
                "/api/admin/accounts", headers=self._headers(sync_token)
            )
            desktop_admin = self.client.get(
                "/api/admin/accounts", headers=self._headers(self.token_a)
            )
            self.assertEqual(scoped_admin.status_code, 403)
            self.assertEqual(desktop_admin.status_code, 200)
        finally:
            conn = self.db.connect()
            try:
                conn.execute(
                    "UPDATE accounts SET role = 'user' WHERE id = ?", (account_id,)
                )
                conn.commit()
            finally:
                conn.close()

        # 快照不带机器 ID 必须失败，且不得清空既有工程绑定。
        missing_machine_snapshot = self.client.post(
            "/api/desktop/v1/project-snapshot",
            json={
                "snapshot_id": str(uuid.uuid4()),
                "revision": 999,
                "project": {"id": "default", "project_name": "不应写入"},
                "tree": [],
                "other_tree": [],
            },
            headers=self._headers(self.desktop_token_a),
        )
        self.assertEqual(missing_machine_snapshot.status_code, 403)
        conn = self.db.connect()
        try:
            preserved = conn.execute(
                "SELECT desktop_machine_id, project_name FROM cloud_engineering_projects "
                "WHERE account_id = ? AND project_id = 'default'",
                (account_id,),
            ).fetchone()
            self.assertEqual(preserved["desktop_machine_id"], "MACHINE-A")
            self.assertEqual(preserved["project_name"], "甲账号工程")
        finally:
            conn.close()
        second = self.client.post(
            "/api/mobile/v1/auth/wechat-login",
            json={"code": "temporary-code-a", "app_id": "wx-test"},
        )
        self.assertIn("token", second.get_json())
        self.assertNotIn("binding_ticket", second.get_json())

    def test_single_wechat_binding_unbinds_and_revokes_old_mobile_token(self):
        from server import app as server_app

        server_app._rate_hits.clear()
        username = "link_guard_user"
        password = "LinkGuard2026"
        self._register(username, password)
        desktop_account_token = self._login(username, password)
        desktop_sync_token = self._activate(desktop_account_token, "MACHINE-LINK")

        first_login = self.client.post(
            "/api/mobile/v1/auth/wechat-login",
            json={"code": "link-first-wechat", "app_id": "wx-link-a"},
        )
        self.assertEqual(first_login.status_code, 200, first_login.get_json())
        first_bind = self.client.post(
            "/api/mobile/v1/auth/wechat-bind",
            json={
                "binding_ticket": first_login.get_json()["binding_ticket"],
                "username": username,
                "password": password,
            },
        )
        self.assertEqual(first_bind.status_code, 200, first_bind.get_json())
        mobile_token = first_bind.get_json()["token"]
        self.assertEqual(
            self.client.get(
                "/api/mobile/v1/bootstrap", headers=self._headers(mobile_token)
            ).status_code,
            200,
        )

        second_login = self.client.post(
            "/api/mobile/v1/auth/wechat-login",
            json={"code": "link-second-wechat", "app_id": "wx-link-b"},
        )
        second_bind = self.client.post(
            "/api/mobile/v1/auth/wechat-bind",
            json={
                "binding_ticket": second_login.get_json()["binding_ticket"],
                "username": username,
                "password": password,
            },
        )
        self.assertEqual(second_bind.status_code, 409, second_bind.get_json())
        self.assertEqual(second_bind.get_json()["code"], "account_already_bound")

        binding = self.client.get(
            "/api/desktop/v1/wechat-binding?desktop_machine_id=MACHINE-LINK",
            headers=self._headers(desktop_sync_token),
        )
        self.assertTrue(binding.get_json()["bound"])
        wrong_password = self.client.delete(
            "/api/desktop/v1/wechat-binding",
            json={"desktop_machine_id": "MACHINE-LINK", "password": "wrong-password"},
            headers=self._headers(desktop_sync_token),
        )
        self.assertEqual(wrong_password.status_code, 401)
        unbound = self.client.delete(
            "/api/desktop/v1/wechat-binding",
            json={"desktop_machine_id": "MACHINE-LINK", "password": password},
            headers=self._headers(desktop_sync_token),
        )
        self.assertEqual(unbound.status_code, 200, unbound.get_json())
        self.assertIn("立即失效", unbound.get_json()["message"])
        self.assertEqual(
            self.client.get(
                "/api/mobile/v1/bootstrap", headers=self._headers(mobile_token)
            ).status_code,
            401,
        )
        login_after_unbind = self.client.post(
            "/api/mobile/v1/auth/wechat-login",
            json={"code": "link-first-wechat", "app_id": "wx-link-a"},
        )
        self.assertTrue(login_after_unbind.get_json()["binding_required"])

    def test_professional_requirement_survives_upload_and_gallery_paginates_other_tree(self):
        from server import app as server_app

        server_app._rate_hits.clear()
        username = "rule_capture_user"
        password = "RuleCapture2026"
        machine_id = "MACHINE-RULE"
        self._register(username, password)
        desktop_account_token = self._login(username, password)
        desktop_sync_token = self._activate(desktop_account_token, machine_id)
        requirement = {
            "template_code": "FJ-JG-001",
            "industry": "房建工程",
            "project_type": "住宅工程",
            "phase": "主体结构",
            "division": "混凝土结构",
            "item": "钢筋安装",
            "process": "隐蔽验收",
            "photo_requirement_name": "钢筋安装隐蔽验收",
            "required_type": "required",
            "min_photo_count": 2,
            "recommended_photo_count": 3,
            "shot_types": "全景、节点近景",
            "timing": "隐蔽前",
            "before_concealment_required": "是",
            "exif_required": "是",
        }
        self._snapshot(
            desktop_sync_token,
            "专业采集工程",
            desktop_machine_id=machine_id,
            revision=20,
            requirements=[requirement],
        )

        login = self.client.post(
            "/api/mobile/v1/auth/wechat-login",
            json={"code": "rule-capture-wechat", "app_id": "wx-rule"},
        )
        bound = self.client.post(
            "/api/mobile/v1/auth/wechat-bind",
            json={
                "binding_ticket": login.get_json()["binding_ticket"],
                "username": username,
                "password": password,
            },
        )
        self.assertEqual(bound.status_code, 200, bound.get_json())
        mobile_token = bound.get_json()["token"]

        rules = self.client.get(
            "/api/mobile/v1/projects/default/requirements",
            headers=self._headers(mobile_token),
        )
        self.assertEqual(rules.status_code, 200, rules.get_json())
        self.assertEqual(rules.get_json()["summary"]["required"], 1)
        self.assertEqual(rules.get_json()["requirements"][0]["template_code"], "FJ-JG-001")

        self._snapshot(
            desktop_sync_token,
            "专业采集工程",
            desktop_machine_id=machine_id,
            revision=21,
        )
        preserved = self.client.get(
            "/api/mobile/v1/projects/default/requirements",
            headers=self._headers(mobile_token),
        )
        self.assertEqual(len(preserved.get_json()["requirements"]), 1)

        batch_response = self.client.post(
            "/api/mobile/v1/batches",
            json={
                "client_batch_id": str(uuid.uuid4()),
                "project_id": "default",
                "scope": "engineering",
                "category": "construction",
                "mode": "direct",
                "assignment": {"unit_code": "YNLQ-001-01-001", "process_name": ""},
                "requirement": {
                    "template_code": "FJ-JG-001",
                    "photo_requirement_name": "客户端不得覆盖服务端名称",
                },
            },
            headers=self._headers(mobile_token),
        )
        self.assertEqual(batch_response.status_code, 201, batch_response.get_json())
        batch_id = batch_response.get_json()["batch"]["batch_id"]
        self.assertEqual(
            batch_response.get_json()["batch"]["requirement"]["photo_requirement_name"],
            "钢筋安装隐蔽验收",
        )
        engineering_uuid = str(uuid.uuid4())
        uploaded = self._upload(
            mobile_token, batch_id, engineering_uuid, self._jpeg(), filename="rule.jpg"
        )
        self.assertEqual(uploaded.status_code, 201, uploaded.get_json())
        committed = self.client.post(
            f"/api/mobile/v1/batches/{batch_id}/commit",
            headers=self._headers(mobile_token),
        )
        self.assertEqual(committed.status_code, 200, committed.get_json())
        detail = self.client.get(
            f"/api/mobile/v1/photos/{engineering_uuid}",
            headers=self._headers(mobile_token),
        ).get_json()["photo"]
        self.assertEqual(detail["requirement"]["template_code"], "FJ-JG-001")

        for index in range(3):
            batch_id_other = self._create_batch(mobile_token, scope="other")
            photo_uuid = str(uuid.uuid4())
            uploaded_other = self._upload(
                mobile_token,
                batch_id_other,
                photo_uuid,
                self._jpeg(color=(30 + index, 90, 130)),
                filename=f"other-{index}.jpg",
            )
            self.assertEqual(uploaded_other.status_code, 201, uploaded_other.get_json())
            committed_other = self.client.post(
                f"/api/mobile/v1/batches/{batch_id_other}/commit",
                headers=self._headers(mobile_token),
            )
            self.assertEqual(committed_other.status_code, 200, committed_other.get_json())

        first_page = self.client.get(
            "/api/mobile/v1/photos?project_id=default&scope=other&"
            "other_node_code=OTHER-SITE&limit=2",
            headers=self._headers(mobile_token),
        )
        self.assertEqual(first_page.status_code, 200, first_page.get_json())
        self.assertEqual(first_page.get_json()["total"], 3)
        self.assertEqual(len(first_page.get_json()["photos"]), 2)
        cursor = first_page.get_json()["next_cursor"]
        self.assertTrue(cursor)
        second_page = self.client.get(
            "/api/mobile/v1/photos?project_id=default&scope=other&"
            f"other_node_code=OTHER-SITE&limit=2&cursor={cursor}",
            headers=self._headers(mobile_token),
        )
        self.assertEqual(len(second_page.get_json()["photos"]), 1)
        self.assertEqual(second_page.get_json()["next_cursor"], "")

        inbox = self.client.get(
            f"/api/desktop/v1/inbox?desktop_machine_id={machine_id}&limit=20",
            headers=self._headers(desktop_sync_token),
        )
        self.assertEqual(inbox.status_code, 200, inbox.get_json())
        engineering_item = next(
            item for item in inbox.get_json()["items"]
            if item["photo_uuid"] == engineering_uuid
        )
        self.assertEqual(engineering_item["requirement_code"], "FJ-JG-001")
        self.assertEqual(engineering_item["requirement_name"], "钢筋安装隐蔽验收")

    def test_tenant_isolation_for_projects_batches_and_photos(self):
        projects_a = self.client.get(
            "/api/mobile/v1/projects", headers=self._headers(self.token_a)
        ).get_json()["projects"]
        projects_b = self.client.get(
            "/api/mobile/v1/projects", headers=self._headers(self.token_b)
        ).get_json()["projects"]
        projects_a_by_id = {project["project_id"]: project for project in projects_a}
        projects_b_by_id = {project["project_id"]: project for project in projects_b}
        self.assertEqual(projects_a_by_id["default"]["project_name"], "甲账号工程")
        self.assertEqual(projects_b_by_id["default"]["project_name"], "乙账号工程")
        self.assertNotIn("gallery-order", projects_b_by_id)

        batch_id = self._create_batch(self.token_a)
        photo_uuid = str(uuid.uuid4())
        uploaded = self._upload(
            self.token_a, batch_id, photo_uuid, self._jpeg()
        )
        self.assertEqual(uploaded.status_code, 201, uploaded.get_json())
        hidden_photo = self.client.get(
            f"/api/mobile/v1/photos/{photo_uuid}", headers=self._headers(self.token_b)
        )
        hidden_batch = self.client.get(
            f"/api/mobile/v1/batches/{batch_id}", headers=self._headers(self.token_b)
        )
        self.assertEqual(hidden_photo.status_code, 404)
        self.assertEqual(hidden_batch.status_code, 404)

    def test_server_accepts_complete_888_unit_snapshot(self):
        units = [
            {
                "unit_code": f"YNLQ-FULL-{index:04d}",
                "internal_project_code": f"LOCAL-FULL-{index:04d}",
                "name": f"验收单元{index:04d}",
                "division_type": "unit",
                "processes": ["土方填筑"] if index == 1 else [],
            }
            for index in range(1, 889)
        ]
        response = self.client.post(
            "/api/desktop/v1/project-snapshot",
            json={
                "snapshot_id": str(uuid.uuid4()),
                "revision": 1,
                "desktop_machine_id": "MACHINE-A",
                "project": {
                    "id": "ynlq-888",
                    "project_code": "YNLQ-FULL",
                    "project_name": "邯郸市永年区洺河龙泉缓洪工程",
                },
                "tree": [
                    {
                        "code": "YNLQ-FULL-C",
                        "name": "洺河龙泉缓洪工程",
                        "unit_projects": [
                            {
                                "code": "YNLQ-FULL-U",
                                "name": "单位工程",
                                "parts": [
                                    {
                                        "code": "YNLQ-FULL-P",
                                        "name": "分部工程",
                                        "units": units,
                                    }
                                ],
                            }
                        ],
                    }
                ],
                "other_tree": [
                    {"node_code": "YNLQ-FULL-OTHER", "name": "其它影像"}
                ],
            },
            headers=self._headers(self.desktop_token_a),
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["unit_count"], 888)
        self.assertEqual(response.get_json()["process_count"], 1)
        tree = self.client.get(
            "/api/mobile/v1/projects/ynlq-888/tree",
            headers=self._headers(self.token_a),
        )
        self.assertEqual(tree.status_code, 200, tree.get_json())
        self.assertEqual(len(tree.get_json()["units"]), 888)
        self.assertEqual(tree.get_json()["project"]["metadata"]["unit_count"], 888)

    def test_gallery_is_latest_first_with_stable_backward_cursor(self):
        project_id = "gallery-order"
        self._snapshot(self.token_a, "图库分页工程", project_id=project_id)
        photo_uuids = []
        for index, color in enumerate(((31, 61, 91), (32, 62, 92), (33, 63, 93))):
            batch_id = self._create_batch(self.token_a, project_id=project_id)
            photo_uuid = str(uuid.uuid4())
            uploaded = self._upload(
                self.token_a,
                batch_id,
                photo_uuid,
                self._jpeg(color),
                filename=f"分页-{index}.jpg",
            )
            self.assertEqual(uploaded.status_code, 201, uploaded.get_json())
            photo_uuids.append(photo_uuid)

        first = self.client.get(
            f"/api/mobile/v1/photos?project_id={project_id}&limit=2",
            headers=self._headers(self.token_a),
        )
        self.assertEqual(first.status_code, 200, first.get_json())
        first_payload = first.get_json()
        self.assertEqual(
            [photo["photo_uuid"] for photo in first_payload["photos"]],
            [photo_uuids[2], photo_uuids[1]],
        )
        self.assertEqual(
            first_payload["next_cursor"],
            str(first_payload["photos"][-1]["cursor"]),
        )

        # 翻页期间新上传的照片只出现在新的首屏，不会混入旧游标之后的页面。
        new_batch = self._create_batch(self.token_a, project_id=project_id)
        newest_uuid = str(uuid.uuid4())
        newest = self._upload(
            self.token_a,
            new_batch,
            newest_uuid,
            self._jpeg((34, 64, 94)),
            filename="分页-最新.jpg",
        )
        self.assertEqual(newest.status_code, 201, newest.get_json())

        second = self.client.get(
            f"/api/mobile/v1/photos?project_id={project_id}&limit=2"
            f"&cursor={first_payload['next_cursor']}",
            headers=self._headers(self.token_a),
        )
        self.assertEqual(second.status_code, 200, second.get_json())
        self.assertEqual(
            [photo["photo_uuid"] for photo in second.get_json()["photos"]],
            [photo_uuids[0]],
        )
        self.assertEqual(second.get_json()["next_cursor"], "")

        refreshed = self.client.get(
            f"/api/mobile/v1/photos?project_id={project_id}&limit=2&cursor=0",
            headers=self._headers(self.token_a),
        ).get_json()
        self.assertEqual(refreshed["photos"][0]["photo_uuid"], newest_uuid)

    def test_batch_target_is_frozen_and_requires_an_active_bound_machine(self):
        empty_project = "machine-empty"
        self._snapshot(
            self.token_a,
            "未绑定电脑工程",
            project_id=empty_project,
        )
        conn = self.db.connect()
        try:
            conn.execute(
                "UPDATE cloud_engineering_projects SET desktop_machine_id = '' "
                "WHERE project_id = ?",
                (empty_project,),
            )
            conn.commit()
        finally:
            conn.close()
        empty_target = self.client.post(
            "/api/mobile/v1/batches",
            json={
                "client_batch_id": str(uuid.uuid4()),
                "project_id": empty_project,
                "scope": "engineering",
                "category": "construction",
                "mode": "direct",
                "assignment": {"unit_code": "YNLQ-001-01-001", "process_name": ""},
            },
            headers=self._headers(self.token_a),
        )
        self.assertEqual(empty_target.status_code, 409)
        self.assertEqual(empty_target.get_json()["code"], "project_desktop_not_bound")

        route_project = "machine-route"
        self._snapshot(self.token_a, "机器冻结工程", project_id=route_project)
        frozen_batch = self._create_batch(self.token_a, project_id=route_project)
        self._snapshot(
            self.token_a,
            "机器冻结工程",
            project_id=route_project,
            desktop_machine_id="MACHINE-A-ALT",
            revision=8,
        )
        frozen_detail = self.client.get(
            f"/api/mobile/v1/batches/{frozen_batch}",
            headers=self._headers(self.token_a),
        ).get_json()["batch"]
        self.assertEqual(frozen_detail["target_machine_id"], "MACHINE-A")
        routed_uuid = str(uuid.uuid4())
        routed = self._upload(
            self.token_a, frozen_batch, routed_uuid, self._jpeg((21, 41, 61))
        )
        self.assertEqual(routed.status_code, 201, routed.get_json())
        committed = self.client.post(
            f"/api/mobile/v1/batches/{frozen_batch}/commit",
            headers=self._headers(self.token_a),
        )
        self.assertEqual(committed.status_code, 200, committed.get_json())
        alt_items = self.client.get(
            "/api/desktop/v1/inbox?desktop_machine_id=MACHINE-A-ALT&limit=100",
            headers=self._headers(self.desktop_token_a_alt),
        ).get_json()["items"]
        original_items = self.client.get(
            "/api/desktop/v1/inbox?desktop_machine_id=MACHINE-A&limit=100",
            headers=self._headers(self.desktop_token_a),
        ).get_json()["items"]
        self.assertNotIn(routed_uuid, {item["photo_uuid"] for item in alt_items})
        self.assertIn(routed_uuid, {item["photo_uuid"] for item in original_items})

        unbound_project = "machine-unbound"
        self._snapshot(self.token_a, "解绑保护工程", project_id=unbound_project)
        unbound_batch = self._create_batch(self.token_a, project_id=unbound_project)
        conn = self.db.connect()
        try:
            conn.execute(
                "UPDATE machines SET active = 0 WHERE machine_id = 'MACHINE-A'"
            )
            conn.commit()
        finally:
            conn.close()
        try:
            rejected_upload = self._upload(
                self.token_a,
                unbound_batch,
                str(uuid.uuid4()),
                self._jpeg((22, 42, 62)),
            )
            self.assertEqual(rejected_upload.status_code, 403)
            self.assertEqual(
                rejected_upload.get_json()["code"], "desktop_machine_not_bound"
            )
            rejected_upload.close()
            create_while_unbound = self.client.post(
                "/api/mobile/v1/batches",
                json={
                    "client_batch_id": str(uuid.uuid4()),
                    "project_id": unbound_project,
                    "scope": "engineering",
                    "category": "construction",
                    "mode": "direct",
                    "assignment": {
                        "unit_code": "YNLQ-001-01-001",
                        "process_name": "",
                    },
                },
                headers=self._headers(self.token_a),
            )
            self.assertEqual(create_while_unbound.status_code, 409)
            self.assertEqual(
                create_while_unbound.get_json()["code"], "project_desktop_not_active"
            )
        finally:
            conn = self.db.connect()
            try:
                conn.execute(
                    "UPDATE machines SET active = 1 WHERE machine_id = 'MACHINE-A'"
                )
                conn.commit()
            finally:
                conn.close()

    def test_batch_idempotency_compares_the_complete_request(self):
        client_batch_id = str(uuid.uuid4())
        payload = {
            "client_batch_id": client_batch_id,
            "project_id": "default",
            "scope": "engineering",
            "category": "construction",
            "mode": "direct",
            "assignment": {
                "unit_code": "YNLQ-001-01-001",
                "process_name": "",
            },
        }
        created = self.client.post(
            "/api/mobile/v1/batches",
            json=payload,
            headers=self._headers(self.token_a),
        )
        self.assertEqual(created.status_code, 201, created.get_json())
        repeated = self.client.post(
            "/api/mobile/v1/batches",
            json=payload,
            headers=self._headers(self.token_a),
        )
        self.assertEqual(repeated.status_code, 200, repeated.get_json())
        self.assertTrue(repeated.get_json()["idempotent"])
        conflicted = self.client.post(
            "/api/mobile/v1/batches",
            json={**payload, "category": "supervision"},
            headers=self._headers(self.token_a),
        )
        self.assertEqual(conflicted.status_code, 409)
        self.assertEqual(conflicted.get_json()["code"], "batch_id_conflict")

    def test_committed_upload_survives_response_failure_and_retry(self):
        batch_id = self._create_batch(self.token_a)
        photo_uuid = str(uuid.uuid4())
        original = self._jpeg((17, 47, 77))
        with patch(
            "server.mobile_api._photo_payload",
            side_effect=RuntimeError("模拟提交后响应序列化失败"),
        ), patch.object(self.app.logger, "exception"):
            failed_response = self._upload(
                self.token_a, batch_id, photo_uuid, original
            )
        self.assertEqual(failed_response.status_code, 500)

        retry = self._upload(self.token_a, batch_id, photo_uuid, original)
        self.assertEqual(retry.status_code, 200, retry.get_json())
        self.assertTrue(retry.get_json()["idempotent"])
        preview = self.client.get(retry.get_json()["photo"]["download_url"])
        self.assertEqual(preview.status_code, 200)
        preview.close()

        committed = self.client.post(
            f"/api/mobile/v1/batches/{batch_id}/commit",
            headers=self._headers(self.token_a),
        )
        self.assertEqual(committed.status_code, 200, committed.get_json())
        inbox = self.client.get(
            "/api/desktop/v1/inbox?desktop_machine_id=MACHINE-A&limit=100",
            headers=self._headers(self.desktop_token_a),
        ).get_json()["items"]
        item = next(value for value in inbox if value["photo_uuid"] == photo_uuid)
        original_response = self.client.get(
            item["original_download_url"],
            headers=self._headers(self.desktop_token_a),
        )
        self.assertEqual(original_response.status_code, 200)
        self.assertEqual(original_response.data, original)
        original_response.close()

    def test_concurrent_same_uuid_upload_does_not_hold_sqlite_write_lock(self):
        from server.mobile_storage import LocalObjectStorage

        project_id = "upload-concurrency"
        self._snapshot(self.token_a, "并发上传工程", project_id=project_id)
        batch_id = self._create_batch(self.token_a, project_id=project_id)
        photo_uuid = str(uuid.uuid4())
        content = self._jpeg((71, 91, 111), size=(1200, 900))
        entered_storage = threading.Event()
        release_storage = threading.Event()
        real_put_stream = LocalObjectStorage.put_stream

        def slow_put_stream(instance, key, stream, size_bytes, content_type):
            entered_storage.set()
            if not release_storage.wait(5):
                raise AssertionError("测试未及时释放对象写入")
            return real_put_stream(instance, key, stream, size_bytes, content_type)

        def threaded_upload():
            with self.app.test_client() as client:
                return client.post(
                    f"/api/mobile/v1/batches/{batch_id}/photos",
                    data={
                        "file": (io.BytesIO(content), "并发原图.jpg"),
                        "photo_uuid": photo_uuid,
                        "client_captured_at": "2026-08-25T01:02:03Z",
                        "orientation": "1",
                        "sha256": hashlib.sha256(content).hexdigest(),
                        "original_size_bytes": str(len(content)),
                        "original_filename": "并发原图.jpg",
                    },
                    headers=self._headers(self.token_a),
                    content_type="multipart/form-data",
                )

        with patch(
            "server.mobile_storage.LocalObjectStorage.put_stream", new=slow_put_stream
        ), ThreadPoolExecutor(max_workers=2) as pool:
            first_future = pool.submit(threaded_upload)
            self.assertTrue(entered_storage.wait(3))
            second_future = pool.submit(threaded_upload)
            # 第一请求停在对象网络 I/O 时，独立 SQLite 写事务仍必须立即成功。
            conn = self.db.connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    "UPDATE accounts SET notes = notes WHERE username = 'tenant_a'"
                )
                conn.commit()
            finally:
                conn.close()
            release_storage.set()
            first = first_future.result(timeout=5)
            second = second_future.result(timeout=5)

        self.assertEqual({first.status_code, second.status_code}, {200, 201})
        self.assertEqual(
            sum(response.get_json()["idempotent"] for response in (first, second)), 1
        )
        conn = self.db.connect()
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM cloud_photos WHERE account_id = "
                "(SELECT id FROM accounts WHERE username = 'tenant_a') AND photo_uuid = ?",
                (photo_uuid,),
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(count, 1)

    def test_commit_wins_over_an_upload_already_in_object_storage(self):
        from server import config
        from server.mobile_storage import LocalObjectStorage

        project_id = "upload-commit-race"
        self._snapshot(self.token_a, "提交竞态工程", project_id=project_id)
        batch_id = self._create_batch(self.token_a, project_id=project_id)
        first_uuid = str(uuid.uuid4())
        first = self._upload(
            self.token_a, batch_id, first_uuid, self._jpeg((81, 101, 121))
        )
        self.assertEqual(first.status_code, 201, first.get_json())

        late_uuid = str(uuid.uuid4())
        late_content = self._jpeg((82, 102, 122), size=(1200, 900))
        entered_storage = threading.Event()
        release_storage = threading.Event()
        real_put_stream = LocalObjectStorage.put_stream

        def delayed_put_stream(instance, key, stream, size_bytes, content_type):
            entered_storage.set()
            if not release_storage.wait(5):
                raise AssertionError("测试未及时释放对象写入")
            return real_put_stream(instance, key, stream, size_bytes, content_type)

        def late_upload():
            with self.app.test_client() as client:
                return client.post(
                    f"/api/mobile/v1/batches/{batch_id}/photos",
                    data={
                        "file": (io.BytesIO(late_content), "迟到原图.jpg"),
                        "photo_uuid": late_uuid,
                        "orientation": "1",
                        "sha256": hashlib.sha256(late_content).hexdigest(),
                        "original_size_bytes": str(len(late_content)),
                        "original_filename": "迟到原图.jpg",
                    },
                    headers=self._headers(self.token_a),
                    content_type="multipart/form-data",
                )

        with patch(
            "server.mobile_storage.LocalObjectStorage.put_stream",
            new=delayed_put_stream,
        ), ThreadPoolExecutor(max_workers=1) as pool:
            late_future = pool.submit(late_upload)
            self.assertTrue(entered_storage.wait(3))
            committed = self.client.post(
                f"/api/mobile/v1/batches/{batch_id}/commit",
                headers=self._headers(self.token_a),
            )
            self.assertEqual(committed.status_code, 200, committed.get_json())
            release_storage.set()
            late_response = late_future.result(timeout=5)

        self.assertEqual(late_response.status_code, 409, late_response.get_json())
        self.assertEqual(late_response.get_json()["code"], "batch_committed")
        detail = self.client.get(
            f"/api/mobile/v1/batches/{batch_id}",
            headers=self._headers(self.token_a),
        ).get_json()["batch"]
        self.assertEqual(detail["status"], "desktop_pending")
        self.assertEqual(
            [photo["photo_uuid"] for photo in detail["photos"]], [first_uuid]
        )
        self.assertEqual(
            list(config.MOBILE_STORAGE_DIR.rglob(f"{late_uuid}.*")),
            [],
            "提交先完成时，迟到上传不得留孤儿对象",
        )

    def test_wechat_auth_is_rate_limited(self):
        from server import app as server_app

        server_app._rate_hits.clear()
        try:
            with patch.object(server_app, "RATE_LIMIT", 1):
                first = self.client.post(
                    "/api/mobile/v1/auth/wechat-login",
                    json={"code": "rate-first", "app_id": "wx-rate"},
                    headers={"X-Forwarded-For": "198.51.100.20"},
                    environ_base={"REMOTE_ADDR": "127.0.0.1"},
                )
                second = self.client.post(
                    "/api/mobile/v1/auth/wechat-login",
                    json={"code": "rate-second", "app_id": "wx-rate"},
                    headers={"X-Forwarded-For": "198.51.100.20"},
                    environ_base={"REMOTE_ADDR": "127.0.0.1"},
                )
                another_ip = self.client.post(
                    "/api/mobile/v1/auth/wechat-login",
                    json={"code": "rate-third", "app_id": "wx-rate"},
                    headers={"X-Forwarded-For": "198.51.100.21"},
                    environ_base={"REMOTE_ADDR": "127.0.0.1"},
                )
            self.assertEqual(first.status_code, 200, first.get_json())
            self.assertEqual(second.status_code, 429, second.get_json())
            self.assertEqual(second.get_json()["code"], "rate_limited")
            self.assertEqual(another_ip.status_code, 200, another_ip.get_json())
        finally:
            server_app._rate_hits.clear()

    def test_image_limits_decode_sha_and_idempotency(self):
        from server import config

        batch_id = self._create_batch(self.token_a)
        count_before = self._photo_count(self.token_a)

        oversized = self._jpeg((5, 15, 25), size=(800, 600))
        with patch.object(config, "MOBILE_DIRECT_UPLOAD_MAX_BYTES", 1024):
            too_large = self._upload(
                self.token_a, batch_id, str(uuid.uuid4()), oversized
            )
        self.assertEqual(too_large.status_code, 413)
        self.assertEqual(too_large.get_json()["code"], "original_too_large")

        previous_request_limit = self.app.config["MAX_CONTENT_LENGTH"]
        try:
            self.app.config["MAX_CONTENT_LENGTH"] = 1024
            request_too_large = self._upload(
                self.token_a, batch_id, str(uuid.uuid4()), oversized
            )
        finally:
            self.app.config["MAX_CONTENT_LENGTH"] = previous_request_limit
        self.assertEqual(request_too_large.status_code, 413)
        self.assertEqual(request_too_large.get_json()["code"], "request_too_large")

        broken = b"not-a-jpeg"
        invalid = self._upload(
            self.token_a, batch_id, str(uuid.uuid4()), broken
        )
        self.assertEqual(invalid.status_code, 415)
        self.assertEqual(invalid.get_json()["code"], "unsupported_original_format")
        corrupt_jpeg = self._upload(
            self.token_a, batch_id, str(uuid.uuid4()), b"\xff\xd8broken"
        )
        self.assertEqual(corrupt_jpeg.status_code, 422)
        self.assertEqual(corrupt_jpeg.get_json()["code"], "invalid_image")

        valid = self._jpeg((60, 120, 90))
        mismatch = self._upload(
            self.token_a, batch_id, str(uuid.uuid4()), valid, sha="0" * 64
        )
        self.assertEqual(mismatch.status_code, 422)
        self.assertEqual(mismatch.get_json()["code"], "sha256_mismatch")
        size_mismatch = self._upload(
            self.token_a,
            batch_id,
            str(uuid.uuid4()),
            valid,
            original_size_bytes=len(valid) + 1,
        )
        self.assertEqual(size_mismatch.status_code, 422)
        self.assertEqual(size_mismatch.get_json()["code"], "original_size_mismatch")

        wide = self._jpeg((45, 75, 105), size=(12001, 1))
        dimensions = self._upload(
            self.token_a, batch_id, str(uuid.uuid4()), wide
        )
        self.assertEqual(dimensions.status_code, 422)
        self.assertEqual(dimensions.get_json()["code"], "image_dimensions_exceeded")
        self.assertEqual(self._photo_count(self.token_a), count_before)

        photo_uuid = str(uuid.uuid4())
        first = self._upload(
            self.token_a,
            batch_id,
            photo_uuid,
            valid,
            original_filename=r"C:\DCIM\水闸原图.jpg",
        )
        second = self._upload(self.token_a, batch_id, photo_uuid, valid)
        self.assertEqual(first.status_code, 201, first.get_json())
        self.assertEqual(second.status_code, 200, second.get_json())
        self.assertTrue(second.get_json()["idempotent"])
        self.assertLessEqual(first.get_json()["photo"]["size_bytes"], 102400)
        self.assertEqual(first.get_json()["photo"]["mime_type"], "image/jpeg")
        self.assertEqual(self._photo_count(self.token_a), count_before + 1)

        conn = self.db.connect()
        try:
            stored = conn.execute(
                "SELECT * FROM cloud_photos WHERE photo_uuid = ?", (photo_uuid,)
            ).fetchone()
            self.assertEqual(stored["original_sha256"], hashlib.sha256(valid).hexdigest())
            self.assertEqual(stored["original_size_bytes"], len(valid))
            self.assertEqual(stored["original_filename"], "水闸原图.jpg")
            self.assertTrue(stored["original_storage_key"].endswith(f"/{photo_uuid}.jpg"))
            self.assertIn("/previews/", stored["preview_storage_key"])
            self.assertLessEqual(stored["preview_size_bytes"], 102400)
            self.assertNotEqual(stored["original_storage_key"], stored["preview_storage_key"])
        finally:
            conn.close()

        png_batch = self._create_batch(self.token_a)
        png_uuid = str(uuid.uuid4())
        png_content = self._png()
        png_result = self._upload(
            self.token_a,
            png_batch,
            png_uuid,
            png_content,
            filename="相册原图.png",
        )
        self.assertEqual(png_result.status_code, 201, png_result.get_json())
        conn = self.db.connect()
        try:
            png_row = conn.execute(
                "SELECT * FROM cloud_photos WHERE photo_uuid = ?", (png_uuid,)
            ).fetchone()
            self.assertEqual(png_row["original_mime_type"], "image/png")
            self.assertTrue(png_row["original_storage_key"].endswith(f"/{png_uuid}.png"))
            preview_path = config.MOBILE_STORAGE_DIR.joinpath(
                *png_row["preview_storage_key"].split("/")
            )
            preview_bytes = preview_path.read_bytes()
            self.assertTrue(preview_bytes.startswith(b"\xff\xd8"))
            self.assertLessEqual(len(preview_bytes), 102400)
        finally:
            conn.close()

        other_batch = self._create_batch(self.token_a)
        conflict = self._upload(
            self.token_a, other_batch, photo_uuid, valid
        )
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.get_json()["code"], "photo_uuid_conflict")
        empty = self.client.get(
            f"/api/mobile/v1/batches/{other_batch}",
            headers=self._headers(self.token_a),
        ).get_json()["batch"]
        self.assertEqual(empty["progress"]["total"], 0)
        self.assertEqual(self._photo_count(self.token_a), count_before + 2)

        from server.mobile_storage import StorageError

        storage_batch = self._create_batch(self.token_a)
        before_failure = self._photo_count(self.token_a)
        failed_uuid = str(uuid.uuid4())
        with patch(
            "server.mobile_storage.LocalObjectStorage.put_bytes",
            side_effect=StorageError("mock storage outage"),
        ):
            unavailable = self._upload(
                self.token_a,
                storage_batch,
                failed_uuid,
                self._jpeg((10, 20, 30)),
            )
        self.assertEqual(unavailable.status_code, 503)
        self.assertEqual(unavailable.get_json()["code"], "storage_unavailable")
        self.assertTrue(unavailable.get_json()["retryable"])
        self.assertEqual(self._photo_count(self.token_a), before_failure)
        self.assertFalse(
            list(config.MOBILE_STORAGE_DIR.rglob(f"{failed_uuid}.*")),
            "对象写入失败后不应遗留原图或预览孤儿文件",
        )

    def _photo_count(self, token):
        response = self.client.get(
            "/api/mobile/v1/photos?project_id=default&limit=100",
            headers=self._headers(token),
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        return len(response.get_json()["photos"])

    def _account_id(self, username):
        conn = self.db.connect()
        try:
            row = conn.execute(
                "SELECT id FROM accounts WHERE username = ?", (username,)
            ).fetchone()
            self.assertIsNotNone(row)
            return int(row["id"])
        finally:
            conn.close()

    def test_status_flow_inbox_ack_and_safe_download(self):
        batch_id = self._create_batch(self.token_a)
        photo_uuid = str(uuid.uuid4())
        original_content = self._jpeg((120, 80, 55))
        uploaded = self._upload(
            self.token_a,
            batch_id,
            photo_uuid,
            original_content,
            original_filename=r"D:\DCIM\水闸现场原片.jpg",
        )
        download_url = uploaded.get_json()["photo"]["download_url"]
        self.assertTrue(download_url.startswith("/api/mobile/v1/files/"))
        download = self.client.get(download_url)
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.mimetype, "image/jpeg")
        download.close()

        committed = self.client.post(
            f"/api/mobile/v1/batches/{batch_id}/commit",
            headers=self._headers(self.token_a),
        )
        self.assertEqual(committed.status_code, 200, committed.get_json())
        self.assertEqual(committed.get_json()["batch"]["status"], "desktop_pending")

        pending_commit_retry = self.client.post(
            f"/api/mobile/v1/batches/{batch_id}/commit",
            headers=self._headers(self.token_a),
        )
        self.assertEqual(pending_commit_retry.status_code, 200)
        self.assertTrue(pending_commit_retry.get_json()["idempotent"])
        pending_assignment = self.client.patch(
            f"/api/mobile/v1/batches/{batch_id}/assignments",
            json={
                "photo_uuid": photo_uuid,
                "unit_code": "YNLQ-001-01-001",
                "process_name": "",
            },
            headers=self._headers(self.token_a),
        )
        self.assertEqual(pending_assignment.status_code, 409)
        self.assertEqual(pending_assignment.get_json()["code"], "batch_committed")
        pending_analysis = self.client.post(
            f"/api/mobile/v1/batches/{batch_id}/analyze",
            headers=self._headers(self.token_a),
        )
        self.assertEqual(pending_analysis.status_code, 409)
        self.assertEqual(pending_analysis.get_json()["code"], "batch_not_analyzable")

        no_machine = self.client.get(
            "/api/desktop/v1/inbox?limit=100",
            headers=self._headers(self.desktop_token_a),
        )
        self.assertEqual(no_machine.status_code, 403)
        self.assertEqual(
            no_machine.get_json()["code"], "desktop_token_machine_mismatch"
        )
        inbox_response = self.client.get(
            "/api/desktop/v1/inbox?limit=100&desktop_machine_id=MACHINE-A",
            headers=self._headers(self.desktop_token_a),
        )
        self.assertEqual(inbox_response.status_code, 200, inbox_response.get_json())
        inbox_payload = inbox_response.get_json()
        self.assertEqual(inbox_payload["original_max_bytes"], 50 * 1024 * 1024)
        inbox = inbox_payload["items"]
        item = next(entry for entry in inbox if entry["photo_uuid"] == photo_uuid)
        self.assertEqual(item["unit_code"], "YNLQ-001-01-001")
        self.assertEqual(item["original_sha256"], hashlib.sha256(original_content).hexdigest())
        self.assertEqual(item["original_size_bytes"], len(original_content))
        self.assertEqual(item["original_filename"], "水闸现场原片.jpg")
        self.assertEqual(item["original_mime_type"], "image/jpeg")
        original_download = self.client.get(
            item["original_download_url"],
            headers=self._headers(self.desktop_token_a),
        )
        self.assertEqual(original_download.status_code, 200)
        self.assertEqual(original_download.data, original_content)
        original_download.close()

        ack_data = {
            "local_project_code": "LOCAL-001",
            "local_photo_id": "SY-0001",
            "desktop_machine_id": "MACHINE-A",
        }
        wrong_machine = self.client.post(
            f"/api/desktop/v1/photos/{photo_uuid}/ack",
            json={**ack_data, "desktop_machine_id": "MACHINE-A-ALT"},
            headers=self._headers(self.desktop_token_a_alt),
        )
        self.assertEqual(wrong_machine.status_code, 403)
        self.assertEqual(wrong_machine.get_json()["code"], "wrong_desktop_machine")

        from server.mobile_storage import StorageError

        with patch(
            "server.mobile_storage.LocalObjectStorage.delete",
            side_effect=StorageError("mock cleanup outage"),
        ):
            ack = self.client.post(
                f"/api/desktop/v1/photos/{photo_uuid}/ack",
                json=ack_data,
                headers=self._headers(self.desktop_token_a),
            )
        self.assertEqual(ack.status_code, 200, ack.get_json())
        self.assertFalse(ack.get_json()["idempotent"])
        self.assertTrue(ack.get_json()["cleanup_pending"])

        again = self.client.post(
            f"/api/desktop/v1/photos/{photo_uuid}/ack",
            json=ack_data,
            headers=self._headers(self.desktop_token_a),
        )
        self.assertEqual(again.status_code, 200, again.get_json())
        self.assertTrue(again.get_json()["idempotent"])
        self.assertEqual(again.get_json()["cleanup_status"], "deleted")
        self.assertFalse(again.get_json()["cleanup_pending"])

        expired_original = self.client.get(
            item["original_download_url"],
            headers=self._headers(self.desktop_token_a),
        )
        self.assertEqual(expired_original.status_code, 404)
        preview_after_cleanup = self.client.get(download_url)
        self.assertEqual(preview_after_cleanup.status_code, 200)
        preview_after_cleanup.close()
        detail = self.client.get(
            f"/api/mobile/v1/batches/{batch_id}", headers=self._headers(self.token_a)
        ).get_json()["batch"]
        self.assertEqual(detail["status"], "desktop_imported")
        imported_commit_retry = self.client.post(
            f"/api/mobile/v1/batches/{batch_id}/commit",
            headers=self._headers(self.token_a),
        )
        self.assertEqual(imported_commit_retry.status_code, 200)
        self.assertTrue(imported_commit_retry.get_json()["idempotent"])
        self.assertEqual(
            imported_commit_retry.get_json()["batch"]["status"], "desktop_imported"
        )
        self.assertEqual(
            imported_commit_retry.get_json()["batch"]["photos"][0]["status"],
            "desktop_imported",
        )
        no_requeued_original = self.client.get(
            "/api/desktop/v1/inbox?limit=100&desktop_machine_id=MACHINE-A",
            headers=self._headers(self.desktop_token_a),
        ).get_json()["items"]
        self.assertNotIn(photo_uuid, {item["photo_uuid"] for item in no_requeued_original})
        analyze_after_ack = self.client.post(
            f"/api/mobile/v1/batches/{batch_id}/analyze",
            headers=self._headers(self.token_a),
        )
        self.assertEqual(analyze_after_ack.status_code, 409)
        self.assertEqual(analyze_after_ack.get_json()["code"], "batch_not_analyzable")

    def test_auto_review_assignment_and_desktop_backfill(self):
        batch_id = self._create_batch(self.token_a, mode="auto")
        photo_uuid = str(uuid.uuid4())
        self._upload(
            self.token_a,
            batch_id,
            photo_uuid,
            self._jpeg((80, 90, 140)),
            filename="左岸连接堤-验收.jpg",
        )
        from server.mobile_storage import LocalObjectStorage

        recognition_reads = []
        real_get_bytes = LocalObjectStorage.get_bytes

        def tracked_get_bytes(instance, key, max_bytes):
            recognition_reads.append((key, max_bytes))
            return real_get_bytes(instance, key, max_bytes)

        with patch(
            "server.mobile_recognition.recognize_watermark",
            return_value={
                "photo_date": "2026-08-25",
                "title": "模板验收",
                "construction_area": "左岸连接堤",
                "construction_content": "模板验收",
                "project_name": "洺河龙泉缓洪工程",
                "watermark_text": "施工区域：左岸连接堤",
            },
        ), patch(
            "server.mobile_storage.LocalObjectStorage.get_bytes",
            new=tracked_get_bytes,
        ):
            accepted, analyzed = self._analyze_and_wait(self.token_a, batch_id)
        self.assertEqual(accepted.status_code, 202, accepted.get_json())
        self.assertEqual(analyzed.get_json()["batch"]["status"], "needs_review")
        analyzed_photo = analyzed.get_json()["batch"]["photos"][0]
        self.assertEqual(analyzed_photo["match"]["confidence"], "high")
        self.assertEqual(analyzed_photo["assignment"]["unit_code"], "YNLQ-001-01-001")
        analyze_retry = self.client.post(
            f"/api/mobile/v1/batches/{batch_id}/analyze",
            headers=self._headers(self.token_a),
        )
        self.assertEqual(analyze_retry.status_code, 200)
        self.assertTrue(analyze_retry.get_json()["idempotent"])
        self.assertEqual(analyze_retry.get_json()["batch"]["status"], "needs_review")
        retry_detail = self.client.get(
            f"/api/mobile/v1/batches/{batch_id}",
            headers=self._headers(self.token_a),
        ).get_json()["batch"]
        self.assertEqual(retry_detail["status"], "needs_review")
        self.assertTrue(recognition_reads)
        self.assertIn("/photos/", recognition_reads[0][0])
        self.assertNotIn("/previews/", recognition_reads[0][0])
        self.assertEqual(recognition_reads[0][1], 50 * 1024 * 1024)
        late_after_review_uuid = str(uuid.uuid4())
        late_after_review = self._upload(
            self.token_a,
            batch_id,
            late_after_review_uuid,
            self._jpeg((81, 91, 141)),
        )
        self.assertEqual(late_after_review.status_code, 409)
        self.assertEqual(late_after_review.get_json()["code"], "batch_closed")
        assigned = self.client.patch(
            f"/api/mobile/v1/batches/{batch_id}/assignments",
            json={
                "assignments": [
                    {
                        "photo_uuid": photo_uuid,
                        "unit_code": "YNLQ-001-01-001",
                        "process_name": "",
                        "title": "模板验收",
                        "photo_date": "2026-08-25",
                    }
                ]
            },
            headers=self._headers(self.token_a),
        )
        self.assertEqual(assigned.status_code, 200, assigned.get_json())

        backfill_uuid = str(uuid.uuid4())
        content = self._jpeg((30, 45, 60))
        backfilled = self.client.post(
            "/api/desktop/v1/backfill-photo",
            data={
                "file": (io.BytesIO(content), "电脑查看副本.jpg"),
                "photo_uuid": backfill_uuid,
                "project_id": "default",
                "scope": "engineering",
                "category": "supervision",
                "unit_code": "YNLQ-001-01-001",
                "process_name": "",
                "title": "监理检查",
                "photo_date": "2026-08-24",
                "sha256": hashlib.sha256(content).hexdigest(),
                "desktop_machine_id": "MACHINE-A",
            },
            headers=self._headers(self.desktop_token_a),
            content_type="multipart/form-data",
        )
        self.assertEqual(backfilled.status_code, 201, backfilled.get_json())
        self.assertEqual(backfilled.get_json()["photo"]["status"], "desktop_imported")
        self.assertEqual(backfilled.get_json()["photo"]["source"], "desktop")
        conn = self.db.connect()
        try:
            backfill_row = conn.execute(
                "SELECT * FROM cloud_photos WHERE photo_uuid = ?", (backfill_uuid,)
            ).fetchone()
            self.assertEqual(backfill_row["original_storage_key"], "")
            self.assertEqual(backfill_row["original_cleanup_status"], "not_applicable")
            self.assertLessEqual(backfill_row["preview_size_bytes"], 102400)
        finally:
            conn.close()

        oversized_stream = io.BytesIO()
        # 只需略大于 100KB；保持在 Werkzeug 内存构造阈值下，
        # 避免测试请求构造器的临时文件干扰 ResourceWarning 审计。
        Image.effect_noise((400, 400), 100).convert("RGB").save(
            oversized_stream, "JPEG", quality=95
        )
        oversized_preview = oversized_stream.getvalue()
        self.assertGreater(len(oversized_preview), 102400)
        rejected_backfill = self.client.post(
            "/api/desktop/v1/backfill-photo",
            data={
                "file": (io.BytesIO(oversized_preview), "过大查看副本.jpg"),
                "photo_uuid": str(uuid.uuid4()),
                "project_id": "default",
                "scope": "engineering",
                "category": "supervision",
                "unit_code": "YNLQ-001-01-001",
                "sha256": hashlib.sha256(oversized_preview).hexdigest(),
                "desktop_machine_id": "MACHINE-A",
            },
            headers=self._headers(self.desktop_token_a),
            content_type="multipart/form-data",
        )
        self.assertEqual(rejected_backfill.status_code, 413)
        self.assertEqual(rejected_backfill.get_json()["code"], "preview_too_large")
        rejected_backfill.close()

    def test_shared_match_confidence_and_ocr_failure_degrades_to_review(self):
        from server import mobile_recognition

        candidates = [
            {
                "unit_code": "YNLQ-001-01-001",
                "project_code": "LOCAL-001",
                "display_project_code": "YNLQ-001-01-001",
                "project_name": "左岸连接堤",
                "source_fields": {
                    "单元工程编码": "YNLQ-001-01-001",
                    "单元工程名称": "左岸连接堤",
                    "分部工程名称": "左岸连接工程",
                    "单位工程名称": "龙泉河单位工程",
                    "合同工程名称": "洺河龙泉缓洪工程",
                },
            }
        ]
        high = mobile_recognition.match_photo(
            ocr_fields={"construction_area": "左岸连接堤"}, candidates=candidates
        )
        low = mobile_recognition.match_photo(
            ocr_fields={"construction_content": "左岸连接堤"}, candidates=candidates
        )
        self.assertEqual(high["confidence"], "high")
        self.assertEqual(high["score"], 980)
        self.assertEqual(low["confidence"], "low")
        self.assertEqual(low["score"], 360)

        batch_id = self._create_batch(self.token_a, mode="auto")
        photo_uuid = str(uuid.uuid4())
        self._upload(
            self.token_a, batch_id, photo_uuid, self._jpeg((100, 100, 100))
        )
        with patch(
            "server.mobile_recognition.recognize_watermark",
            side_effect=RuntimeError("mock ocr failure"),
        ):
            _, response = self._analyze_and_wait(self.token_a, batch_id)
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["job"]["status"], "failed")
        self.assertGreater(response.get_json()["job"]["result"]["failed_count"], 0)
        photo = response.get_json()["batch"]["photos"][0]
        self.assertEqual(photo["status"], "needs_review")
        self.assertEqual(photo["error"]["code"], "analysis_failed")
        self.assertEqual(photo["match"]["confidence"], "low")

    def test_chunked_upload_is_resumable_isolated_and_preserves_original(self):
        from server import config

        batch_id = self._create_batch(self.token_a)
        photo_uuid = str(uuid.uuid4())
        original = self._png((18, 88, 126, 190), size=(640, 480))
        chunk_size = 1024
        parts = [
            original[index : index + chunk_size]
            for index in range(0, len(original), chunk_size)
        ]
        with patch.object(config, "MOBILE_CHUNK_BYTES", chunk_size):
            initialized = self._chunk_init(
                self.token_a,
                batch_id,
                photo_uuid,
                original,
                chunk_size=chunk_size,
                filename=r"D:\DCIM\闸门原图.png",
            )
            self.assertEqual(initialized.status_code, 201, initialized.get_json())
            upload_id = initialized.get_json()["upload"]["upload_id"]
            retry_init = self._chunk_init(
                self.token_a,
                batch_id,
                photo_uuid,
                original,
                chunk_size=chunk_size,
                filename=r"D:\DCIM\闸门原图.png",
            )
        self.assertEqual(retry_init.status_code, 200, retry_init.get_json())
        self.assertTrue(retry_init.get_json()["idempotent"])

        cross_tenant = self.client.get(
            f"/api/mobile/v1/batches/{batch_id}/chunked-uploads/{photo_uuid}",
            headers=self._headers(self.token_b),
        )
        self.assertEqual(cross_tenant.status_code, 404)
        cross_tenant_put = self._put_chunk(
            self.token_b, batch_id, photo_uuid, 0, parts[0]
        )
        self.assertEqual(cross_tenant_put.status_code, 404)

        conflicting_batch = self._create_batch(self.token_a)
        with patch.object(config, "MOBILE_CHUNK_BYTES", chunk_size):
            conflicting_context = self._chunk_init(
                self.token_a,
                conflicting_batch,
                photo_uuid,
                original,
                chunk_size=chunk_size,
                filename=r"D:\DCIM\闸门原图.png",
            )
        self.assertEqual(conflicting_context.status_code, 409)
        self.assertEqual(
            conflicting_context.get_json()["code"], "photo_uuid_conflict"
        )

        for index in reversed(range(len(parts))):
            uploaded = self._put_chunk(
                self.token_a, batch_id, photo_uuid, index, parts[index]
            )
            self.assertEqual(uploaded.status_code, 201, uploaded.get_json())
        duplicate = self._put_chunk(
            self.token_a, batch_id, photo_uuid, 0, parts[0]
        )
        self.assertEqual(duplicate.status_code, 200, duplicate.get_json())
        self.assertTrue(duplicate.get_json()["idempotent"])
        different = bytearray(parts[0])
        different[0] ^= 0x01
        conflict = self._put_chunk(
            self.token_a, batch_id, photo_uuid, 0, bytes(different)
        )
        self.assertEqual(conflict.status_code, 409, conflict.get_json())
        self.assertEqual(conflict.get_json()["code"], "chunk_conflict")

        resumed = self.client.get(
            f"/api/mobile/v1/batches/{batch_id}/chunked-uploads/{photo_uuid}",
            headers=self._headers(self.token_a),
        )
        self.assertEqual(
            resumed.get_json()["upload"]["uploaded_chunks"],
            list(range(len(parts))),
        )
        blocked_commit = self.client.post(
            f"/api/mobile/v1/batches/{batch_id}/commit",
            headers=self._headers(self.token_a),
        )
        self.assertEqual(blocked_commit.status_code, 409, blocked_commit.get_json())
        self.assertEqual(
            blocked_commit.get_json()["code"], "batch_uploads_incomplete"
        )

        finalized = self.client.post(
            f"/api/mobile/v1/batches/{batch_id}/chunked-uploads/"
            f"{photo_uuid}/finalize",
            json={
                "sha256": hashlib.sha256(original).hexdigest(),
                "original_size_bytes": len(original),
                "total_chunks": len(parts),
            },
            headers=self._headers(self.token_a),
        )
        self.assertEqual(finalized.status_code, 201, finalized.get_json())
        photo = finalized.get_json()["photo"]
        self.assertLessEqual(photo["preview_size_bytes"], 102400)
        self.assertNotIn("original", photo["download_url"])
        self.assertEqual(finalized.get_json()["upload"]["status"], "completed")
        finalized_again = self.client.post(
            f"/api/mobile/v1/batches/{batch_id}/chunked-uploads/"
            f"{photo_uuid}/finalize",
            json={
                "sha256": hashlib.sha256(original).hexdigest(),
                "original_size_bytes": len(original),
                "total_chunks": len(parts),
            },
            headers=self._headers(self.token_a),
        )
        self.assertEqual(finalized_again.status_code, 200, finalized_again.get_json())
        self.assertTrue(finalized_again.get_json()["idempotent"])

        committed = self.client.post(
            f"/api/mobile/v1/batches/{batch_id}/commit",
            headers=self._headers(self.token_a),
        )
        self.assertEqual(committed.status_code, 200, committed.get_json())
        inbox = self.client.get(
            "/api/desktop/v1/inbox?limit=100&desktop_machine_id=MACHINE-A",
            headers=self._headers(self.desktop_token_a),
        ).get_json()["items"]
        item = next(entry for entry in inbox if entry["photo_uuid"] == photo_uuid)
        self.assertEqual(item["original_filename"], "闸门原图.png")
        self.assertEqual(item["original_mime_type"], "image/png")
        downloaded = self.client.get(
            item["original_download_url"], headers=self._headers(self.desktop_token_a)
        )
        self.assertEqual(downloaded.data, original)
        downloaded.close()
        conn = self.db.connect()
        try:
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM mobile_upload_chunks WHERE session_id = ?",
                    (upload_id,),
                ).fetchone()[0],
                0,
            )
        finally:
            conn.close()
        self.assertFalse(
            (Path(config.MOBILE_CHUNK_DIR) / str(self._account_id("tenant_a")) / str(upload_id)).exists()
        )

    def test_chunked_upload_hash_failure_quota_expiry_and_abort(self):
        from server import config

        chunk_size = 1024
        original = self._jpeg((42, 72, 92), size=(640, 480))
        batch_id = self._create_batch(self.token_a)
        photo_uuid = str(uuid.uuid4())
        wrong_final_sha = "0" * 64
        with patch.object(config, "MOBILE_CHUNK_BYTES", chunk_size):
            initialized = self._chunk_init(
                self.token_a,
                batch_id,
                photo_uuid,
                original,
                chunk_size=chunk_size,
                sha=wrong_final_sha,
            )
        self.assertEqual(initialized.status_code, 201, initialized.get_json())
        parts = [
            original[index : index + chunk_size]
            for index in range(0, len(original), chunk_size)
        ]
        for index, part in enumerate(parts):
            self.assertEqual(
                self._put_chunk(
                    self.token_a, batch_id, photo_uuid, index, part
                ).status_code,
                201,
            )
        failed = self.client.post(
            f"/api/mobile/v1/batches/{batch_id}/chunked-uploads/"
            f"{photo_uuid}/finalize",
            json={
                "sha256": wrong_final_sha,
                "original_size_bytes": len(original),
                "total_chunks": len(parts),
            },
            headers=self._headers(self.token_a),
        )
        self.assertEqual(failed.status_code, 422, failed.get_json())
        self.assertEqual(failed.get_json()["code"], "sha256_mismatch")
        status = self.client.get(
            f"/api/mobile/v1/batches/{batch_id}/chunked-uploads/{photo_uuid}",
            headers=self._headers(self.token_a),
        ).get_json()["upload"]
        self.assertEqual(status["status"], "failed")
        self.assertEqual(status["uploaded_chunks"], [])

        with patch.object(config, "MOBILE_MAX_ORIGINAL_BYTES", 100), patch.object(
            config, "MOBILE_CHUNK_BYTES", 50
        ):
            too_large = self.client.post(
                f"/api/mobile/v1/batches/{batch_id}/chunked-uploads/init",
                json={
                    "photo_uuid": str(uuid.uuid4()),
                    "sha256": hashlib.sha256(b"x" * 101).hexdigest(),
                    "original_size_bytes": 101,
                    "original_filename": "large.jpg",
                    "chunk_size_bytes": 50,
                    "total_chunks": 3,
                    "orientation": 1,
                },
                headers=self._headers(self.token_a),
            )
        self.assertEqual(too_large.status_code, 413, too_large.get_json())

        quota_batch = self._create_batch(self.token_a)
        first_uuid = str(uuid.uuid4())
        second_uuid = str(uuid.uuid4())
        with patch.object(config, "MOBILE_CHUNK_BYTES", chunk_size), patch.object(
            config, "MOBILE_CHUNK_MAX_ACTIVE_PER_ACCOUNT", 1
        ):
            first = self._chunk_init(
                self.token_a,
                quota_batch,
                first_uuid,
                original,
                chunk_size=chunk_size,
            )
            self.assertEqual(first.status_code, 201, first.get_json())
            rejected = self._chunk_init(
                self.token_a,
                quota_batch,
                second_uuid,
                original,
                chunk_size=chunk_size,
            )
            self.assertEqual(rejected.status_code, 429, rejected.get_json())
            conn = self.db.connect()
            try:
                conn.execute(
                    "UPDATE mobile_upload_sessions SET expires_at = '2000-01-01T00:00:00Z' "
                    "WHERE account_id = ? AND photo_uuid = ?",
                    (self._account_id("tenant_a"), first_uuid),
                )
                conn.commit()
            finally:
                conn.close()
            after_expiry = self._chunk_init(
                self.token_a,
                quota_batch,
                second_uuid,
                original,
                chunk_size=chunk_size,
            )
        self.assertEqual(after_expiry.status_code, 201, after_expiry.get_json())
        aborted = self.client.post(
            f"/api/mobile/v1/batches/{quota_batch}/chunked-uploads/"
            f"{second_uuid}/abort",
            headers=self._headers(self.token_a),
        )
        self.assertEqual(aborted.status_code, 200, aborted.get_json())
        aborted_again = self.client.post(
            f"/api/mobile/v1/batches/{quota_batch}/chunked-uploads/"
            f"{second_uuid}/abort",
            headers=self._headers(self.token_a),
        )
        self.assertTrue(aborted_again.get_json()["idempotent"])

    def test_chunk_cleanup_failure_is_persisted_retried_and_counts_quota(self):
        from server import config
        from server.mobile_chunks import ChunkFileError, ChunkFileStore

        chunk_size = 1024
        original = self._jpeg((91, 71, 51), size=(640, 480))
        batch_id = self._create_batch(self.token_a)
        photo_uuid = str(uuid.uuid4())
        blocked_uuid = str(uuid.uuid4())
        with patch.object(config, "MOBILE_CHUNK_BYTES", chunk_size):
            initialized = self._chunk_init(
                self.token_a,
                batch_id,
                photo_uuid,
                original,
                chunk_size=chunk_size,
            )
            self.assertEqual(initialized.status_code, 201, initialized.get_json())
            upload_id = initialized.get_json()["upload"]["upload_id"]
            first_part = original[:chunk_size]
            uploaded = self._put_chunk(
                self.token_a, batch_id, photo_uuid, 0, first_part
            )
            self.assertEqual(uploaded.status_code, 201, uploaded.get_json())

            with patch.object(
                ChunkFileStore,
                "cleanup",
                side_effect=ChunkFileError("mock chunk cleanup outage"),
            ), patch.object(config, "MOBILE_CHUNK_MAX_ACTIVE_PER_ACCOUNT", 1):
                aborted = self.client.post(
                    f"/api/mobile/v1/batches/{batch_id}/chunked-uploads/"
                    f"{photo_uuid}/abort",
                    headers=self._headers(self.token_a),
                )
                self.assertEqual(aborted.status_code, 200, aborted.get_json())
                self.assertEqual(
                    aborted.get_json()["upload"]["cleanup_status"], "pending"
                )
                self.assertIn(
                    "mock chunk cleanup outage",
                    aborted.get_json()["upload"]["cleanup_error"],
                )
                blocked = self._chunk_init(
                    self.token_a,
                    batch_id,
                    blocked_uuid,
                    original,
                    chunk_size=chunk_size,
                )
                self.assertEqual(blocked.status_code, 429, blocked.get_json())
                self.assertEqual(blocked.get_json()["code"], "chunk_quota_exceeded")

            # 下一次状态查询会触发持久 pending 清扫；清理成功后不再占配额。
            cleaned = self.client.get(
                f"/api/mobile/v1/batches/{batch_id}/chunked-uploads/{photo_uuid}",
                headers=self._headers(self.token_a),
            )
            self.assertEqual(cleaned.status_code, 200, cleaned.get_json())
            self.assertEqual(
                cleaned.get_json()["upload"]["cleanup_status"], "cleaned"
            )
            with patch.object(config, "MOBILE_CHUNK_MAX_ACTIVE_PER_ACCOUNT", 1):
                admitted = self._chunk_init(
                    self.token_a,
                    batch_id,
                    blocked_uuid,
                    original,
                    chunk_size=chunk_size,
                )
            self.assertEqual(admitted.status_code, 201, admitted.get_json())
            self.client.post(
                f"/api/mobile/v1/batches/{batch_id}/chunked-uploads/"
                f"{blocked_uuid}/abort",
                headers=self._headers(self.token_a),
            )

        conn = self.db.connect()
        try:
            row = conn.execute(
                "SELECT cleanup_status, cleanup_error FROM mobile_upload_sessions "
                "WHERE id = ?",
                (upload_id,),
            ).fetchone()
            self.assertEqual(row["cleanup_status"], "cleaned")
            self.assertEqual(row["cleanup_error"], "")
        finally:
            conn.close()
        session_dir = (
            Path(config.MOBILE_CHUNK_DIR)
            / str(self._account_id("tenant_a"))
            / str(upload_id)
        )
        self.assertFalse(session_dir.exists())

    def test_missing_chunk_file_fails_finalize_without_sticking_finalizing(self):
        from server import config

        chunk_size = 1024
        original = self._jpeg((31, 61, 91), size=(640, 480))
        batch_id = self._create_batch(self.token_a)
        photo_uuid = str(uuid.uuid4())
        with patch.object(config, "MOBILE_CHUNK_BYTES", chunk_size):
            initialized = self._chunk_init(
                self.token_a,
                batch_id,
                photo_uuid,
                original,
                chunk_size=chunk_size,
            )
            self.assertEqual(initialized.status_code, 201, initialized.get_json())
            upload_id = initialized.get_json()["upload"]["upload_id"]
            parts = [
                original[index : index + chunk_size]
                for index in range(0, len(original), chunk_size)
            ]
            for index, part in enumerate(parts):
                self.assertEqual(
                    self._put_chunk(
                        self.token_a, batch_id, photo_uuid, index, part
                    ).status_code,
                    201,
                )
            missing_path = (
                Path(config.MOBILE_CHUNK_DIR)
                / str(self._account_id("tenant_a"))
                / str(upload_id)
                / "000000.part"
            )
            missing_path.unlink()
            finalized = self.client.post(
                f"/api/mobile/v1/batches/{batch_id}/chunked-uploads/"
                f"{photo_uuid}/finalize",
                json={
                    "sha256": hashlib.sha256(original).hexdigest(),
                    "original_size_bytes": len(original),
                    "total_chunks": len(parts),
                },
                headers=self._headers(self.token_a),
            )
        self.assertEqual(finalized.status_code, 422, finalized.get_json())
        self.assertEqual(finalized.get_json()["code"], "chunk_assembly_failed")
        state = self.client.get(
            f"/api/mobile/v1/batches/{batch_id}/chunked-uploads/{photo_uuid}",
            headers=self._headers(self.token_a),
        ).get_json()["upload"]
        self.assertEqual(state["status"], "failed")
        self.assertNotEqual(state["status"], "finalizing")

    def test_analysis_heartbeat_protects_one_slow_photo_from_stale_recovery(self):
        from server import config

        started = threading.Event()
        release = threading.Event()

        def slow_recognition(_image_bytes, strict=True):
            started.set()
            release.wait(5)
            return {
                "construction_area": "左岸连接堤",
                "watermark_text": "施工区域：左岸连接堤",
            }

        batch_id = self._create_batch(self.token_a, mode="auto")
        self._upload(
            self.token_a, batch_id, str(uuid.uuid4()), self._jpeg((19, 39, 59))
        )
        terminal = None
        try:
            with patch.object(
                config, "MOBILE_ANALYSIS_STALE_SECONDS", 1
            ), patch(
                "server.mobile_recognition.recognize_watermark",
                side_effect=slow_recognition,
            ):
                accepted = self.client.post(
                    f"/api/mobile/v1/batches/{batch_id}/analyze",
                    headers=self._headers(self.token_a),
                )
                self.assertEqual(accepted.status_code, 202, accepted.get_json())
                self.assertTrue(started.wait(1))
                job_id = accepted.get_json()["job"]["job_id"]
                time.sleep(1.4)
                while_running = self.client.get(
                    f"/api/mobile/v1/batches/{batch_id}",
                    headers=self._headers(self.token_a),
                )
                self.assertEqual(while_running.status_code, 200)
                self.assertEqual(
                    while_running.get_json()["batch"]["status"],
                    "analyzing",
                    while_running.get_json(),
                )
                release.set()
                for _ in range(300):
                    terminal = self.client.get(
                        f"/api/mobile/v1/jobs/{job_id}",
                        headers=self._headers(self.token_a),
                    )
                    if terminal.get_json()["job"]["status"] in {
                        "completed",
                        "failed",
                    }:
                        break
                    time.sleep(0.01)
        finally:
            release.set()
        self.assertIsNotNone(terminal)
        self.assertEqual(terminal.get_json()["job"]["status"], "completed")

    def test_async_analysis_is_idempotent_and_recovers_stale_job(self):
        started = threading.Event()
        release = threading.Event()

        def delayed_recognition(_image_bytes, strict=True):
            started.set()
            release.wait(3)
            return {
                "construction_area": "左岸连接堤",
                "watermark_text": "施工区域：左岸连接堤",
            }

        batch_id = self._create_batch(self.token_a, mode="auto")
        self._upload(
            self.token_a, batch_id, str(uuid.uuid4()), self._jpeg((17, 27, 37))
        )
        with patch(
            "server.mobile_recognition.recognize_watermark",
            side_effect=delayed_recognition,
        ):
            first = self.client.post(
                f"/api/mobile/v1/batches/{batch_id}/analyze",
                headers=self._headers(self.token_a),
            )
            self.assertEqual(first.status_code, 202, first.get_json())
            self.assertTrue(started.wait(1))
            second = self.client.post(
                f"/api/mobile/v1/batches/{batch_id}/analyze",
                headers=self._headers(self.token_a),
            )
            self.assertEqual(second.status_code, 202, second.get_json())
            self.assertTrue(second.get_json()["idempotent"])
            self.assertEqual(
                first.get_json()["job"]["job_id"],
                second.get_json()["job"]["job_id"],
            )
            release.set()
            job_id = first.get_json()["job"]["job_id"]
            for _ in range(200):
                terminal = self.client.get(
                    f"/api/mobile/v1/jobs/{job_id}",
                    headers=self._headers(self.token_a),
                )
                if terminal.get_json()["job"]["status"] in {"completed", "failed"}:
                    break
                time.sleep(0.01)
        self.assertEqual(terminal.get_json()["job"]["status"], "completed")
        hidden_job = self.client.get(
            f"/api/mobile/v1/jobs/{job_id}", headers=self._headers(self.token_b)
        )
        self.assertEqual(hidden_job.status_code, 404)
        conn = self.db.connect()
        try:
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM mobile_jobs WHERE account_id = ? AND batch_id = ?",
                    (self._account_id("tenant_a"), batch_id),
                ).fetchone()[0],
                1,
            )
        finally:
            conn.close()

        stale_batch = self._create_batch(self.token_a, mode="auto")
        self._upload(
            self.token_a,
            stale_batch,
            str(uuid.uuid4()),
            self._jpeg((47, 57, 67)),
        )
        conn = self.db.connect()
        try:
            account_id = self._account_id("tenant_a")
            conn.execute(
                "UPDATE mobile_batches SET status = 'analyzing' WHERE id = ? AND account_id = ?",
                (stale_batch, account_id),
            )
            conn.execute(
                "UPDATE cloud_photos SET status = 'analyzing' WHERE batch_id = ? AND account_id = ?",
                (stale_batch, account_id),
            )
            cur = conn.execute(
                "INSERT INTO mobile_jobs (account_id, batch_id, job_type, status, created_at, updated_at) "
                "VALUES (?, ?, 'analyze', 'running', '2000-01-01T00:00:00Z', "
                "'2000-01-01T00:00:00Z')",
                (account_id, stale_batch),
            )
            stale_job_id = cur.lastrowid
            conn.commit()
        finally:
            conn.close()
        recovered = self.client.get(
            f"/api/mobile/v1/batches/{stale_batch}",
            headers=self._headers(self.token_a),
        )
        self.assertEqual(recovered.status_code, 200, recovered.get_json())
        self.assertEqual(recovered.get_json()["batch"]["status"], "needs_review")
        stale_job = self.client.get(
            f"/api/mobile/v1/jobs/{stale_job_id}",
            headers=self._headers(self.token_a),
        ).get_json()["job"]
        self.assertEqual(stale_job["status"], "failed")
        self.assertEqual(stale_job["error"]["code"], "analysis_interrupted")

        # 即使 job 刚进入 running（未达到运行期 stale 阈值），新进程启动时也
        # 必须把旧进程遗留状态立即转人工；客户端只轮询 batch 也不会永久卡住。
        restart_batch = self._create_batch(self.token_a, mode="auto")
        self._upload(
            self.token_a,
            restart_batch,
            str(uuid.uuid4()),
            self._jpeg((77, 87, 97)),
        )
        conn = self.db.connect()
        try:
            account_id = self._account_id("tenant_a")
            fresh_timestamp = "2099-01-01T00:00:00Z"
            conn.execute(
                "UPDATE mobile_batches SET status = 'analyzing', updated_at = ? "
                "WHERE id = ? AND account_id = ?",
                (fresh_timestamp, restart_batch, account_id),
            )
            conn.execute(
                "UPDATE cloud_photos SET status = 'analyzing', updated_at = ? "
                "WHERE batch_id = ? AND account_id = ?",
                (fresh_timestamp, restart_batch, account_id),
            )
            cur = conn.execute(
                "INSERT INTO mobile_jobs (account_id, batch_id, job_type, status, "
                "created_at, updated_at) VALUES (?, ?, 'analyze', 'running', ?, ?)",
                (account_id, restart_batch, fresh_timestamp, fresh_timestamp),
            )
            restart_job_id = cur.lastrowid
            conn.commit()
        finally:
            conn.close()
        from server import app as server_app

        restarted_app = server_app.create_app()
        restarted_app.config["TESTING"] = True
        with restarted_app.test_client() as restarted_client:
            batch_after_restart = restarted_client.get(
                f"/api/mobile/v1/batches/{restart_batch}",
                headers=self._headers(self.token_a),
            )
            self.assertEqual(batch_after_restart.status_code, 200)
            self.assertEqual(
                batch_after_restart.get_json()["batch"]["status"], "needs_review"
            )
            job_after_restart = restarted_client.get(
                f"/api/mobile/v1/jobs/{restart_job_id}",
                headers=self._headers(self.token_a),
            )
            self.assertEqual(
                job_after_restart.get_json()["job"]["error"]["code"],
                "analysis_interrupted",
            )

    def test_deployment_templates_are_complete_and_staging_is_isolated(self):
        root = Path(__file__).resolve().parents[1]
        deploy_auth = (root / "deploy_auth.py").read_text(encoding="utf-8")
        ast.parse(deploy_auth)
        for filename in (
            "mobile_api.py",
            "mobile_storage.py",
            "mobile_recognition.py",
            "mobile_chunks.py",
        ):
            self.assertIn(filename, deploy_auth)
        self.assertIn("pip install", deploy_auth)
        self.assertIn("/api/mobile/v1/projects", deploy_auth)
        self.assertIn("BACKUP_LIVE_DB_SCRIPT", deploy_auth)
        self.assertIn("source_connection.backup", deploy_auth)
        self.assertIn("validate_mobile_migration.py", deploy_auth)
        self.assertIn("--expected-accounts", deploy_auth)
        self.assertLess(
            deploy_auth.index("validation_result = ssh("),
            deploy_auth.index("replacement = ssh("),
        )

        production_dropin = (
            root / "server" / "deploy" / "album-auth-mobile-v1.conf"
        ).read_text(encoding="utf-8")
        self.assertIn("ExecStart=\n", production_dropin)
        self.assertIn("-w 1 --threads 4", production_dropin)
        self.assertNotIn("\nEnvironment=", production_dropin)
        self.assertIn(
            "EnvironmentFile=-/etc/album-auth/mobile.env",
            production_dropin,
        )
        self.assertNotIn("\nEnvironment=", production_dropin)

        deploy_sh = (root / "server" / "deploy" / "deploy.sh").read_text(encoding="utf-8")
        self.assertIn('CODE_DIR="$APP_DIR/server"', deploy_sh)
        self.assertIn('"$SERVER_SRC/" "$STAGE_DIR/server/"', deploy_sh)
        self.assertIn('"$STAGE_DIR/server/requirements.txt"', deploy_sh)
        self.assertIn("trap rollback ERR", deploy_sh)
        self.assertIn("PRAGMA quick_check;", deploy_sh)
        self.assertIn("server/mobile_api.py", deploy_sh)
        self.assertIn("/api/mobile/v1/projects", deploy_sh)

        production_service = (
            root / "server" / "deploy" / "album-auth.service"
        ).read_text(encoding="utf-8")
        self.assertIn("-w 1 --threads 4", production_service)
        self.assertIn("--timeout 300", production_service)
        self.assertNotIn("-w 2", production_service)
        self.assertIn("EnvironmentFile=-/etc/album-auth/mobile.env", production_service)

        staging_script = (
            root / "server" / "deploy" / "deploy-staging.sh"
        ).read_text(encoding="utf-8")
        staging_service = (
            root / "server" / "deploy" / "album-auth-staging.service"
        ).read_text(encoding="utf-8")
        self.assertIn("SERVICE_NAME=album-auth-staging", staging_script)
        self.assertIn("/opt/album-auth-staging", staging_script)
        self.assertIn("/var/lib/album-auth-staging", staging_script)
        self.assertIn("staging.db", staging_service)
        self.assertIn("127.0.0.1:18080", staging_service)
        self.assertIn("ALBUM_MOBILE_STORAGE_BACKEND=local", staging_service)
        self.assertIn("ALBUM_MOBILE_CHUNK_DIR=/var/lib/album-auth-staging/mobile_chunks", staging_service)
        self.assertIn('CHUNK_DIR="$DATA_DIR/mobile_chunks"', staging_script)
        self.assertIn("-name '*.py' -print0", staging_script)
        self.assertIn('-m py_compile "${python_modules[@]}"', staging_script)
        self.assertIn("-w 1 --threads 4 --timeout 300", staging_service)
        self.assertIn("--timeout 300", production_dropin)

        nginx = (root / "server" / "deploy" / "nginx-domain.conf").read_text(encoding="utf-8")
        self.assertIn("api.shuiliyingxiang.cn", nginx)
        self.assertIn("listen 443 ssl", nginx)
        self.assertIn("client_max_body_size 52m", nginx)
        self.assertIn("client_body_timeout 240s", nginx)
        self.assertNotIn("client_max_body_size 1m", nginx)
        self.assertIn("proxy_pass http://127.0.0.1:8000", nginx)
        self.assertIn("proxy_connect_timeout 240s", nginx)
        self.assertIn("proxy_read_timeout 240s", nginx)
        self.assertIn("proxy_send_timeout 240s", nginx)
        for nginx_name in ("nginx-staging.conf", "nginx-bootstrap.conf"):
            nginx_template = (
                root / "server" / "deploy" / nginx_name
            ).read_text(encoding="utf-8")
            self.assertIn("client_max_body_size 52m", nginx_template)
            self.assertIn("client_body_timeout 240s", nginx_template)
            self.assertIn("proxy_connect_timeout 240s", nginx_template)
            self.assertIn("proxy_read_timeout 240s", nginx_template)
            self.assertIn("proxy_send_timeout 240s", nginx_template)

        cloud_template = (
            root / "server" / "templates" / "cloud.html"
        ).read_text(encoding="utf-8")
        self.assertIn("手机原图仅短期中转到绑定电脑", cloud_template)
        self.assertIn("电脑确认归档后服务器删除原图", cloud_template)
        self.assertNotIn("平台只同步缩略图，不上传工程原图", cloud_template)


if __name__ == "__main__":
    unittest.main()
