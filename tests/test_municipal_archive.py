# -*- coding: utf-8 -*-
"""市政专业契约：划分、空间定位、原件和整理包，不把水利单元逻辑套过来。"""
from __future__ import annotations

import gzip
import io
import json
import os
import tempfile
import unittest
import uuid
import zipfile
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from werkzeug.datastructures import FileStorage

import municipal_export
import municipal_rules


ROOT = Path(__file__).resolve().parents[1]


def _jpeg_bytes():
    memory = io.BytesIO()
    Image.new("RGB", (32, 24), (20, 80, 40)).save(memory, "JPEG", quality=90)
    return memory.getvalue()


class MunicipalRuleContractTest(unittest.TestCase):
    def test_catalog_aliases_and_unknown_type_do_not_fallback(self):
        self.assertEqual(municipal_rules.canonical_project_type("道路工程"), "城镇道路")
        self.assertEqual(municipal_rules.canonical_project_type("泵站"), "给水排水构筑物")
        with self.assertRaises(municipal_rules.MunicipalRuleError) as raised:
            municipal_rules.canonical_project_type("地铁工程")
        self.assertEqual(raised.exception.code, "unknown_project_type")
        with self.assertRaises(municipal_rules.MunicipalRuleError):
            municipal_rules.filter_requirements([], "")

    def test_six_types_remain_and_structure_has_no_fake_photo_list(self):
        import professional_templates

        professional_templates.load_template_db.cache_clear()
        names = [item["name"] for item in municipal_rules.SUBTYPES]
        self.assertEqual(names, ["城镇道路", "城市桥梁", "给水管道", "排水管道", "综合管廊", "道路照明与交通设施", "给水排水构筑物"])
        for name in ("城镇道路", "城市桥梁", "给水管道", "排水管道", "综合管廊", "道路照明与交通设施"):
            rows = professional_templates.requirements("市政工程", name)
            self.assertGreater(len(rows), 0, name)
            self.assertTrue(all(row["rule_level"] in {"product_default", "national_mandatory"} for row in rows))
            self.assertTrue(all("本条属于国家强制" not in row["rule_nature"] for row in rows if row["rule_level"] != "national_mandatory"))
        structure = professional_templates.plan_summary("市政工程", "给水排水构筑物")
        self.assertEqual(structure["total"], 0)
        self.assertEqual(structure["checklist_status"], "project_config")
        self.assertIn("不能把泵站", structure["support_note"])

    def test_concealment_clause_is_not_a_batch_timing_phrase(self):
        import professional_templates

        professional_templates.load_template_db.cache_clear()
        rows = []
        for name in ("城镇道路", "城市桥梁", "给水管道", "排水管道"):
            rows.extend(professional_templates.requirements("市政工程", name))
        mandatory = [row for row in rows if row["rule_level"] == "national_mandatory"]
        suggested = [row for row in rows if row["rule_level"] == "product_default"]
        self.assertTrue(mandatory)
        self.assertTrue(all(row["rule_clause"] == municipal_rules.CONCEALMENT_CLAUSE for row in mandatory))
        self.assertTrue(all(row["before_concealment_required"] == "是" for row in mandatory))
        self.assertTrue(all("软件建议" in row["rule_nature"] for row in suggested))
        self.assertTrue(all("55032" not in row["standard_source"] for row in suggested))
        self.assertIn(municipal_rules.RULE_VERSION, rows[0]["rule_version"])

    def test_spatial_text_keeps_well_numbers_and_stake_text(self):
        spatial = municipal_rules.sanitize_spatial(
            {"well_from": "W01", "well_to": "W02", "pipe_system": "雨水", "stake_start": "K0+120"},
            "排水管道",
        )
        self.assertEqual(spatial["well_from"], "W01")
        self.assertEqual(spatial["well_to"], "W02")
        self.assertNotIn("stake_start", spatial)
        road = municipal_rules.sanitize_spatial({"stake_start": "K0+120", "stake_end": "K0+180", "side": "左幅"}, "城镇道路")
        self.assertEqual(road["stake_start"], "K0+120")
        self.assertEqual(road["side"], "左幅")

    def test_skeleton_separates_bridge_options_and_pipe_tests(self):
        bridge = {item["name"]: item for item in municipal_rules.DIVISION_SKELETON["城市桥梁"]["divisions"]}
        self.assertIn("简支梁桥不强制", bridge["索塔"]["optional_note"])
        self.assertIn("简支梁桥不强制", bridge["锚碇"]["optional_note"])
        water_items = {name for division in municipal_rules.DIVISION_SKELETON["给水管道"]["divisions"] for name in division["items"]}
        drain_items = {name for division in municipal_rules.DIVISION_SKELETON["排水管道"]["divisions"] for name in division["items"]}
        self.assertIn("冲洗消毒", water_items)
        self.assertNotIn("冲洗消毒", drain_items)
        self.assertIn("闭水试验", drain_items)
        self.assertNotIn("闭水试验", water_items)
        self.assertIn("工作井", water_items)
        structure_names = [item["name"] for item in municipal_rules.DIVISION_SKELETON["给水排水构筑物"]["divisions"]]
        self.assertIn("主体结构", structure_names)
        self.assertNotIn("井段", structure_names)

    def test_precheck_reports_missing_concealment_without_claiming_acceptance(self):
        report = municipal_rules.precheck_photos([], expect_concealment=True, local_profile="shenzhen-2025")
        self.assertEqual(report["result"], "预检未通过")
        self.assertFalse(report["archivable"])
        self.assertIn("GB 55032-2022 第3.3.4条第4款", json.dumps(report, ensure_ascii=False))
        self.assertIn("不等于", report["statement"])
        self.assertIn("不证明现场事实", report["hash_limitation"])
        self.assertIn("备案后三个月", report["transfer_timing"])
        self.assertNotIn("竣工验收后三个月内移交全部", report["transfer_timing"])
        self.assertTrue(any("shenzhen-2025" in item["message"] and "不会自动启用" in item["message"] for item in report["issues"]))
        self.assertEqual(municipal_rules.local_profile_note(""), "")

    def test_duplicate_hash_is_warned_not_deleted_and_names_do_not_collide(self):
        raw = b"same-bytes"
        original = municipal_rules.intake_original_record(raw, "a.jpg", "desktop", False)
        photos = []
        for index in range(2):
            photos.append({
                "id": str(index),
                "photo_uuid": f"uuid-{index}",
                "title": "全景" if index == 0 else "近景",
                "photo_date": "2026-11-17",
                "photographer": "张三",
                "archive": {
                    "location_text": "人民路",
                    "concealment": "none",
                    "original": original,
                    "times": {"confirmed_capture": "2026-11-17", "exif_original": "2026-11-17 08:00", "uploaded_at": "2026-11-17 18:00"},
                },
            })
        report = municipal_rules.precheck_photos(photos)
        self.assertTrue(any("不自动删除" in item["message"] for item in report["issues"]))
        used = set()
        first = municipal_rules.unique_export_name("../秘密/a.jpg", used)
        second = municipal_rules.unique_export_name("../a.jpg", used)
        self.assertEqual(first, "a.jpg")
        self.assertEqual(second, "a-2.jpg")
        self.assertNotIn("..", first)

    def test_package_keeps_originals_out_of_derived_copies(self):
        raw = _jpeg_bytes()
        record = municipal_rules.intake_original_record(raw, "K0+120.jpg", "desktop", False)
        photo = {
            "photo_uuid": "p1",
            "id": "RD-001",
            "title": "人民路 K0+120—K0+180 左幅 路基",
            "photo_date": "2026-11-17",
            "photographer": "李四",
            "archive": {
                "location_text": "人民路左幅",
                "phase": "during",
                "concealment": "before_cover",
                "template_code": "SZ-0001",
                "acceptance": {"record_no": "YS-1"},
                "times": {"confirmed_capture": "2026-11-17", "exif_original": "2026:11:17 09:01:02", "uploaded_at": "2026-11-17 12:00:00"},
                "original": record,
            },
            "spatial": {"stake_start": "K0+120", "stake_end": "K0+180", "side": "左幅"},
            "leaf": {"item_code": "road-01-001", "item_name": "清表"},
        }
        package = municipal_export.build_package("道路一组", [photo], {"p1": raw})
        with zipfile.ZipFile(io.BytesIO(package)) as bundle:
            names = set(bundle.namelist())
            self.assertIn("目录.csv", names)
            self.assertIn("manifest.json", names)
            self.assertIn("预检报告.json", names)
            self.assertIn("利用副本/说明.txt", names)
            original_names = [name for name in names if name.startswith("原片/")]
            self.assertEqual(len(original_names), 1)
            self.assertEqual(bundle.read(original_names[0]), raw)
            manifest = json.loads(bundle.read("manifest.json"))
        self.assertEqual(manifest["fonds_number"], "")
        self.assertEqual(manifest["archive_number"], "")
        self.assertTrue(manifest["not_a_transfer"])
        self.assertTrue(manifest["not_an_acceptance"])
        self.assertEqual(manifest["catalog_count"], 1)
        self.assertEqual(manifest["original_count"], 1)
        self.assertEqual(manifest["files"][0]["sha256"], record["sha256"])
        derived = dict(photo)
        derived["archive"] = {**photo["archive"], "original": {**record, "status": "derived", "warning": "压缩副本"}}
        derived_package = municipal_export.build_package("缺原件", [derived], {"p1": raw})
        with zipfile.ZipFile(io.BytesIO(derived_package)) as bundle:
            self.assertFalse(any(name.startswith("原片/") for name in bundle.namelist()))
            report = json.loads(bundle.read("预检报告.json"))
        self.assertEqual(report["result"], "预检未通过")
        self.assertFalse(report["archivable"])


class MunicipalDesktopFlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("ALBUM_DATA_DIR", tempfile.mkdtemp(prefix="album-municipal-desktop-"))
        import app as desktop_app

        cls.desktop = desktop_app
        cls.client = desktop_app.app.test_client()
        cls._saved_files = {}
        for path in (
            desktop_app.ENGINEERING_PROJECTS_PATH,
            desktop_app.PROJECT_INFO_PATH,
            desktop_app.ENGINEERING_SETTINGS_PATH,
        ):
            cls._saved_files[path] = path.read_bytes() if path.exists() else None

    @classmethod
    def tearDownClass(cls):
        for path, payload in cls._saved_files.items():
            if payload is None:
                path.unlink(missing_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(payload)
        cls.desktop._ENGINEERING_READ_CACHE["sig"] = None
        cls.desktop._ENGINEERING_READ_CACHE["data"] = None
        cls.desktop.manager.invalidate_projects_cache()

    def setUp(self):
        with self.client.session_transaction() as session:
            session["username"] = "市政测试员"

    def _create(self, name, code, project_type, industry="市政工程"):
        return self.client.post("/api/engineering-projects", json={
            "project_name": name,
            "project_code": code,
            "industry": industry,
            "project_type": project_type,
            "delete_password": "Muni7286",
        })

    def test_three_end_template_and_project_type_roundtrip(self):
        created = self._create("市政道路工程", f"SZ-{uuid.uuid4().hex[:8]}", "道路工程")
        self.assertEqual(created.status_code, 200, created.get_json())
        info = created.get_json()["project_info"]
        self.assertEqual(info["industry"], "市政工程")
        self.assertEqual(info["project_type"], "城镇道路")
        self.assertEqual(info["project_type_code"], "road")
        self.assertEqual(info["rule_version"], municipal_rules.RULE_VERSION)
        unknown = self._create("未知市政", f"SZ-BAD-{uuid.uuid4().hex[:6]}", "地铁工程")
        self.assertEqual(unknown.status_code, 400)
        template = self.client.get("/api/municipal/template").get_json()
        self.assertEqual(template["rule_version"], municipal_rules.RULE_VERSION)
        self.assertEqual(template["local_profiles_enabled"], [])
        water = self._create("老水利工程", f"SL-{uuid.uuid4().hex[:8]}", "河道治理", industry="水利工程")
        self.assertEqual(water.status_code, 200, water.get_json())
        self.assertEqual(water.get_json()["project_info"]["industry"], "水利工程")
        self.assertEqual(professional_templates_requirements_for_water(), [])

    def test_municipal_import_item_nodes_skip_water_matcher_and_keep_legacy_units(self):
        created = self._create("桥梁工程", f"QL-{uuid.uuid4().hex[:8]}", "城市桥梁")
        self.assertEqual(created.status_code, 200, created.get_json())
        water_csv = "合同工程名称,单位工程名称,单位工程编码,分部工程名称,分部工程编码,单元工程名称,单元工程编码,关键词\n合同,单位,DW,分部,FB,混凝土灌注桩单元,UNIT-PILE-1,\n"
        rejected = self.client.post("/api/import-projects", data={"file": (io.BytesIO(water_csv.encode("utf-8")), "unit.csv")}, content_type="multipart/form-data")
        self.assertEqual(rejected.status_code, 400, rejected.get_json())
        self.assertIn("不能把水利单元", rejected.get_json()["error"])
        item_code = "QL-" + uuid.uuid4().hex[:8]
        municipal_csv = f"分项工程编码,分项工程名称,分部工程编码,分部工程名称,单位工程编码,单位工程名称,合同或标段名称\n{item_code},支座,QL-01,支座,QL,跨河桥,一标段\n"
        imported = self.client.post("/api/import-projects", data={"file": (io.BytesIO(municipal_csv.encode("utf-8")), "item.csv")}, content_type="multipart/form-data")
        self.assertEqual(imported.status_code, 200, imported.get_json())
        self.assertEqual(imported.get_json()["result"]["created"], 1, imported.get_json())
        project = self.desktop.manager.get_project(item_code)
        self.assertEqual(project["division_type"], "item")
        self.assertEqual(project["standard_unit_name"], "")
        self.assertNotIn("单元工程编码", project["source_fields"])
        self.assertFalse(self.desktop.is_pile_unit({"project_name": "灌注桩", "division_type": "item", "source_fields": {"节点类型": "item"}}))
        self.assertTrue(self.desktop.is_pile_unit({"project_name": "钻孔灌注桩单元工程", "division_type": "unit", "source_fields": {"单元工程编码": "DY-1"}}))
        legacy_code = "OLD-" + uuid.uuid4().hex[:8]
        legacy_dir = self.desktop.manager._project_dir(legacy_code)
        legacy_dir.mkdir(parents=True, exist_ok=True)
        (legacy_dir / "metadata.json").write_text(json.dumps({
            "project_code": legacy_code,
            "display_project_code": legacy_code,
            "project_name": "旧单元",
            "division_type": "unit",
            "photos": [{"id": "OLD-001", "photo_uuid": str(uuid.uuid4())}],
            "source_fields": {"节点类型": "unit", "单元工程编码": legacy_code, "单元工程名称": "旧单元", "工程项目ID": self.desktop.active_engineering_project_id()},
            "engineering_project_id": self.desktop.active_engineering_project_id(),
        }, ensure_ascii=False), encoding="utf-8")
        self.desktop.manager.invalidate_projects_cache()
        again = f"分项工程编码,分项工程名称,分部工程编码,分部工程名称,单位工程编码,单位工程名称\n{legacy_code},不应改名,QL-01,支座,QL,跨河桥\n"
        second = self.client.post("/api/import-projects", data={"file": (io.BytesIO(again.encode("utf-8")), "again.csv")}, content_type="multipart/form-data")
        self.assertEqual(second.status_code, 200, second.get_json())
        kept = json.loads((legacy_dir / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(kept["division_type"], "unit")
        self.assertEqual(kept["project_name"], "旧单元")
        self.assertEqual(kept["photos"][0]["id"], "OLD-001")

    def test_photo_archive_fields_survive_and_export_roundtrip(self):
        created = self._create("给水管网", f"GS-{uuid.uuid4().hex[:8]}", "给水管道")
        self.assertEqual(created.status_code, 200, created.get_json())
        item_code = "GS-" + uuid.uuid4().hex[:8]
        row = f"分项工程编码,分项工程名称,分部工程编码,分部工程名称,单位工程编码,单位工程名称\n{item_code},下管与接口,GS-02,预制管开槽施工主体结构,GS,给水\n"
        imported = self.client.post("/api/import-projects", data={"file": (io.BytesIO(row.encode("utf-8")), "pipe.csv")}, content_type="multipart/form-data")
        self.assertEqual(imported.status_code, 200, imported.get_json())
        raw = _jpeg_bytes()
        storage = FileStorage(stream=io.BytesIO(raw), filename="W01.jpg", content_type="image/jpeg")
        added = self.desktop.manager.add_photos(
            item_code,
            [storage],
            title="给水 J01—J02 接口",
            photo_date="2026-11-01",
            photographer="王五",
            per_file_meta={"W01.jpg": {
                "capture_source": "desktop",
                "spatial": {"well_from": "J01", "well_to": "J02", "pipe_system": "给水"},
                "archive": {
                    "template_code": "SZ-0105",
                    "phase": "during",
                    "concealment": "before_cover",
                    "location_text": "人民路",
                    "process_event": "接口安装",
                    "acceptance": {"record_no": "YS-JS-1", "title": "隐蔽验收"},
                    "times": {"exif_original": "2026:11:01 08:30:00", "confirmed_capture": "2026-11-01"},
                    "gps": {"status": "denied", "manual_place": "人民路"},
                },
            }},
        )
        photo = added[0]
        self.assertEqual(photo["spatial"]["well_from"], "J01")
        self.assertNotEqual(photo["archive"]["times"]["uploaded_at"][:10], "")
        self.assertEqual(photo["archive"]["times"]["exif_original"], "2026:11:01 08:30:00")
        self.assertEqual(photo["archive"]["times"]["confirmed_capture"], "2026-11-01")
        self.assertEqual(photo["archive"]["original"]["status"], "preserved")
        self.assertEqual(photo["archive"]["original"]["sha256"], __import__("hashlib").sha256(raw).hexdigest())
        self.assertNotEqual(photo["archive"]["times"]["uploaded_at"], photo["photo_date"])
        patched = self.client.patch(f"/api/photos/{item_code}/{photo['id']}", json={
            "photo_uuid": photo["photo_uuid"],
            "title": "给水 J01—J02 接口安装（覆土前）",
            "photo_date": "2026-11-01",
            "photographer": "王五",
            "archive": photo["archive"],
            "spatial": {"well_from": "J01", "well_to": "J02", "pipe_system": "给水"},
        })
        self.assertEqual(patched.status_code, 200, patched.get_json())
        self.assertEqual(patched.get_json()["photo"]["spatial"]["well_from"], "J01")
        self.assertEqual(patched.get_json()["photo"]["id"], photo["id"])
        snapshot = self.desktop.mobile_sync.build_project_snapshot(
            self.desktop.manager,
            self.desktop.current_engineering_project(),
            {"nodes": []},
        )
        leaves = []
        def walk(node):
            if isinstance(node, dict):
                leaves.extend(node.get("items") or [])
                leaves.extend(node.get("units") or [])
                for value in node.values():
                    if isinstance(value, list):
                        for child in value:
                            walk(child)
        for contract in snapshot["tree"]:
            walk(contract)
        item_codes = [item.get("item_code") for item in leaves]
        self.assertIn(item_code, item_codes)
        self.assertTrue(any(item.get("division_type") == "item" for item in leaves))
        found = self.client.get("/api/archive/search?well=J01").get_json()["photos"]
        self.assertTrue(any(item["photo_uuid"] == photo["photo_uuid"] for item in found))
        package = self.client.post("/api/archive-packages", json={"title": "给水组", "photo_ids": [photo["photo_uuid"]]})
        self.assertEqual(package.status_code, 200, package.data[:200])
        with zipfile.ZipFile(io.BytesIO(package.data)) as bundle:
            manifest = json.loads(bundle.read("manifest.json"))
            self.assertEqual(manifest["original_count"], 1)
            self.assertIn("不证明现场事实", manifest["hash_limitation"])
        water = self._create("水利排序", f"SL-PILE-{uuid.uuid4().hex[:6]}", "", industry="水利工程")
        self.assertEqual(water.status_code, 200, water.get_json())
        pile_code = "PILE-" + uuid.uuid4().hex[:8]
        self.desktop.manager.create_project(pile_code, "钻孔灌注桩单元工程", "", {"单元工程名称": "钻孔灌注桩单元工程", "单元工程编码": pile_code})
        stored = self.desktop.manager.get_project(pile_code)
        self.assertEqual(stored["division_type"], "unit")
        self.assertIn("灌注桩", stored.get("standard_unit_name", "") + stored["project_name"])
        self.assertTrue(self.desktop.is_pile_unit(stored))

    def test_industry_change_requires_confirmation_and_does_not_renumber(self):
        created = self._create("待改专业", f"CHG-{uuid.uuid4().hex[:8]}", "城镇道路")
        self.assertEqual(created.status_code, 200, created.get_json())
        project_id = created.get_json()["project_info"]["id"]
        item_code = "CHG-" + uuid.uuid4().hex[:8]
        row = f"分项工程编码,分项工程名称,分部工程编码,分部工程名称,单位工程编码,单位工程名称\n{item_code},路基,CHG-01,路基,CHG,道路\n"
        self.assertEqual(self.client.post("/api/import-projects", data={"file": (io.BytesIO(row.encode("utf-8")), "chg.csv")}, content_type="multipart/form-data").status_code, 200)
        before = self.desktop.manager.get_project(item_code)
        denied = self.client.post("/api/project-info", json={
            "id": project_id,
            "project_name": "待改专业",
            "project_code": created.get_json()["project_info"]["project_code"],
            "industry": "水利工程",
            "project_type": "河道治理",
            "delete_password": "",
        })
        self.assertEqual(denied.status_code, 409, denied.get_json())
        kept = self.desktop.manager.get_project(item_code)
        self.assertEqual(kept["division_type"], before["division_type"])
        self.assertEqual(kept.get("photos"), before.get("photos"))
        confirmed = self.client.post("/api/project-info", json={
            "id": project_id,
            "project_name": "待改专业",
            "industry": "水利工程",
            "project_type": "河道治理",
            "confirm_industry_change": True,
        })
        self.assertEqual(confirmed.status_code, 200, confirmed.get_json())
        self.assertEqual(self.desktop.manager.get_project(item_code)["division_type"], "item")

    def test_published_print_and_quota_constants_stay(self):
        self.assertEqual(self.desktop.DEFAULT_ENGINEERING_SETTINGS["print_margin_top_mm"], 20.0)
        self.assertEqual(self.desktop.DEFAULT_ENGINEERING_SETTINGS["print_margin_right_mm"], 20.0)
        self.assertEqual(self.desktop.DEFAULT_ENGINEERING_SETTINGS["print_margin_bottom_mm"], 20.0)
        self.assertEqual(self.desktop.DEFAULT_ENGINEERING_SETTINGS["print_margin_left_mm"], 20.0)
        self.assertEqual(self.desktop.SIDE_LABEL_MARGIN_MM, 8.0)
        self.assertEqual(self.desktop.SIDE_LABEL_SEPARATOR_MM, 2.0)
        from server import config
        self.assertEqual(config.DEFAULT_PRODUCT_CONFIG["free"]["photo_limit"], 3000)
        self.assertEqual(config.DEFAULT_PRODUCT_CONFIG["pricing"]["monthly_price"], 39)
        self.assertEqual(config.DEFAULT_PRODUCT_CONFIG["pricing"]["lifetime_price"], 399)
        self.assertEqual(config.DEFAULT_PRODUCT_CONFIG["mini_program"]["free_upload_limit"], 500)

    def test_browser_gzip_matches_frontend_source(self):
        source = ROOT / "assets" / "app-A20260910-2.92.js"
        packed = Path(str(source) + ".gz")
        self.assertTrue(packed.is_file())
        self.assertEqual(gzip.decompress(packed.read_bytes()), source.read_bytes())


def professional_templates_requirements_for_water():
    import professional_templates
    professional_templates.load_template_db.cache_clear()
    return professional_templates.requirements("水利工程", "水闸")


class MunicipalServerRoundtripTest(unittest.TestCase):
    def test_snapshot_item_upload_keeps_archive_and_blocks_other_project(self):
        from server import app as server_app
        from server import config, db

        temp = tempfile.TemporaryDirectory(prefix="album-municipal-server-")
        self.addCleanup(temp.cleanup)
        old = {
            "DATA_DIR": config.DATA_DIR,
            "DB_PATH": config.DB_PATH,
            "MOBILE_STORAGE_BACKEND": config.MOBILE_STORAGE_BACKEND,
            "MOBILE_STORAGE_DIR": config.MOBILE_STORAGE_DIR,
            "WECHAT_MOCK_ENABLED": config.WECHAT_MOCK_ENABLED,
        }
        config.DATA_DIR = Path(temp.name)
        config.DB_PATH = Path(temp.name) / "server.db"
        config.MOBILE_STORAGE_BACKEND = "local"
        config.MOBILE_STORAGE_DIR = Path(temp.name) / "objects"
        config.WECHAT_MOCK_ENABLED = True
        self.addCleanup(lambda: [setattr(config, key, value) for key, value in old.items()])
        server_app._rate_hits.clear()
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        old_signer = server_app.signer
        server_app.signer = server_app.LicenseSigner(Path(temp.name) / "key")
        server_app.signer._key = Ed25519PrivateKey.generate()
        self.addCleanup(lambda: setattr(server_app, "signer", old_signer))
        app = server_app.create_app()
        app.config["TESTING"] = True
        client = app.test_client()
        client.post("/api/register", json={"username": "muni_owner", "password": "MuniOwner2026"})
        client.post("/api/register", json={"username": "other_owner", "password": "OtherOwner2026"})
        token = client.post("/api/login", json={"username": "muni_owner", "password": "MuniOwner2026"}).get_json()["token"]
        other = client.post("/api/login", json={"username": "other_owner", "password": "OtherOwner2026"}).get_json()["token"]
        conn = db.connect()
        account_id = conn.execute("SELECT id FROM accounts WHERE username = 'muni_owner'").fetchone()["id"]
        other_id = conn.execute("SELECT id FROM accounts WHERE username = 'other_owner'").fetchone()["id"]
        conn.execute("INSERT INTO machines (account_id, machine_id, active) VALUES (?, 'MACHINE-M', 1)", (account_id,))
        conn.execute("INSERT INTO machines (account_id, machine_id, active) VALUES (?, 'MACHINE-O', 1)", (other_id,))
        conn.execute("INSERT INTO licenses(account_id,license_type,valid_days,active) VALUES (?,'lifetime',0,1)", (account_id,))
        conn.commit()
        conn.close()
        desktop = client.post("/api/activate", json={"machine_id": "MACHINE-M"}, headers={"Authorization": "Bearer " + token}).get_json()["desktop_sync_token"]
        other_desktop = client.post("/api/activate", json={"machine_id": "MACHINE-O"}, headers={"Authorization": "Bearer " + other}).get_json()["desktop_sync_token"]
        snapshot = {
            "snapshot_id": str(uuid.uuid4()),
            "revision": 3,
            "desktop_machine_id": "MACHINE-M",
            "project": {
                "id": "municipal-1",
                "project_code": "SZ",
                "project_name": "市政道路",
                "industry": "市政工程",
                "project_type": "城镇道路",
                "rule_version": municipal_rules.RULE_VERSION,
            },
            "tree": [{
                "code": "SEC-1",
                "name": "一标段",
                "unit_projects": [{
                    "code": "DW-ROAD",
                    "name": "人民路",
                    "parts": [{
                        "code": "FB-BASE",
                        "name": "路基",
                        "items": [{"item_code": "FX-001", "name": "清表", "division_type": "item"}],
                    }],
                }],
            }],
            "requirements": [{
                "template_code": "SZ-ROAD-HIDE",
                "industry": "市政工程",
                "project_type": "城镇道路",
                "phase": "施工阶段",
                "division": "路基",
                "process": "清表",
                "photo_requirement_name": "隐蔽前现场影像",
                "required_type": "required",
                "before_concealment_required": "是",
                "standard_source": municipal_rules.CONCEALMENT_CLAUSE,
                "min_photo_count": 1,
            }],
        }
        saved = client.post("/api/desktop/v1/project-snapshot", json=snapshot, headers={"Authorization": "Bearer " + desktop})
        self.assertEqual(saved.status_code, 200, saved.get_json())
        login = client.post("/api/mobile/v1/auth/wechat-login", json={"code": "muni-wechat", "app_id": "wx-muni"})
        bound = client.post("/api/mobile/v1/auth/wechat-bind", json={
            "binding_ticket": login.get_json()["binding_ticket"],
            "username": "muni_owner",
            "password": "MuniOwner2026",
        })
        mobile = bound.get_json()["token"]
        tree = client.get("/api/mobile/v1/projects/municipal-1/tree", headers={"Authorization": "Bearer " + mobile})
        self.assertEqual(tree.status_code, 200, tree.get_json())
        flat = json.dumps(tree.get_json()["tree"], ensure_ascii=False)
        self.assertIn("FX-001", flat)
        self.assertIn("item", flat)
        rules = client.get("/api/mobile/v1/projects/municipal-1/requirements", headers={"Authorization": "Bearer " + mobile}).get_json()
        self.assertEqual(rules["requirements"][0]["rule_level"], "national_mandatory")
        missing = client.post("/api/mobile/v1/batches", json={
            "client_batch_id": str(uuid.uuid4()),
            "project_id": "municipal-1",
            "scope": "engineering",
            "category": "construction",
            "mode": "direct",
            "assignment": {"item_code": "FX-MISSING"},
        }, headers={"Authorization": "Bearer " + mobile})
        self.assertEqual(missing.status_code, 404, missing.get_json())
        self.assertIn("不会被删除", missing.get_json()["error"])
        batch = client.post("/api/mobile/v1/batches", json={
            "client_batch_id": str(uuid.uuid4()),
            "project_id": "municipal-1",
            "scope": "engineering",
            "category": "construction",
            "mode": "direct",
            "assignment": {
                "item_code": "FX-001",
                "archive": {
                    "phase": "during",
                    "concealment": "before_cover",
                    "location_text": "人民路 K0+120",
                    "template_code": "SZ-ROAD-HIDE",
                    "times": {"exif_original": "2026:11:02 07:00:00", "confirmed_capture": "2026-11-02"},
                    "gps": {"status": "denied", "manual_place": "人民路"},
                    "acceptance": {"record_no": "YS-9"},
                },
                "spatial": {"stake_start": "K0+120", "side": "左幅"},
            },
            "requirement": {"template_code": "SZ-ROAD-HIDE"},
        }, headers={"Authorization": "Bearer " + mobile})
        self.assertEqual(batch.status_code, 201, batch.get_json())
        assignment = batch.get_json()["batch"]["assignment"]
        self.assertEqual(assignment["item_code"], "FX-001")
        self.assertEqual(assignment["part_name"], "路基")
        self.assertEqual(assignment["archive"]["times"]["exif_original"], "2026:11:02 07:00:00")
        self.assertEqual(assignment["spatial"]["stake_start"], "K0+120")
        self.assertEqual(assignment["gps"]["status"] if False else assignment["archive"]["gps"]["status"], "denied")
        other_view = client.get("/api/mobile/v1/projects/municipal-1/tree", headers={"Authorization": "Bearer " + other})
        self.assertIn(other_view.status_code, {403, 404})
        other_snapshot = client.post("/api/desktop/v1/project-snapshot", json={
            **snapshot,
            "snapshot_id": str(uuid.uuid4()),
            "revision": 1,
            "desktop_machine_id": "MACHINE-O",
            "project": {**snapshot["project"], "id": "other-project", "project_name": "别人的工程"},
        }, headers={"Authorization": "Bearer " + other_desktop})
        self.assertEqual(other_snapshot.status_code, 200, other_snapshot.get_json())
        own_after = client.get("/api/mobile/v1/projects/municipal-1/requirements", headers={"Authorization": "Bearer " + mobile})
        self.assertEqual(own_after.status_code, 200)
        self.assertEqual(own_after.get_json()["requirements"][0]["template_code"], "SZ-ROAD-HIDE")
