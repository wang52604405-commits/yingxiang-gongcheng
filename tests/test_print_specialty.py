import importlib
import os
import tempfile
import unittest
from unittest.mock import patch


class PrintSpecialtyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='print-specialty-')
        os.environ.setdefault('ALBUM_DATA_DIR', cls.tmp.name)
        cls.mod = importlib.import_module('app')

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def project(self, kind):
        return {'project_code': 'internal', 'display_project_code': '001', 'project_name': {'unit': '水利单元名', 'item': '土方路基', 'batch': '第一检验批'}[kind], 'division_type': kind,
                'source_fields': {'节点类型': kind, '单元工程名称': '水利单元名' if kind == 'unit' else '', '分项工程名称': '土方路基', '检验批名称': '第一检验批' if kind == 'batch' else ''}}

    def test_side_labels_use_actual_node_name_never_photo_title(self):
        for kind, label in [('unit', '单元工程名称'), ('item', '分项工程名称'), ('batch', '检验批名称')]:
            with self.subTest(kind=kind), patch.object(self.mod, 'current_engineering_project', return_value={'industry': '公路工程'}):
                project = self.project(kind)
                slip = self.mod.side_label_for_photo({'title': '不同的照片题名'}, unit_project=project)
                self.assertEqual(slip['unit_name_label'], label)
                self.assertEqual(slip['unit_name'], project['project_name'])
                self.assertNotEqual(slip['unit_name'], slip['title'])

    def test_actual_print_template_labels_values_and_counts(self):
        for kind, word in [('unit', '单元'), ('item', '分项'), ('batch', '检验批')]:
            project = self.project(kind)
            with self.subTest(kind=kind), self.mod.app.test_request_context('/?style=sidelabel'), patch.object(self.mod, 'current_engineering_project', return_value={'industry': '公路工程'}):
                pages = self.mod.layout_side_label_pages([{'title': '现场照片', 'id': 'SY001', 'url': '/photo.jpg'}], project)
                html = self.mod.render_template('print.html', project=project, photos=[], project_groups=[{'level':'', 'project_name':project['project_name'], 'pages':pages}], category_label='施工单元影像', print_layout='portrait', print_page_size=2, print_settings={}, watermark_text='')
                self.assertIn(f'施工{word}影像：共 1 个{word}', html)
                self.assertIn(f'<b>{self.mod.print_leaf_name_label(project)}</b>', html)
                self.assertIn(project['project_name'], html)
                if kind != 'unit':
                    self.assertNotIn('<b>单元工程名称</b>', html)

    def test_regular_captions_use_leaf_name_and_preserve_custom_labels(self):
        project = self.project('batch')
        with patch.object(self.mod, 'read_engineering_settings', return_value={'photo_detail_fields':[{'label':'单元工程名称','source':'project_name'}]}):
            rows = self.mod.photo_detail_rows(project, {'project_name':'照片携带的旧名称'})
        self.assertEqual(rows, [{'label':'检验批名称','value':'第一检验批','source':'project_name'}])
        with patch.object(self.mod, 'read_engineering_settings', return_value={'photo_detail_fields':[{'label':'施工部位','source':'project_name'}]}):
            self.assertEqual(self.mod.photo_detail_rows(project, {})[0]['label'], '施工部位')

    def test_batch_book_uses_actual_selected_nodes_in_changed_specialty(self):
        from contextlib import ExitStack
        for kinds, expected in [(['unit'], '单元'), (['item'], '分项'), (['unit', 'item'], '工程节点'), (['batch', 'item'], '工程节点')]:
            projects = {str(i): self.project(kind) for i, kind in enumerate(kinds)}
            captured = {}
            def render(_template, **kwargs):
                captured.update(kwargs)
                return 'ok'
            with self.subTest(kinds=kinds), ExitStack() as stack:
                for name, value in [('expired_license_response', None), ('batch_print_permission_response', None), ('watermark_text_for_user', ''), ('current_engineering_project', {'industry':'公路工程'})]:
                    stack.enter_context(patch.object(self.mod, name, return_value=value))
                stack.enter_context(patch.object(self.mod.manager, 'get_project', side_effect=lambda code: projects[code]))
                stack.enter_context(patch.object(self.mod.manager, 'get_photos', return_value=[{'id':'p', 'category':'construction'}]))
                stack.enter_context(patch.object(self.mod, 'enrich_print_photos', side_effect=lambda p, rows, settings: rows))
                stack.enter_context(patch.object(self.mod, 'split_photos_by_level', side_effect=lambda p, rows: (rows, [])))
                stack.enter_context(patch.object(self.mod, 'layout_print_pages', side_effect=lambda rows, *a, **k: [rows]))
                stack.enter_context(patch.object(self.mod, 'remember_last_print_job'))
                stack.enter_context(patch.object(self.mod, 'render_template', side_effect=render))
                response = self.mod.app.test_client().get('/print/construction/batch?codes=' + ','.join(projects))
                self.assertEqual(response.status_code, 200, response.data)
                self.assertEqual(captured['project_groups'][0]['level'], expected + '照片')
                self.assertEqual(captured['leaf_label_override'], expected)

    def test_recent_upload_missing_unit_project_does_not_mislabel_leaf(self):
        project = self.project('batch')
        data = dict(project, photos=[{'id':'p','filename':'p.jpg','upload_time':'2026-11-18'}])
        with patch.object(self.mod, 'login_required_json', return_value=({'username':'tester'},None)), \
             patch.object(self.mod.manager, 'list_projects', return_value=[project]), \
             patch.object(self.mod.manager, 'get_project', return_value=data), \
             patch.object(self.mod.manager, '_thumb_url', return_value='/thumb.jpg'):
            response = self.mod.app.test_client().get('/api/recent-uploads')
        self.assertEqual(response.status_code, 200, response.data)
        row = response.get_json()['records'][0]
        self.assertEqual(row['unit'], '')
        self.assertEqual(row['project_name'], '第一检验批')
        self.assertEqual(row['node_kind'], 'batch')
