"""真实 HTTP 检验批原图往返；同原批码不能串父分项，旧分项照片不迁移。"""
import hashlib
import io
import unittest
import uuid

import mobile_sync
import municipal_rules
if __package__:
    from . import test_highway_scoped_identity as fixture
else:
    import test_highway_scoped_identity as fixture


class MunicipalBatchRoundtripTests(unittest.TestCase):
    def setUp(self):
        fixture.HighwayScopedIdentityTests.setUp(self)
        self.project = {
            'id': 'municipal-batch-roundtrip', 'project_code': 'SZ-BATCH', 'project_name': '市政批次试验',
            'industry': '市政工程', 'project_type': '城镇道路', 'rule_version': municipal_rules.RULE_VERSION,
            'cloud_owner_id': str(self.account_id),
        }
        self.manager = fixture.desktop.AlbumManager(self.root / 'municipal-batch-albums')
        self.rows = [{
            '合同或标段名称': '合同一', '单位工程名称': '道路', '单位工程编码': 'DW01',
            '分部工程名称': '路基', '分部工程编码': 'FB01', '分项工程名称': '填筑' + item,
            '分项工程编码': item,
        } for item in ('A', 'B')]
        self.assertEqual(self.manager.import_municipal_records(self.rows)['created'], 2)
        self.raw = fixture.support.jpeg_bytes((80, 60))
        self.legacy_uuid, self.legacy_path = self.add_desktop_photo('A', 'legacy.jpg')
        self.legacy_metadata = self.manager._metadata_path('A').read_bytes()
        self.assertEqual(self.manager.import_municipal_records([
            dict(row, 检验批编码='01', 检验批名称='第一批') for row in self.rows
        ])['created'], 2)
        self.assertEqual(self.manager._metadata_path('A').read_bytes(), self.legacy_metadata)
        self.batches = {p['source_fields']['分项工程编码']: p['project_code']
                        for p in self.manager.list_projects() if p['division_type'] == 'batch'}
        self.assertEqual(len(set(self.batches.values())), 2)
        self.service = mobile_sync.DesktopMobileSync(
            self.manager, self.cloud, lambda: dict(self.project), lambda: {'nodes': []},
            self.root / 'batch-state.json', self.root / 'batch-cache', machine_id_reader=lambda: 'MACHINE-A')
        result = self.service._sync_snapshot()
        self.assertTrue(result.get('ok'), result)

    def add_desktop_photo(self, code, filename):
        photo_uuid = str(uuid.uuid4())
        data = self.manager.get_project(code)
        data['photos'].append({'id': 'SY' + uuid.uuid4().hex[:8], 'photo_uuid': photo_uuid,
            'filename': filename, 'category': 'construction', 'title': '现场原片',
            'photo_date': '2026-11-01', 'process_name': '', 'sha256': hashlib.sha256(self.raw).hexdigest()})
        self.manager._write_metadata(code, data)
        path = self.manager._photos_dir(code) / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.raw)
        return photo_uuid, path

    def upload(self, code):
        response = self.client.post('/api/mobile/v1/batches', json={
            'client_batch_id': str(uuid.uuid4()), 'project_id': self.project['id'],
            'scope': 'engineering', 'category': 'construction', 'mode': 'direct',
            'assignment': {'item_code': code, 'parent_item_name': '不可信父名称'},
        }, headers=self.user_headers)
        self.assertEqual(response.status_code, 201, response.get_json())
        assignment = response.get_json()['batch']['assignment']
        self.assertEqual(assignment['item_code'], code)
        batch_id = response.get_json()['batch']['batch_id']
        photo_uuid = str(uuid.uuid4())
        uploaded = self.client.post(f'/api/mobile/v1/batches/{batch_id}/photos', data={
            'photo_uuid': photo_uuid, 'file': (io.BytesIO(self.raw), 'mobile.jpg'),
            'sha256': hashlib.sha256(self.raw).hexdigest(), 'original_size_bytes': str(len(self.raw)),
            'client_captured_at': '2026-11-01T08:00:00Z', 'auto_delivery': 'true',
        }, headers=self.user_headers, content_type='multipart/form-data')
        self.assertEqual(uploaded.status_code, 201, uploaded.get_json())
        committed = self.client.post(f'/api/mobile/v1/batches/{batch_id}/commit', headers=self.user_headers)
        self.assertEqual(committed.status_code, 200, committed.get_json())
        return photo_uuid, assignment

    def test_batch_and_parent_upload_download_backfill_preserve_separate_ownership(self):
        expected = {}
        # Reverse order catches implementations that select the first original batch code.
        for parent in ('B', 'A'):
            code = self.batches[parent]
            photo_uuid, assignment = self.upload(code)
            expected[photo_uuid] = code
            self.assertEqual(assignment['node_type'], 'batch')
            self.assertEqual(assignment['batch_code'], '01')
            self.assertEqual(assignment['item_display_code'], '01')
            self.assertEqual(assignment['parent_item_code'], parent)
            self.assertEqual(assignment['parent_item_name'], '填筑' + parent)
            self.assertEqual(assignment['unit_code'], '')
        parent_uuid, assignment = self.upload('A')
        expected[parent_uuid] = 'A'
        self.assertEqual(assignment['node_type'], 'item')
        result = self.service._sync_inbox()
        self.assertEqual(result.get('imported'), 3, result)
        for code in ('A', 'B', *self.batches.values()):
            photos = self.manager.get_project(code)['photos']
            for photo_uuid, target in expected.items():
                found = [p for p in photos if p.get('photo_uuid') == photo_uuid]
                self.assertEqual(len(found), 1 if code == target else 0)
                if found:
                    self.assertEqual((self.manager._photos_dir(code) / found[0]['filename']).read_bytes(), self.raw)
            legacy = [p for p in photos if p.get('photo_uuid') == self.legacy_uuid]
            self.assertEqual(len(legacy), 1 if code == 'A' else 0)
        legacy = next(p for p in self.manager.get_project('A')['photos'] if p.get('photo_uuid') == self.legacy_uuid)
        self.legacy_path = self.manager._photos_dir('A') / legacy['filename']
        self.assertEqual(self.legacy_path.read_bytes(), self.raw)
        desktop_uuid, desktop_path = self.add_desktop_photo(self.batches['B'], 'desktop-batch.jpg')
        result = self.service._sync_backfill()
        self.assertGreaterEqual(result.get('uploaded', 0), 2, result)
        for photo_uuid, code, kind in ((desktop_uuid, self.batches['B'], 'batch'), (self.legacy_uuid, 'A', 'item')):
            response = self.client.get(f'/api/mobile/v1/photos/{photo_uuid}', headers=self.user_headers)
            self.assertEqual(response.status_code, 200, response.get_json())
            assignment = response.get_json()['photo']['assignment']
            self.assertEqual(assignment['item_code'], code)
            self.assertEqual(assignment['node_type'], kind)
            if kind == 'batch':
                self.assertEqual(assignment['batch_code'], '01')
                self.assertEqual(assignment['parent_item_code'], 'B')
        self.assertEqual(desktop_path.read_bytes(), self.raw)
        self.assertEqual(self.legacy_path.read_bytes(), self.raw)


if __name__ == '__main__':
    unittest.main()
