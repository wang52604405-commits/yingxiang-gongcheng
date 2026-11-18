"""市政分项的电脑预览回填和待归类回写必须贯通真实服务端。"""
from __future__ import annotations

import hashlib
import io
import tempfile
import unittest
import uuid
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import mobile_sync
import municipal_rules

if __package__:
    from .test_mobile_sync import FakeCloud, FakeManager, jpeg_bytes
else:
    from test_mobile_sync import FakeCloud, FakeManager, jpeg_bytes


class MunicipalManager(FakeManager):
    def project_hierarchy(self, data):
        result = super().project_hierarchy(data)
        fields = data.get("source_fields") or {}
        result.update({
            "node_kind": fields.get("节点类型", "unit"),
            "item_code": fields.get("分项工程编码", ""),
            "item_name": fields.get("分项工程名称", ""),
        })
        if result["node_kind"] == "item":
            result["unit_code"] = ""
        return result


class ServerCloud(FakeCloud):
    def __init__(self, client, token, account_id):
        super().__init__(identity=str(account_id))
        self.client = client
        self.headers = {"Authorization": "Bearer " + token}
        self.classifications = []

    @staticmethod
    def result(response):
        return {**response.get_json(), "http_status": response.status_code}

    def desktop_project_snapshot(self, snapshot):
        return self.result(self.client.post(
            "/api/desktop/v1/project-snapshot", json=snapshot, headers=self.headers,
        ))

    def desktop_backfill_photo(self, path, metadata):
        self.backfills.append(dict(metadata))
        return self.result(self.client.post(
            "/api/desktop/v1/backfill-photo",
            data={**metadata, "file": (io.BytesIO(Path(path).read_bytes()), "preview.jpg")},
            content_type="multipart/form-data", headers=self.headers,
        ))

    def desktop_classify_photo(self, photo_uuid, metadata):
        self.classifications.append(dict(metadata))
        return self.result(self.client.post(
            f"/api/desktop/v1/photos/{photo_uuid}/classify",
            json=metadata, headers=self.headers,
        ))


