"""公路原码可局部重复；云端和桌面必须使用完整父路径内部身份。"""
from __future__ import annotations

import hashlib
import io
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

# app 首次导入也只能落在隔离位置；已经加载时绝不重载或覆盖其他测试配置。
_initial_dir = tempfile.TemporaryDirectory(prefix="highway-identity-module-")
_previous_env = os.environ.get("ALBUM_DATA_DIR")
os.environ.setdefault("ALBUM_DATA_DIR", _initial_dir.name)
try:
    import app as desktop
finally:
    if _previous_env is None:
        os.environ.pop("ALBUM_DATA_DIR", None)
    else:
        os.environ["ALBUM_DATA_DIR"] = _previous_env

import mobile_sync
import highway_rules
if __package__:
    from . import test_municipal_mobile_backfill as support
else:
    import test_municipal_mobile_backfill as support


class LiveCloud(support.ServerCloud):
    def desktop_inbox(self, cursor="", limit=50, desktop_machine_id=""):
        return self.result(self.client.get("/api/desktop/v1/inbox", query_string={
            "cursor": cursor, "limit": limit, "desktop_machine_id": desktop_machine_id,
        }, headers=self.headers))

    def desktop_download_bytes(self, url, max_bytes=50 * 1024 * 1024):
        parsed = urlsplit(url)
        response = self.client.get(parsed.path + ("?" + parsed.query if parsed.query else ""), headers=self.headers)
        try:
            if response.status_code != 200:
                return {"ok": False, "error": str(response.get_json()), "http_status": response.status_code}
            if len(response.data) > max_bytes:
                return {"ok": False, "error": "too large"}
            return {"ok": True, "data": response.data}
        finally:
            response.close()

    def desktop_ack_photo(self, photo_uuid, local_project_code, local_photo_id, desktop_machine_id=""):
        return self.result(self.client.post(f"/api/desktop/v1/photos/{photo_uuid}/ack", json={
            "local_project_code": local_project_code, "local_photo_id": local_photo_id,
            "desktop_machine_id": desktop_machine_id,
        }, headers=self.headers))


