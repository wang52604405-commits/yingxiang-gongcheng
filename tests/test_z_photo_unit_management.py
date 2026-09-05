# -*- coding: utf-8 -*-
from __future__ import annotations

import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from PIL import Image



class PhotoUnitManagementTest(unittest.TestCase):
    def setUp(self):
        # Lazy import prevents unittest discovery from initializing app.py before
        # the repository's existing product-core isolation fixtures run.
        import app as desktop_app
        self.desktop_app = desktop_app
        self.temp = tempfile.TemporaryDirectory(prefix="album-photo-move-")
        self.manager = self.desktop_app.AlbumManager(Path(self.temp.name))
        self.settings = patch.object(
            self.desktop_app,
            "read_engineering_settings",
            return_value={
                "process_digits": 3,
                "numbering_rules": self.desktop_app.DEFAULT_NUMBERING_RULES,
            },
        )
        self.settings.start()
        # The fixture owns a standalone temporary AlbumManager rather than a full
        # engineering project, so bypass only this fixture's global ownership check.
        self.engineering_match = patch.object(
            self.desktop_app,
            "project_matches_engineering",
            return_value=True,
        )
        self.engineering_match.start()

    def tearDown(self):
        self.engineering_match.stop()
        self.settings.stop()
        self.temp.cleanup()

    def make_unit(self, code: str, name: str, processes=None):
        data = {
            "project_code": code,
            "display_project_code": code,
            "project_name": name,
            "photos": [],
            "processes": list(processes or []),
            "source_fields": {},
        }
        self.manager._project_dir(code).mkdir(parents=True, exist_ok=True)
        self.manager._photos_dir(code).mkdir(parents=True, exist_ok=True)
        self.manager._originals_dir(code).mkdir(parents=True, exist_ok=True)
        self.manager._write_metadata(code, data)
        return self.manager.get_project(code)

    def add_photo(self, code: str, process_name="", photo_uuid=""):
        data = self.manager.get_project(code)
        name = f"seed-{uuid.uuid4().hex}.jpg"
        target = self.manager._photos_dir(code) / name
        Image.new("RGB", (640, 480), (80, 120, 160)).save(target, "JPEG", quality=90)
        permanent = photo_uuid or uuid.uuid4().hex
        record = {
            "id": f"{code}-LEGACY-SY001",
            "filename": name,
            "original_name": name,
            "photo_uuid": permanent,
            "category": "construction",
            "category_label": "施工",
            "title": "测试照片",
            "photo_date": "2026-09-05",
            "photographer": "测试员",
            "description": "跨单元移动测试",
            "process_name": process_name,
            "process_code": self.manager._process_code(data, process_name) if process_name else "",
            "rotation": 0,
        }
        data.setdefault("photos", []).append(record)
        self.manager._renumber_after_change(code, data)
        return permanent

    def test_two_level_numbering_drops_unit_prefix(self):
        data = self.make_unit("YNLQ-2024-001", "一号单元", ["土方开挖"])
        unit_id = self.manager._archive_id_for_photo(data, {"process_name": ""}, "construction", 1)
        process_id = self.manager._archive_id_for_photo(data, {"process_name": "土方开挖"}, "construction", 1)
        self.assertEqual(unit_id, "SYDY001")
        self.assertEqual(process_id, "GY001-SYGX001")
        self.assertNotIn("YNLQ-2024", unit_id)
        self.assertNotIn("YNLQ-2024", process_id)

    def test_rename_process_keeps_order_and_photo_uuid(self):
        self.make_unit("SRC-001", "源单元", ["土方开挖", "模板安装"])
        permanent = self.add_photo("SRC-001", "土方开挖")
        before = self.manager.get_photos("SRC-001")[0]
        self.assertEqual(before["process_code"], "GY001")
        project = self.manager.rename_process("SRC-001", "土方开挖", "基坑开挖")
        self.assertEqual(project["processes"], ["基坑开挖", "模板安装"])
        after = self.manager.get_photos("SRC-001")[0]
        self.assertEqual(after["photo_uuid"], permanent)
        self.assertEqual(after["process_name"], "基坑开挖")
        self.assertEqual(after["process_code"], "GY001")
        self.assertTrue((self.manager._photos_dir("SRC-001") / after["filename"]).is_file())

    def test_cross_unit_move_preserves_uuid_and_reassigns_process(self):
        self.make_unit("YNLQ-2024-SRC", "源单元", ["开挖"])
        self.make_unit("YNLQ-2024-DST", "目标单元", ["验收"])
        permanent = self.add_photo("YNLQ-2024-SRC", "开挖")
        source_photo = self.manager.get_photos("YNLQ-2024-SRC")[0]
        moved = self.manager.move_photo(
            "YNLQ-2024-SRC",
            source_photo["id"],
            "YNLQ-2024-DST",
            category="construction",
            target_process_name="验收",
        )
        self.assertEqual(self.manager.get_photos("YNLQ-2024-SRC"), [])
        target_photos = self.manager.get_photos("YNLQ-2024-DST")
        self.assertEqual(len(target_photos), 1)
        self.assertEqual(target_photos[0]["photo_uuid"], permanent)
        self.assertEqual(target_photos[0]["process_name"], "验收")
        self.assertEqual(target_photos[0]["process_code"], "GY001")
        self.assertEqual(target_photos[0]["id"], "GY001-SYGX001")
        self.assertEqual(moved["photo_uuid"], permanent)
        self.assertTrue((self.manager._photos_dir("YNLQ-2024-DST") / target_photos[0]["filename"]).is_file())


class FrontendPhotoManagementContractTest(unittest.TestCase):
    def test_filters_move_dialog_process_controls_and_red_counts_exist(self):
        root = Path(__file__).resolve().parents[1]
        html = (root / "templates" / "index.html").read_text(encoding="utf-8")
        js_files = sorted((root / "assets").glob("app-A*.js"))
        css_files = sorted((root / "assets").glob("app-A*.css"))
        self.assertEqual(len(js_files), 1)
        self.assertEqual(len(css_files), 1)
        js = js_files[0].read_text(encoding="utf-8")
        css = css_files[0].read_text(encoding="utf-8")
        for marker in ("unitListSearchInput", "unitUploadFilter", "photoMoveModal", "photoMoveTargetSelect"):
            self.assertIn(marker, html)
        for marker in ("renameProcess", "deleteProcess", "confirmPhotoMove", "data-process-rename", "data-process-delete"):
            self.assertIn(marker, js)
        self.assertIn("unit-card-photo-counts b.has-photos", css)
        self.assertIn("color:#dc2626", css)


if __name__ == "__main__":
    unittest.main()
