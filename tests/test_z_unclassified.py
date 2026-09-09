import hashlib
import io
import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from werkzeug.datastructures import FileStorage


class UnclassifiedWorkflowTest(unittest.TestCase):
    def setUp(self):
        import app
        self.app = app
        self.temp = tempfile.TemporaryDirectory(prefix="album-unclassified-")
        self.manager = app.AlbumManager(Path(self.temp.name))
        self.project = {"id": "project-A", "project_name": "工程 A", "project_code": "A", "cloud_owner_id": "owner-A"}
        self.tree = {"nodes": []}
        self.ownership = {"state": "matched", "owner_id": "owner-A", "account_id": "owner-A", "project_ref": "owner-A:project-A", "local_project_id": "project-A"}
        def write_tree(value):
            self.tree = json.loads(json.dumps(value))
        patches = [
            patch.object(app, "manager", self.manager),
            patch.object(app, "current_engineering_project", lambda: dict(self.project)),
            patch.object(app, "read_other_images", lambda: json.loads(json.dumps(self.tree))),
            patch.object(app, "write_other_images", write_tree),
            patch.object(app, "current_project_cloud_ownership", lambda: dict(self.ownership)),
            patch.object(app.licensing, "machine_id", return_value="MACHINE-A"),
            patch.object(app, "read_engineering_settings", return_value={"process_digits": 3, "numbering_rules": app.DEFAULT_NUMBERING_RULES}),
        ]
        self.patches = patches
        for active in patches:
            active.start()
        self.client = app.app.test_client()
        with self.client.session_transaction() as session:
            session["username"] = "owner"
        self.identity = app.mobile_sync._engineering_project_identity(self.project)
        self.stage = app.ensure_unclassified_project(self.identity)
        self.unit = self.manager.create_project("UNIT-1", "一号单元", source_fields={"单位工程名称": "单位", "单位工程编码": "UP", "分部工程名称": "分部", "分部工程编码": "PART", "单元工程编码": "UNIT-1"})
        unit = self.manager.get_project("UNIT-1")
        unit["processes"] = ["模板验收"]
        self.manager._write_metadata("UNIT-1", unit)

    def tearDown(self):
        for active in reversed(self.patches):
            active.stop()
        self.temp.cleanup()

    def seed_photo(self):
        stream = io.BytesIO()
        Image.new("RGB", (360, 240), (30, 80, 100)).save(stream, "JPEG")
        raw = stream.getvalue()
        permanent = str(uuid.uuid4())
        self.manager.add_photos(self.stage, [FileStorage(stream=io.BytesIO(raw), filename="original.jpg")], title="原题名", photo_date="2026-09-09", photographer="张三", per_file_meta={"original.jpg": {"photo_uuid": permanent, "preserve_mobile_original": True, "mobile_original_received": True, "mobile_unclassified": True, "manual_review_required": True, "review_reason": "OCR 未能识别", "sha256": hashlib.sha256(raw).hexdigest(), "project_owner_account_id": "owner-A"}})
        return permanent, raw

    def test_provider_is_idempotent_and_scoped_without_rewriting_other_projects(self):
        self.assertEqual(self.app.ensure_unclassified_project(self.identity), self.stage)
        self.assertEqual(len(self.tree["nodes"]), 1)
        fields = self.manager.get_project(self.stage)["source_fields"]
        self.assertEqual(fields["_mobile_unclassified_project_ref"], "owner-A:project-A")
        with self.assertRaisesRegex(ValueError, "已切换"):
            self.app.ensure_unclassified_project({**self.identity, "owner_account_id": "another-owner"})

    def test_authenticated_list_move_preserves_uuid_original_and_metadata_and_retries_idempotently(self):
        permanent, original = self.seed_photo()
        result = self.client.get("/api/unclassified").get_json()
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["photos"][0]["review_reason"], "OCR 未能识别")
        payload = {"project_id": "project-A", "photo_uuids": [permanent], "target_project_code": "UNIT-1", "target_process_name": "模板验收"}
        moved = self.client.post("/api/unclassified/classify", json=payload)
        self.assertEqual(moved.status_code, 200, moved.get_json())
        photo = self.manager.get_project("UNIT-1")["photos"][0]
        self.assertEqual(photo["photo_uuid"], permanent)
        self.assertEqual(photo["title"], "原题名")
        self.assertEqual(photo["photographer"], "张三")
        self.assertTrue(photo["mobile_classification_pending"])
        self.assertFalse(photo["manual_review_required"])
        self.assertEqual((self.manager._photos_dir("UNIT-1") / photo["filename"]).read_bytes(), original)
        self.assertEqual(self.client.get("/api/unclassified").get_json()["count"], 0)
        self.assertEqual(self.client.post("/api/unclassified/classify", json=payload).status_code, 200)
        self.assertEqual(len(self.manager.get_project("UNIT-1")["photos"]), 1)

    def test_auth_wrong_owner_project_and_unsafe_target_are_rejected_without_moving(self):
        permanent, _raw = self.seed_photo()
        payload = {"project_id": "project-A", "photo_uuids": [permanent], "target_project_code": "../UNIT-1"}
        self.assertEqual(self.client.post("/api/unclassified/classify", json=payload).status_code, 400)
        payload.update(target_project_code="UNIT-1", project_id="wrong-project")
        self.assertEqual(self.client.post("/api/unclassified/classify", json=payload).status_code, 400)
        self.ownership["state"] = "mismatch"
        self.assertEqual(self.client.get("/api/unclassified").status_code, 403)
        self.assertEqual(len(self.manager.get_project(self.stage)["photos"]), 1)
        with self.client.session_transaction() as session:
            session.clear()
        self.assertEqual(self.client.get("/api/unclassified").status_code, 401)

    def test_target_metadata_failure_rolls_back_the_only_original(self):
        permanent, original = self.seed_photo()
        source = self.manager.get_project(self.stage)["photos"][0]
        write = self.manager._write_metadata
        fail_once = [True]
        def guarded(code, data):
            if code == "UNIT-1" and fail_once[0]:
                fail_once[0] = False
                raise OSError("disk full")
            return write(code, data)
        with patch.object(self.manager, "_write_metadata", side_effect=guarded):
            with self.assertRaises(Exception):
                self.manager.move_photo(self.stage, source["id"], "UNIT-1")
        recovered = next(photo for photo in self.manager.get_project(self.stage)["photos"] if photo["photo_uuid"] == permanent)
        self.assertEqual((self.manager._photos_dir(self.stage) / recovered["filename"]).read_bytes(), original)
        self.assertFalse(self.manager.get_project("UNIT-1")["photos"])


if __name__ == "__main__":
    unittest.main()