class HighwayScopedIdentityTests(unittest.TestCase):
    def setUp(self):
        # Reuse the proven real HTTP server/license fixture, not its fake desktop manager.
        support.MunicipalDesktopRoundtripTest.setUp(self)
        self.cloud = LiveCloud(self.client, self.cloud.headers["Authorization"][7:], self.account_id)
        self.project = {
            "id": "highway-scoped", "project_code": "GL", "project_name": "公路路径试验",
            "industry": "公路工程", "project_type": "公路综合土建", "rule_version": highway_rules.RULE_VERSION,
            "cloud_owner_id": str(self.account_id),
        }
        saved = {p: p.read_bytes() if p.exists() else None for p in (
            desktop.ENGINEERING_PROJECTS_PATH, desktop.PROJECT_INFO_PATH, desktop.ENGINEERING_SETTINGS_PATH)}
        def restore():
            for path, content in saved.items():
                if content is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_bytes(content)
            desktop._ENGINEERING_READ_CACHE.update(sig=None, data=None)
            desktop.manager.invalidate_projects_cache()
        self.addCleanup(restore)
        self.patch_project = patch.object(desktop, "current_engineering_project", lambda *args, **kwargs: dict(self.project))
        self.patch_project.start()
        self.addCleanup(self.patch_project.stop)
        self.manager = desktop.AlbumManager(self.root / "highway-albums")
        # 同一分项原码贯穿不同分部、单位、合同，子分部原码也重复。
        self.rows = []
        for contract, unit, part, sub in (("第一合同段", "01", "01", ""),
                                         ("第一合同段", "01", "02", ""),
                                         ("第一合同段", "02", "01", ""),
                                         ("第二合同段", "01", "01", ""),
                                         ("第二合同段", "01", "02", "Z01"),
                                         ("第二合同段", "02", "02", "Z01")):
            self.rows.append({
                "合同或标段名称": contract, "单位工程编码": unit, "单位工程名称": "路基工程" + unit,
                "分部工程编码": part, "分部工程名称": "分部" + part,
                "子分部工程编码": sub, "子分部工程名称": "批准子分部" if sub else "",
                "划分依据": "批准划分表" if sub else "", "分项工程编码": "001", "分项工程名称": "土方路基",
            })
        imported = self.manager.import_projects_from_records(self.rows)
        self.assertEqual(imported["created"], len(self.rows))
        self.codes = [highway_rules.storage_code(row, self.project["id"]) for row in self.rows]
        self.assertEqual({p["project_code"] for p in self.manager.list_projects()}, set(self.codes))
        self.service = mobile_sync.DesktopMobileSync(
            self.manager, self.cloud, lambda: dict(self.project), lambda: {"nodes": []},
            self.root / "highway-state.json", self.root / "highway-cache", machine_id_reader=lambda: "MACHINE-A",
        )
        result = self.service._sync_snapshot()
        self.assertTrue(result.get("ok"), result)

    def nodes(self):
        response = self.client.get("/api/mobile/v1/projects/highway-scoped/tree", headers=self.user_headers)
        self.assertEqual(response.status_code, 200, response.get_json())
        result = []
        def visit(nodes):
            for node in nodes:
                result.append(node)
                visit(node.get("children", []))
        visit(response.get_json()["tree"])
        return result

    def test_server_tree_has_unique_parent_and_leaf_ids_with_original_display_codes(self):
        nodes = self.nodes()
        self.assertEqual(len({n["code"] for n in nodes}), len(nodes))
        leaves = [n for n in nodes if n["code"] in self.codes]
        self.assertEqual(len(leaves), len(self.rows))
        self.assertEqual({n["display_code"] for n in leaves}, {"001"})
        self.assertEqual(len({n["parent_code"] for n in leaves}), len(self.rows))
        # 同原单位、分部、子分部编码也必须保持独立父级，不靠中文名称去消除冲突。
        for raw in ("01", "02", "Z01"):
            matching = [n for n in nodes if n.get("display_code") == raw]
            self.assertGreaterEqual(len(matching), 2)
            self.assertEqual(len({n["code"] for n in matching}), len(matching))

    def test_raw_item_code_is_rejected_not_first_matched(self):
        response = self.client.post("/api/mobile/v1/batches", json={
            "client_batch_id": str(uuid.uuid4()), "project_id": self.project["id"],
            "scope": "engineering", "category": "construction", "mode": "direct", "assignment": {"item_code": "001"},
        }, headers=self.user_headers)
        self.assertEqual(response.status_code, 404, response.get_json())
        with self.assertRaises(ValueError):
            self.service._resolve_inbox_target({"scope": "engineering", "category": "construction", "item_code": "001"})

    def test_mobile_upload_imports_only_selected_leaf_and_backfill_keeps_identity(self):
        # Select the last sibling, so any first-match-on-original-code bug cannot accidentally pass.
        selected = self.codes[-1]
        batch = self.client.post("/api/mobile/v1/batches", json={
            "client_batch_id": str(uuid.uuid4()), "project_id": self.project["id"],
            "scope": "engineering", "category": "construction", "mode": "direct", "assignment": {"item_code": selected},
        }, headers=self.user_headers)
        self.assertEqual(batch.status_code, 201, batch.get_json())
        self.assertEqual(batch.get_json()["batch"]["assignment"]["item_code"], selected)
        batch_id = batch.get_json()["batch"]["batch_id"]
        photo_uuid = str(uuid.uuid4())
        raw = support.jpeg_bytes((80, 60))
        response = self.client.post(f"/api/mobile/v1/batches/{batch_id}/photos", data={
            "photo_uuid": photo_uuid, "file": (io.BytesIO(raw), "mobile.jpg"),
            "sha256": hashlib.sha256(raw).hexdigest(), "original_size_bytes": str(len(raw)),
            "client_captured_at": "2026-11-01T08:00:00Z", "auto_delivery": "true",
        }, content_type="multipart/form-data", headers=self.user_headers)
        self.assertEqual(response.status_code, 201, response.get_json())
        committed = self.client.post(f"/api/mobile/v1/batches/{batch_id}/commit", headers=self.user_headers)
        self.assertEqual(committed.status_code, 200, committed.get_json())
        result = self.service._sync_inbox()
        self.assertEqual(result.get("imported"), 1, result)
        for code in self.codes:
            found = [p for p in self.manager.get_project(code).get("photos", []) if p.get("photo_uuid") == photo_uuid]
            self.assertEqual(len(found), 1 if code == selected else 0)
            if found:
                self.assertEqual((self.manager._photos_dir(code) / found[0]["filename"]).read_bytes(), raw)
        # A separate desktop original on another same-code sibling must backfill into that sibling.
        target = self.codes[1]
        desktop_uuid = str(uuid.uuid4())
        data = self.manager.get_project(target)
        data["photos"].append({"id": "SY999", "photo_uuid": desktop_uuid, "filename": "desktop.jpg",
            "category": "construction", "title": "电脑原片", "photo_date": "2026-11-01", "process_name": "",
            "sha256": hashlib.sha256(raw).hexdigest()})
        self.manager._write_metadata(target, data)
        path = self.manager._photos_dir(target) / "desktop.jpg"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        result = self.service._sync_backfill()
        self.assertGreaterEqual(result.get("uploaded", 0), 1, result)
        response = self.client.get(f"/api/mobile/v1/photos/{desktop_uuid}", headers=self.user_headers)
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["photo"]["assignment"]["item_code"], target)
        self.assertEqual(path.read_bytes(), raw)


if __name__ == "__main__":
    unittest.main()