class MunicipalDesktopRoundtripTest(unittest.TestCase):
    def setUp(self):
        from server import app as server_app, config, db

        self.temp = tempfile.TemporaryDirectory(prefix="municipal-desktop-roundtrip-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        overrides = {
            "DATA_DIR": self.root / "server",
            "DB_PATH": self.root / "server" / "server.db",
            "MOBILE_STORAGE_BACKEND": "local",
            "MOBILE_STORAGE_DIR": self.root / "objects",
            "WECHAT_MOCK_ENABLED": True,
            "ADMIN_USERNAME": "",
            "ADMIN_PASSWORD": "",
        }
        old_config = {key: getattr(config, key) for key in overrides}
        self.addCleanup(lambda: [setattr(config, key, value) for key, value in old_config.items()])
        for key, value in overrides.items():
            setattr(config, key, value)
        old_signer = server_app.signer
        self.addCleanup(lambda: setattr(server_app, "signer", old_signer))
        server_app.signer = server_app.LicenseSigner(self.root / "test-key")
        server_app.signer._key = Ed25519PrivateKey.generate()
        server_app._rate_hits.clear()
        app = server_app.create_app()
        app.config["TESTING"] = True
        self.client = app.test_client()
        self.db = db
        registered = self.client.post("/api/register", json={"username": "municipal_sync", "password": "MunicipalSync2026"})
        self.assertEqual(registered.status_code, 200, registered.get_json())
        token = self.client.post("/api/login", json={"username": "municipal_sync", "password": "MunicipalSync2026"}).get_json()["token"]
        self.user_headers = {"Authorization": "Bearer " + token}
        conn = db.connect()
        self.account_id = conn.execute("SELECT id FROM accounts WHERE username = 'municipal_sync'").fetchone()["id"]
        conn.execute("INSERT INTO machines(account_id,machine_id,active) VALUES (?,'MACHINE-A',1)", (self.account_id,))
        conn.execute("INSERT INTO licenses(account_id,license_type,valid_days,active) VALUES (?,'lifetime',0,1)", (self.account_id,))
        conn.commit()
        conn.close()
        activated = self.client.post("/api/activate", json={"machine_id": "MACHINE-A"}, headers=self.user_headers)
        self.assertEqual(activated.status_code, 200, activated.get_json())
        self.cloud = ServerCloud(self.client, activated.get_json()["desktop_sync_token"], self.account_id)
        self.manager = MunicipalManager(self.root / "albums")
        self.project = {
            "id": "municipal-road", "project_code": "SZ", "project_name": "市政道路",
            "industry": "市政工程", "project_type": "城镇道路",
            "rule_version": municipal_rules.RULE_VERSION,
            "cloud_owner_id": str(self.account_id),
        }
        self.manager.add_project("FX-001", "清表", {
            "合同工程名称": "一标段", "单位工程编码": "DW-1", "单位工程名称": "人民路",
            "分部工程编码": "FB-1", "分部工程名称": "路基",
            "节点类型": "item", "分项工程编码": "FX-001", "分项工程名称": "清表",
        }, division_type="item")
        self.manager.add_project("OLD-UNIT", "保留的水利单元", {
            "合同工程名称": "一标段", "单位工程编码": "DW-OLD", "单位工程名称": "原工程",
            "分部工程编码": "FB-OLD", "分部工程名称": "原分部", "单元工程编码": "OLD-UNIT",
        })
        self.service = mobile_sync.DesktopMobileSync(
            self.manager, self.cloud, lambda: dict(self.project), lambda: {"nodes": []},
            self.root / "state.json", self.root / "cache", machine_id_reader=lambda: "MACHINE-A",
        )
        snapshot = self.service._sync_snapshot()
        self.assertTrue(snapshot.get("ok"), snapshot)

    def add_photo(self, project_code, **extra):
        raw = jpeg_bytes((80, 60))
        photo = {
            "id": "SY001", "photo_uuid": str(uuid.uuid4()), "filename": "original.jpg",
            "category": "construction", "title": "现场检查", "photo_date": "2026-11-01",
            "process_name": "", "sha256": hashlib.sha256(raw).hexdigest(),
            **extra,
        }
        data = self.manager.get_project(project_code)
        data["photos"].append(photo)
        self.manager._write_metadata(project_code, data)
        path = self.manager._photos_dir(project_code) / "original.jpg"
        path.write_bytes(raw)
        return photo, path, raw

    def test_desktop_backfill_routes_item_and_legacy_unit_without_touching_originals(self):
        item, item_path, item_raw = self.add_photo("FX-001", archive={"location_text": "人民路 K0+120"}, spatial={"stake_start": "K0+120"})
        unit, unit_path, unit_raw = self.add_photo("OLD-UNIT")
        result = self.service._sync_backfill()
        self.assertEqual(result.get("uploaded"), 2, result)
        self.assertEqual(result["inventory"]["permanent_error_count"], 0)
        for photo, field, expected in ((item, "item_code", "FX-001"), (unit, "unit_code", "OLD-UNIT")):
            response = self.client.get(f"/api/mobile/v1/photos/{photo['photo_uuid']}", headers=self.user_headers)
            self.assertEqual(response.status_code, 200, response.get_json())
            payload = response.get_json()["photo"]
            self.assertEqual(payload["assignment"][field], expected)
            self.assertEqual(payload["source"], "desktop")
            self.assertEqual(payload["status"], "desktop_imported")
            if field == "item_code":
                self.assertEqual(payload["assignment"]["unit_code"], "")
                self.assertEqual(payload["assignment"]["archive"]["location_text"], "人民路 K0+120")
                self.assertEqual(payload["assignment"]["spatial"]["stake_start"], "K0+120")
        self.assertEqual(item_path.read_bytes(), item_raw)
        self.assertEqual(unit_path.read_bytes(), unit_raw)

    def test_pending_mobile_classification_writes_item_then_is_idempotent(self):
        photo, path, raw = self.add_photo(
            "FX-001", mobile_original_received=True, mobile_classification_pending=True,
            project_owner_account_id=str(self.account_id),
            archive={"location_text": "人民路 K0+120"}, spatial={"stake_start": "K0+120"},
        )
        batch = self.client.post("/api/mobile/v1/batches", json={
            "client_batch_id": str(uuid.uuid4()), "project_id": "municipal-road",
            "scope": "engineering", "category": "construction", "mode": "direct",
            "assignment": {"item_code": "FX-001"},
        }, headers=self.user_headers)
        self.assertEqual(batch.status_code, 201, batch.get_json())
        batch_id = batch.get_json()["batch"]["batch_id"]
        uploaded = self.client.post(f"/api/mobile/v1/batches/{batch_id}/photos", data={
            "photo_uuid": photo["photo_uuid"], "file": (io.BytesIO(raw), "original.jpg"),
            "sha256": hashlib.sha256(raw).hexdigest(), "client_captured_at": "2026-11-01T08:00:00Z",
            "auto_delivery": "true",
        }, content_type="multipart/form-data", headers=self.user_headers)
        self.assertEqual(uploaded.status_code, 201, uploaded.get_json())
        committed = self.client.post(f"/api/mobile/v1/batches/{batch_id}/commit", headers=self.user_headers)
        self.assertEqual(committed.status_code, 200, committed.get_json())
        ack = self.client.post(f"/api/desktop/v1/photos/{photo['photo_uuid']}/ack", json={
            "desktop_machine_id": "MACHINE-A", "local_project_code": "FX-001", "local_photo_id": "SY001",
        }, headers=self.cloud.headers)
        self.assertEqual(ack.status_code, 200, ack.get_json())
        result = self.service._sync_classification_pending()
        self.assertEqual(result, {"ok": True, "synced": 1, "failed": 0})
        self.assertFalse(self.manager.get_project("FX-001")["photos"][0]["mobile_classification_pending"])
        response = self.client.get(f"/api/mobile/v1/photos/{photo['photo_uuid']}", headers=self.user_headers)
        assignment = response.get_json()["photo"]["assignment"]
        self.assertEqual(assignment["item_code"], "FX-001")
        self.assertEqual(assignment["unit_code"], "")
        self.assertEqual(assignment["archive"]["location_text"], "人民路 K0+120")
        self.assertEqual(assignment["spatial"]["stake_start"], "K0+120")
        again = self.cloud.desktop_classify_photo(photo["photo_uuid"], self.cloud.classifications[-1])
        self.assertTrue(again.get("ok"), again)
        self.assertTrue(again["idempotent"])
        self.assertEqual(path.read_bytes(), raw)

    def test_missing_item_waits_for_new_snapshot_without_blocking_other_photos(self):
        self.manager.add_project("FX-NEW", "新分项", {
            "合同工程名称": "一标段", "单位工程编码": "DW-1", "单位工程名称": "人民路",
            "分部工程编码": "FB-1", "分部工程名称": "路基",
            "节点类型": "item", "分项工程编码": "FX-NEW", "分项工程名称": "新分项",
        }, division_type="item")
        photo, path, raw = self.add_photo("FX-NEW")
        self.add_photo("OLD-UNIT")
        result = self.service._sync_backfill()
        self.assertEqual(result["uploaded"], 1, result)
        self.assertEqual(result["inventory"]["permanent_error_count"], 1)
        error = self.service._read_state()["backfill_errors"][photo["photo_uuid"]]
        self.assertEqual(error["code"], "item_not_found")
        attempts = len(self.cloud.backfills)
        self.assertEqual(self.service._sync_backfill()["uploaded"], 0)
        self.assertEqual(len(self.cloud.backfills), attempts)
        self.assertTrue(self.service._sync_snapshot()["ok"])
        retried = self.service._sync_backfill()
        self.assertEqual(retried["uploaded"], 1, retried)
        self.assertEqual(retried["inventory"]["permanent_error_count"], 0)
        self.assertEqual(path.read_bytes(), raw)


if __name__ == "__main__":
    unittest.main()
