import copy
import unittest

import highway_rules as rules


def row(**changes):
    result = dict(zip(rules.REQUIRED_HEADERS, ("路基工程", "001", "路基土石方工程", "01", "土方路基", "001-01-001")))
    result.update(changes)
    return result


class HighwayRulesTests(unittest.TestCase):
    def test_industry_is_independent(self):
        for value in ("公路", "公路工程", "highway"):
            self.assertTrue(rules.is_highway_name(value))
        for value in ("市政工程", "城镇道路", "水利工程"):
            self.assertFalse(rules.is_highway_name(value))

    def test_type_requires_explicit_supported_choice(self):
        for value in ("", "机电工程", "公路养护", "未知"):
            with self.assertRaises(rules.HighwayRuleError):
                rules.canonical_project_type(value)
        self.assertEqual(rules.canonical_project_type("桥梁工程"), "桥梁工程")

    def test_preserves_original_code_and_does_not_mutate(self):
        source = row(起点桩号="K001+002", 左右幅="左幅", 分项工程编码="合同一·001/土方")
        before = copy.deepcopy(source)
        result = rules.validate_import_records([source])[0]
        self.assertEqual(source, before)
        self.assertEqual(result["单位工程编码"], "001")
        self.assertEqual(result["分项工程编码"], source["分项工程编码"])
        self.assertEqual(result["起点桩号"], "K001+002")
        self.assertEqual(result["节点类型"], "item")
        self.assertEqual(result["工程专业"], "公路工程")

    def test_all_errors_reported_before_return(self):
        with self.assertRaises(rules.HighwayRuleError) as caught:
            rules.validate_import_records([row(单位工程编码=""), row(分项工程编码="", 分部工程名称="")])
        self.assertEqual({e["row"] for e in caught.exception.errors}, {2, 3})

    def test_water_unit_not_relabelled(self):
        with self.assertRaises(rules.HighwayRuleError):
            rules.validate_import_records([row(单元工程编码="old")])

    def test_duplicate_item_not_renumbered(self):
        with self.assertRaises(rules.HighwayRuleError):
            rules.validate_import_records([row(), row()])

    def test_same_item_code_allowed_under_different_parents(self):
        for changes in ({"合同或标段名称": "第二合同"}, {"单位工程编码": "002"},
                        {"分部工程编码": "02"},
                        {"子分部工程名称": "第二涵洞", "子分部工程编码": "H2", "划分依据": "批准表"}):
            with self.subTest(changes=changes):
                result = rules.validate_import_records([row(), row(**changes)])
                self.assertEqual(len(result), 2)
                self.assertEqual(result[0]["分项工程编码"], result[1]["分项工程编码"])
                self.assertNotEqual(rules.storage_code(result[0], "p1"), rules.storage_code(result[1], "p1"))

    def test_storage_code_safe_stable_and_project_scoped(self):
        source = row(合同或标段名称="A/B\\C", 分项工程编码='  ../001:*?"<>|\\/土方  ')
        result = rules.validate_import_records([source])[0]
        self.assertEqual(result["分项工程编码"], source["分项工程编码"])
        identifier = rules.storage_code(result, "工程1")
        self.assertRegex(identifier, r"^GL-[0-9a-f]{32}$")
        self.assertEqual(identifier, rules.storage_code(dict(reversed(list(result.items()))), "工程1"))
        self.assertNotEqual(identifier, rules.storage_code(result, "工程2"))
        result["分项工程名称"] = "修订名称"
        self.assertEqual(identifier, rules.storage_code(result, "工程1"))

    def test_long_codes_not_truncated(self):
        value = "码/" * 1000
        result = rules.validate_import_records([row(分项工程编码=value), row(分项工程编码=value + "1")])
        self.assertEqual(result[0]["分项工程编码"], value)
        self.assertNotEqual(rules.storage_code(result[0], "p"), rules.storage_code(result[1], "p"))
        self.assertEqual(len(rules.storage_code(result[0], "p")), 35)

    def test_identity_separates_levels_without_delimiter_collisions(self):
        first = row(单位工程编码="A/B", 分部工程编码="C")
        second = row(单位工程编码="A", 分部工程编码="B/C")
        self.assertEqual(rules.division_identity(first), ("", "A/B", "C", "", "001-01-001"))
        self.assertNotEqual(rules.storage_code(first, "p"), rules.storage_code(second, "p"))
        self.assertNotEqual(rules.storage_code(row(分项工程编码="ABC"), "p"),
                            rules.storage_code(row(分项工程编码="abc"), "p"))

    def test_project_subdivision_requires_basis(self):
        with self.assertRaises(rules.HighwayRuleError):
            rules.validate_import_records([row(子分部工程名称="1号涵洞", 子分部工程编码="H01")])
        result = rules.validate_import_records([row(子分部工程名称="1号涵洞", 子分部工程编码="H01", 划分依据="项目批准划分表")])
        self.assertEqual(result[0]["子分部工程编码"], "H01")

    def test_parent_code_conflict(self):
        with self.assertRaises(rules.HighwayRuleError):
            rules.validate_import_records([row(), row(分项工程编码="002", 分部工程名称="排水工程")])

    def test_number_alias_and_empty_rows(self):
        value = row()
        value["单位工程编号"] = value.pop("单位工程编码")
        self.assertEqual(len(rules.validate_import_records([{}, value])), 1)
        self.assertEqual(rules.preserve_code_text(1.0), "1")
        self.assertEqual(rules.preserve_code_text("001.0"), "001.0")
        with self.assertRaises(rules.HighwayRuleError):
            rules.validate_import_records([])

    def test_template_has_no_forced_photos_or_water_level(self):
        doc = rules.template_document()
        self.assertEqual(doc["hierarchy"], ["单位工程", "分部工程", "分项工程"])
        self.assertEqual(doc["requirements"], [])
        self.assertEqual(doc["checklist_status"], "project_config")

    def test_precheck_requires_preserved_original_hash(self):
        for original in ({}, {"status": "preserved"}, {"status": "preview", "sha256": "a"}):
            self.assertFalse(rules.precheck_photos([{"archive": {"original": original}}])["archivable"])
        self.assertTrue(rules.precheck_photos([{"archive": {"original": {"status": "preserved", "sha256": "a"}}}])["archivable"])
        self.assertFalse(rules.precheck_photos([])["archivable"])

    def test_precheck_never_claims_municipal_compliance(self):
        result = rules.precheck_photos([{"archive": {"concealment": "before_cover"}}], expect_concealment=True)
        self.assertNotIn("GB55032", str(result))
        self.assertNotIn("三个月", str(result))
        self.assertIn("不等于", result["statement"])


if __name__ == "__main__":
    unittest.main()
