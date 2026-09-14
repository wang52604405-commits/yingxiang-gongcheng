# -*- coding: utf-8 -*-
from __future__ import annotations

import io
import re
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from werkzeug.datastructures import FileStorage


class ProcessPhotoTransferTest(unittest.TestCase):
    def setUp(self):
        import app as desktop_app

        self.desktop = desktop_app
        self.temp = tempfile.TemporaryDirectory(prefix="album-process-transfer-")
        self.manager = desktop_app.AlbumManager(Path(self.temp.name))
        self.manager_patch = patch.object(desktop_app, "manager", self.manager)
        self.match_patch = patch.object(desktop_app, "project_matches_engineering", return_value=True)
        self.manager_patch.start()
        self.match_patch.start()
        self.project_code = "PROC-MOVE-001"
        self.manager._write_metadata(
            self.project_code,
            {
                "project_code": self.project_code,
                "display_project_code": self.project_code,
                "project_name": "工序照片移动测试单元",
                "engineering_project_id": "test-project",
                "processes": ["钢筋安装", "混凝土浇筑"],
                "photos": [],
                "source_fields": {},
            },
        )
        self.client = desktop_app.app.test_client()
        with self.client.session_transaction() as session:
            session["username"] = "工序测试员"

    def tearDown(self):
        self.match_patch.stop()
        self.manager_patch.stop()
        self.temp.cleanup()

    @staticmethod
    def jpg_file(name: str) -> FileStorage:
        memory = io.BytesIO()
        Image.new("RGB", (96, 72), (36, 108, 126)).save(memory, "JPEG", quality=90)
        memory.seek(0)
        return FileStorage(stream=memory, filename=name, content_type="image/jpeg")

    def test_same_unit_photo_can_move_between_processes(self):
        added = self.manager.add_photos(
            self.project_code,
            [self.jpg_file("process-a.jpg")],
            category="construction",
            photo_date="2026-09-14",
            process_name="钢筋安装",
        )[0]
        original_uuid = added["photo_uuid"]
        moved = self.manager.move_photo(
            self.project_code,
            added["id"],
            self.project_code,
            category="construction",
            target_process_name="混凝土浇筑",
        )
        self.assertEqual(moved["photo_uuid"], original_uuid)
        self.assertEqual(moved["process_name"], "混凝土浇筑")
        self.assertEqual(moved["process_code"], "GY002")
        photos = self.manager.get_photos(self.project_code)
        self.assertEqual(len(photos), 1)
        self.assertEqual(photos[0]["process_name"], "混凝土浇筑")

    def test_delete_process_prunes_stale_deleted_photo_metadata(self):
        added = self.manager.add_photos(
            self.project_code,
            [self.jpg_file("stale.jpg")],
            category="construction",
            photo_date="2026-09-14",
            process_name="钢筋安装",
        )[0]
        data = self.manager.get_project(self.project_code)
        photo = next(item for item in data["photos"] if item["photo_uuid"] == added["photo_uuid"])
        photo_path = self.manager._photos_dir(self.project_code) / photo["filename"]
        photo_path.unlink()
        thumb = self.manager._photos_dir(self.project_code) / self.manager._thumb_filename(photo["filename"])
        thumb.unlink(missing_ok=True)

        encoded = urllib.parse.quote("钢筋安装", safe="")
        response = self.client.delete(f"/api/photos/{self.project_code}/processes/{encoded}")
        self.assertEqual(response.status_code, 200, response.get_json())
        payload = response.get_json()
        self.assertEqual(payload["stale_removed"], 1)
        self.assertNotIn("钢筋安装", payload["processes"])
        self.assertEqual(self.manager.get_project(self.project_code)["photos"], [])

    def test_real_remaining_photo_still_blocks_process_delete_with_category_count(self):
        self.manager.add_photos(
            self.project_code,
            [self.jpg_file("real.jpg")],
            category="supervision",
            photo_date="2026-09-14",
            process_name="钢筋安装",
        )
        encoded = urllib.parse.quote("钢筋安装", safe="")
        response = self.client.delete(f"/api/photos/{self.project_code}/processes/{encoded}")
        self.assertEqual(response.status_code, 400, response.get_json())
        self.assertIn("监理1张", response.get_json()["error"])
        self.assertIn("钢筋安装", self.manager.get_project(self.project_code)["processes"])

    def test_desktop_move_dialog_exposes_current_unit_for_process_transfer(self):
        root = Path(__file__).resolve().parents[1]
        html = (root / "templates" / "index.html").read_text(encoding="utf-8")
        asset = re.search(r'<script\s+defer\s+src="/assets/(app-A[^"]+\.js)"></script>', html)
        self.assertIsNotNone(asset)
        js = (root / "assets" / asset.group(1)).read_text(encoding="utf-8")
        self.assertIn('projectCode(project) === state.selectedCode', js)
        self.assertNotIn('projectCode(project) && projectCode(project) !== state.selectedCode', js)
        self.assertIn('targetCode === sourceCode && targetProcess === sourceProcess', js)
        self.assertIn('移动照片到工序或其它单元', html)
        self.assertIn('id="movePhotoBtn">移动到工序/单元</button>', html)


if __name__ == "__main__":
    unittest.main()
