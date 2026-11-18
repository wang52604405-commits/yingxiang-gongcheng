import json
import os
import sqlite3
import tempfile
import unittest
import uuid
from types import SimpleNamespace

os.environ.setdefault('ALBUM_DATA_DIR', tempfile.mkdtemp(prefix='municipal-batch-'))
import app
import municipal_rules
import mobile_sync
from server import mobile_api


class MunicipalBatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.saved = {p: p.read_bytes() if p.exists() else None for p in
                     (app.ENGINEERING_PROJECTS_PATH, app.PROJECT_INFO_PATH, app.ENGINEERING_SETTINGS_PATH)}

    @classmethod
    def tearDownClass(cls):
        for p, content in cls.saved.items():
            if content is None: p.unlink(missing_ok=True)
            else: p.write_bytes(content)
        app._ENGINEERING_READ_CACHE['sig'] = None
        app._ENGINEERING_READ_CACHE['data'] = None
        app.manager.invalidate_projects_cache()

    def setUp(self):
        self.client = app.app.test_client()
        with self.client.session_transaction() as session: session['username'] = '检验批测试'
        result = self.client.post('/api/engineering-projects', json={
            'project_name': '市政测试', 'project_code': 'M-' + uuid.uuid4().hex[:8],
            'industry': '市政工程', 'project_type': '城镇道路', 'delete_password': 'Batch7286'})
        self.assertEqual(result.status_code, 200)

    def row(self, batch='01', item='FX01'):
        return {'合同或标段名称': '合同一', '单位工程名称': '道路一', '单位工程编码': 'DW01',
                '分部工程名称': '路基', '分部工程编码': 'FB01', '分项工程名称': '填筑',
                '分项工程编码': item, '检验批名称': '填筑第一批', '检验批编码': batch}

    def snapshot(self):
        return mobile_sync.build_project_snapshot(app.manager, app.current_engineering_project(), {'nodes': []})

    def test_legacy_item_unchanged_and_batch_nested(self):
        legacy = self.row(); legacy.pop('检验批编码'); legacy.pop('检验批名称')
        app.manager.import_municipal_records([legacy])
        path = app.manager._metadata_path('FX01'); before = path.read_bytes()
        self.assertEqual(app.manager.import_municipal_records([self.row()])['created'], 1)
        self.assertEqual(path.read_bytes(), before)
        parent = self.snapshot()['tree'][0]['unit_projects'][0]['parts'][0]['items'][0]
        self.assertEqual(parent['item_code'], 'FX01')
        self.assertEqual(len(parent['batches']), 1)
        batch = parent['batches'][0]
        self.assertEqual(batch['display_code'], '01')
        self.assertTrue(batch['item_code'].startswith('MB-'))
        nodes = mobile_api._flatten_snapshot(self.snapshot()['tree'], [])
        batches = [n for n in nodes if n['node_type'] == 'batch']
        self.assertEqual(batches[0]['parent_code'], 'FX01')
        self.assertEqual(app.manager.import_municipal_records([self.row()])['skipped'], 1)
        self.assertEqual(path.read_bytes(), before)

    def test_duplicate_batch_codes_different_parents_preserved(self):
        self.assertEqual(app.manager.import_municipal_records([self.row('01','A'), self.row('01','B')])['created'], 2)
        projects = [p for p in app.manager.list_projects() if p["division_type"] == "batch"]
        self.assertEqual(len({p['project_code'] for p in projects}), 2)
        self.assertEqual([p['display_project_code'] for p in projects], ['01','01'])
        node = next(p for p in projects if p['source_fields']['分项工程编码'] == 'B')
        sync = SimpleNamespace(manager=app.manager)
        resolved = mobile_sync.DesktopMobileSync._resolve_inbox_target(sync, {'scope':'engineering','category':'construction','item_code':node['project_code']})
        self.assertEqual(resolved[0], node['project_code'])
        with self.assertRaises(ValueError):
            mobile_sync.DesktopMobileSync._resolve_inbox_target(sync, {'scope':'engineering','category':'construction','item_code':'01'})

    def test_later_parent_only_import_does_not_duplicate_or_modify(self):
        app.manager.import_municipal_records([self.row()])
        before = {p['project_code']: app.manager._metadata_path(p['project_code']).read_bytes() for p in app.manager.list_projects()}
        parent = self.row(); parent.pop('检验批名称'); parent.pop('检验批编码')
        self.assertEqual(app.manager.import_municipal_records([parent])['created'], 0)
        after = {p['project_code']: app.manager._metadata_path(p['project_code']).read_bytes() for p in app.manager.list_projects()}
        self.assertEqual(before, after)
        payload = self.client.get('/api/projects?slim=1').get_json()
        batch = next(p for p in payload['projects'] if p['division_type'] == 'batch')
        self.assertEqual(batch['source_fields']['检验批编码'], '01')
        self.assertEqual(batch['source_fields']['节点类型'], 'batch')

    def test_scoped_intermediate_codes_keep_two_units_separate(self):
        app.manager.import_municipal_records([self.row(), dict(self.row(), 单位工程名称='道路二', 单位工程编码='DW02')])
        nodes = mobile_api._flatten_snapshot(self.snapshot()['tree'], [])
        self.assertEqual(len({n['node_code'] for n in nodes}), len(nodes))
        self.assertEqual(len([n for n in nodes if n['node_type'] == 'part']), 2)
        self.assertEqual(len([n for n in nodes if n['node_type'] == 'item']), 2)
        batches = [n for n in nodes if n['node_type'] == 'batch']
        self.assertEqual(len(batches), 2)
        self.assertEqual({n['metadata']['display_code'] for n in batches}, {'01'})
        self.assertEqual(len({n['parent_code'] for n in batches}), 2)

    def test_cross_import_parent_name_conflict_has_no_writes(self):
        app.manager.import_municipal_records([self.row()])
        before = {p['project_code']: app.manager._metadata_path(p['project_code']).read_bytes() for p in app.manager.list_projects()}
        with self.assertRaises(ValueError):
            app.manager.import_municipal_records([dict(self.row('02'), 分部工程名称='另一个名称')])
        after = {p['project_code']: app.manager._metadata_path(p['project_code']).read_bytes() for p in app.manager.list_projects()}
        self.assertEqual(before, after)
        with self.assertRaises(ValueError):
            app.manager.import_municipal_records([dict(self.row(), 检验批名称='改名试图覆盖')])
        self.assertEqual(before, {p['project_code']: app.manager._metadata_path(p['project_code']).read_bytes() for p in app.manager.list_projects()})

    def test_invalid_batch_is_atomic(self):
        with self.assertRaises(ValueError):
            app.manager.import_municipal_records([self.row(), dict(self.row('02'), 检验批名称='')])
        self.assertEqual(app.manager.list_projects(), [])

    def test_server_resolves_trusted_parent_and_rejects_cross_project(self):
        app.manager.import_municipal_records([self.row()])
        nodes = mobile_api._flatten_snapshot(self.snapshot()['tree'], [])
        conn = sqlite3.connect(':memory:'); self.addCleanup(conn.close); conn.row_factory = sqlite3.Row
        conn.execute('CREATE TABLE cloud_units (account_id INTEGER, project_id TEXT, scope TEXT, node_code TEXT, parent_code TEXT, node_type TEXT, name TEXT, sort_order INTEGER, metadata_json TEXT, active INTEGER)')
        for n in nodes:
            conn.execute('INSERT INTO cloud_units VALUES (1,?,?,?,?,?,?,?,?,1)', ('project',n['scope'],n['node_code'],n['parent_code'],n['node_type'],n['name'],n['sort_order'],json.dumps(n['metadata'])))
        batch = next(n for n in nodes if n['node_type']=='batch')
        resolved = mobile_api._engineering_assignment(conn,1,'project',{'item_code':batch['node_code'], 'parent_item_name':'forged'},active_only=True,strict=True)
        self.assertEqual(resolved['node_type'],'batch')
        self.assertEqual(resolved['batch_code'],'01')
        self.assertEqual(resolved['parent_item_name'],'填筑')
        self.assertEqual(resolved['unit_code'],'')
        with self.assertRaises(mobile_api.ApiProblem):
            mobile_api._engineering_assignment(conn,2,'project',{'item_code':batch['node_code']},active_only=True,strict=True)
        rows = conn.execute('SELECT * FROM cloud_units').fetchall()
        tree = mobile_api._tree_from_rows(rows)
        wire = tree[0]['children'][0]['children'][0]['children'][0]['children'][0]
        self.assertEqual(wire['type'],'batch')
        self.assertEqual(wire['display_code'],'01')

if __name__ == '__main__': unittest.main()
