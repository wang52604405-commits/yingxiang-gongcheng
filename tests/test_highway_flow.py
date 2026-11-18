import csv
import io
import json
import os
import tempfile
import unittest
import uuid
import zipfile

os.environ.setdefault('ALBUM_DATA_DIR', tempfile.mkdtemp(prefix='highway-test-'))
import app
import highway_rules
import municipal_export
import professional_templates


class HighwayFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.saved = {p: p.read_bytes() if p.exists() else None for p in
                     (app.ENGINEERING_PROJECTS_PATH, app.PROJECT_INFO_PATH, app.ENGINEERING_SETTINGS_PATH)}

    @classmethod
    def tearDownClass(cls):
        for path, content in cls.saved.items():
            if content is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(content)
        app._ENGINEERING_READ_CACHE["sig"] = None
        app._ENGINEERING_READ_CACHE["data"] = None
        app.manager.invalidate_projects_cache()

    def setUp(self):
        self.client = app.app.test_client()
        with self.client.session_transaction() as session:
            session['username'] = '公路测试员'
        response = self.client.post('/api/engineering-projects', json={
            'project_name': '公路试验', 'project_code': 'GL-' + uuid.uuid4().hex[:8],
            'industry': '公路工程', 'project_type': next(iter(highway_rules.PROJECT_TYPES)),
            'delete_password': 'Highway7286'})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()['project_info']['industry_code'], 'highway')

    def row(self, code='001'):
        return {'合同或标段名称':'第一合同段', '单位工程名称':'路基工程', '单位工程编码':'01',
                '分部工程名称':'路基土石方工程', '分部工程编码':'01-01',
                '分项工程名称':'土方路基', '分项工程编码':code, '起点桩号':'K0+000', '终点桩号':'K1+000'}

    def test_import_preserves_codes_and_uses_items(self):
        row = self.row()
        result = app.manager.import_projects_from_records([row])
        self.assertEqual(result['created'], 1)
        project = app.manager.list_projects()[0]
        self.assertEqual(project['source_fields']['工程专业'], '公路工程')
        self.assertEqual(project['source_fields']['分项工程编码'], '001')
        self.assertNotIn('单元工程编码', project['source_fields'])
        hierarchy = app.manager.project_hierarchy(project)
        self.assertEqual(hierarchy['node_kind'], 'item')
        self.assertEqual(hierarchy['unit_code'], '')
        self.assertEqual(hierarchy['item_code'], '001')
        before = app.manager._metadata_path(project['project_code']).read_bytes()
        with self.assertRaisesRegex(ValueError, '不同名称'):
            app.manager.import_projects_from_records([dict(row, 分项工程名称='不得覆盖')])
        result = app.manager.import_projects_from_records([row])
        self.assertEqual(result['skipped'], 1)
        self.assertEqual(app.manager._metadata_path(project['project_code']).read_bytes(), before)
        exported = self.client.get('/api/engineering-division.csv').data.decode('utf-8-sig')
        self.assertIn('分项工程编码', exported)
        self.assertNotIn('单元工程编码', exported)
        self.assertIn('001', exported)

    def test_xlsx_and_mobile_snapshot_keep_highway_item_identity(self):
        from openpyxl import Workbook
        import mobile_sync
        row = self.row('0007')
        with tempfile.TemporaryDirectory() as directory:
            path = __import__('pathlib').Path(directory) / 'division.xlsx'
            book = Workbook()
            book.active.append(list(row))
            book.active.append(list(row.values()))
            book.save(path)
            book.close()
            self.assertEqual(app.manager.import_projects_from_xlsx(path)['created'], 1)
        snapshot = mobile_sync.build_project_snapshot(app.manager, app.current_engineering_project(), {'nodes': []})
        part = snapshot['tree'][0]['unit_projects'][0]['parts'][0]
        self.assertEqual(part['display_code'], '01-01')
        self.assertEqual(part['items'][0]['display_code'], '0007')
        self.assertTrue(part['items'][0]['item_code'].startswith('GL-'))
        self.assertFalse(part.get('units'))
        project = app.manager.list_projects()[0]
        assignment = mobile_sync._desktop_engineering_assignment(project['project_code'], project, app.manager.project_hierarchy(project), {})
        self.assertEqual(assignment['item_code'], project['project_code'])
        self.assertEqual(assignment['item_display_code'], '0007')
        self.assertEqual(assignment['unit_code'], '')

    def test_original_codes_and_duplicate_local_codes_are_preserved(self):
        rows = [self.row('A/B'), self.row('A-B'), self.row('X' * 101), dict(self.row('A/B'), 分部工程编码='02')]
        result = app.manager.import_projects_from_records(rows)
        self.assertEqual(result['created'], 4)
        projects = app.manager.list_projects()
        self.assertEqual(len({p['project_code'] for p in projects}), 4)
        self.assertEqual(sorted(p['display_project_code'] for p in projects), sorted(r['分项工程编码'] for r in rows))
        before = {p['project_code']: app.manager._metadata_path(p['project_code']).read_bytes() for p in projects}
        self.assertEqual(app.manager.import_projects_from_records(rows)['skipped'], 4)
        for code, content in before.items():
            self.assertEqual(app.manager._metadata_path(code).read_bytes(), content)

    def test_ambiguous_folder_original_code_cannot_select_first_leaf(self):
        app.manager.import_projects_from_records([self.row('001'), dict(self.row('001'), 分部工程编码='02')])
        project, _ = app.match_folder_to_project('001')
        self.assertIsNone(project)
        project, _ = app.match_folder_to_project('土方路基')
        self.assertIsNone(project)
        explicit = app.manager.list_projects()[1]['project_code']
        project, _ = app.match_folder_to_project(explicit)
        self.assertEqual(project['project_code'], explicit)

    def test_conflicting_parent_name_across_imports_is_rejected_without_write(self):
        app.manager.import_projects_from_records([self.row('001')])
        before = {p['project_code']: app.manager._metadata_path(p['project_code']).read_bytes() for p in app.manager.list_projects()}
        with self.assertRaisesRegex(ValueError, '不同名称'):
            app.manager.import_projects_from_records([dict(self.row('002'), 分部工程名称='另一分部名称')])
        self.assertEqual(len(app.manager.list_projects()), 1)
        for code, content in before.items():
            self.assertEqual(app.manager._metadata_path(code).read_bytes(), content)

    def test_blank_optional_subdivision_code_is_rejected(self):
        with self.assertRaises(ValueError):
            app.manager.import_projects_from_records([dict(self.row(), 子分部工程名称='桥跨', 子分部工程编码='   ', 划分依据='批准划分表')])
        self.assertEqual(app.manager.list_projects(), [])

    def test_batch_invalid_no_partial_writes(self):
        with self.assertRaises(ValueError):
            app.manager.import_projects_from_records([self.row(), dict(self.row('002'), 分部工程名称='')])
        self.assertEqual(app.manager.list_projects(), [])

    def test_long_original_code_keeps_distinct_photo_filenames(self):
        app.manager.import_projects_from_records([self.row('X' * 130)])
        project = app.manager.list_projects()[0]
        data = app.manager.get_project(project['project_code'])
        first = app.manager._archive_id_for_photo(data, {}, 'construction', 1)
        second = app.manager._archive_id_for_photo(data, {}, 'construction', 2)
        self.assertNotEqual(app.manager._photo_filename('construction', first, '.jpg'), app.manager._photo_filename('construction', second, '.jpg'))
        self.assertEqual(data['display_project_code'], 'X' * 130)

    def test_non_filename_code_still_has_safe_photo_number(self):
        app.manager.import_projects_from_records([self.row('///')])
        project = app.manager.list_projects()[0]
        data = app.manager.get_project(project['project_code'])
        number = app.manager._archive_id_for_photo(data, {}, 'construction', 1)
        self.assertTrue(number.startswith(project['project_code']))
        self.assertEqual(data['display_project_code'], '///')
        self.assertEqual(data['source_fields']['分项工程编码'], '///')

    def test_bare_project_api_cannot_bypass_scoped_import(self):
        response = self.client.post('/api/projects', json={'project_code':'001', 'project_name':'土方路基'})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(app.manager.list_projects(), [])

    def test_rule_version_only_carries_within_same_specialty(self):
        payload = {'industry':'公路工程', 'project_type':'公路综合土建'}
        self.assertEqual(app._normalize_project_specialty(payload, {'industry':'市政工程','rule_version':'M-old'})[2], highway_rules.RULE_VERSION)
        self.assertEqual(app._normalize_project_specialty(payload, {'industry':'公路工程','rule_version':'H-old'})[2], 'H-old')
        upgraded = dict(payload, confirm_template_upgrade=True)
        self.assertEqual(app._normalize_project_specialty(upgraded, {'industry':'公路工程','rule_version':'H-old'})[2], highway_rules.RULE_VERSION)

    def test_no_municipal_mandatory_rules_or_fallback(self):
        summary = professional_templates.plan_summary('公路工程', next(iter(highway_rules.PROJECT_TYPES)))
        self.assertEqual(summary['total'], 0)
        self.assertNotIn('55032', summary['rule_notice'])
        self.assertEqual(summary['checklist_status'], 'project_config')
        self.assertEqual(self.client.get('/api/highway/template').status_code, 200)
        self.assertEqual(self.client.get('/api/highway/division-template.csv').status_code, 200)
        with self.assertRaises(ValueError):
            app._normalize_project_specialty({'industry':'公路工程','project_type':'水利水电'})

    def test_highway_package_has_no_municipal_claims(self):
        result = municipal_export.build_package('公路照片组', [], {}, rules=highway_rules)
        with zipfile.ZipFile(io.BytesIO(result)) as bundle:
            manifest = json.loads(bundle.read('manifest.json'))
            self.assertEqual(manifest['package_kind'], 'highway_photo_arrangement')
            self.assertNotIn('GB55032', json.dumps(manifest, ensure_ascii=False))
            self.assertNotIn('备案后三个月', json.dumps(manifest, ensure_ascii=False))
            self.assertTrue(manifest['not_an_acceptance'])

if __name__ == '__main__':
    unittest.main()
