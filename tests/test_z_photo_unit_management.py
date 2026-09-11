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

    def test_custom_numbering_rule_applies_when_project_has_processes(self):
        """定义工序的工程也必须跟随“编号规则”里的模板。

        回归背景：两级编号分支曾把格式写死成 SYDY/SYGX，且不读 unit_template /
        process_template，导致客户在设置里改模板完全无效（只有起始号、位数生效）。
        """
        data = self.make_unit("YNLQ-2024-SG-1-01-001", "一号单元", ["土方开挖"])
        custom = {
            "construction": {
                "template": "{code}-GC{seq}",
                "unit_template": "{code}-GC{seq}",
                "process_template": "{code}-GC{process_code}{seq}",
                "start": 5,
                "digits": 4,
                "label": "施工单元影像",
            },
            "supervision": dict(self.desktop_app.DEFAULT_NUMBERING_RULES["supervision"]),
        }
        self.settings.stop()
        self.settings = patch.object(
            self.desktop_app,
            "read_engineering_settings",
            return_value={
                "process_digits": 3,
                "unit_order_digits": 3,
                "numbering_rules": custom,
            },
        )
        self.settings.start()

        unit_id = self.manager._archive_id_for_photo(data, {"process_name": ""}, "construction", 5)
        process_id = self.manager._archive_id_for_photo(
            data, {"process_name": "土方开挖"}, "construction", 5
        )

        self.assertEqual(unit_id, "YNLQ-2024-SG-1-01-001-GC0005")
        self.assertEqual(process_id, "YNLQ-2024-SG-1-01-001-GCGY0010005")
        # 自定义后不应再出现写死的 SYDY / SYGX 标记
        self.assertNotIn("SYDY", unit_id)
        self.assertNotIn("SYGX", process_id)

    def test_default_rule_still_uses_legacy_two_level_format(self):
        """未自定义模板时，两级编号必须保持原有的短格式，避免老工程编号突变。"""
        data = self.make_unit("YNLQ-2024-SG-1-01-001", "一号单元", ["土方开挖"])
        unit_id = self.manager._archive_id_for_photo(data, {"process_name": ""}, "construction", 1)
        process_id = self.manager._archive_id_for_photo(
            data, {"process_name": "土方开挖"}, "construction", 1
        )
        self.assertEqual(unit_id, "SYDY001")
        self.assertEqual(process_id, "GY001-SYGX001")

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
        self.assertIn("color: #d92d20", css)
        self.assertNotIn("background:#fff1f2", css)
        self.assertNotIn("box-shadow:0 0 0 2px", css)
        self.assertIn("#partView > .page-head .unit-filter-toolbar", css)
        self.assertLess(html.index("unitListSearchInput"), html.index("part-scroll-panel"))
        self.assertIn('class="orientation-select" size="7"', html)

    def test_settings_panel_exposes_a_separate_process_template(self):
        """设置里的编号规则必须能单独配“工序格式”，不能被单元格式覆盖。

        回归背景：设置面板此前把 process_template 直接写成单元模板，
        工序编码从未进入编号；而且没有工序格式输入框，客户无处可改。
        """
        root = Path(__file__).resolve().parents[1]
        html = (root / "templates" / "index.html").read_text(encoding="utf-8")
        js = sorted((root / "assets").glob("app-A*.js"))[0].read_text(encoding="utf-8")

        # 施工 / 监理各有一个独立的工序格式输入框
        self.assertIn('id="settingsConstructionProcessTemplate"', html)
        self.assertIn('id="settingsSupervisionProcessTemplate"', html)
        # 占位符表必须支持【工序编码】，否则界面读写会丢工序编码
        self.assertIn('【工序编码】', js)
        self.assertIn('"{process_code}"', js)
        # 保存时工序模板取自工序输入框，而不是照抄单元模板
        self.assertIn('process_template: constructionProcessTemplate', js)
        self.assertIn('process_template: supervisionProcessTemplate', js)
        self.assertNotIn('process_template: constructionUnitTemplate', js)
        self.assertNotIn('process_template: supervisionUnitTemplate', js)
        # 工序格式留空时自动在单元格式里插入工序编码
        self.assertIn("function processTemplateFromUnit(", js)


if __name__ == "__main__":
    unittest.main()
