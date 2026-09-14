"""Performance guards preserve data/permissions; no production credentials or files."""
from __future__ import annotations
import hashlib
import io
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

class MetadataEditPerformanceTest(unittest.TestCase):
    def setUp(self):
        import app
        self.app = app
        self.temp = tempfile.TemporaryDirectory(prefix='album-perf-regression-')
        self.addCleanup(self.temp.cleanup)
        self.manager = app.AlbumManager(Path(self.temp.name))
        settings = patch.object(app, 'read_engineering_settings', return_value=dict(app.DEFAULT_ENGINEERING_SETTINGS))
        self.settings = settings.start(); self.addCleanup(settings.stop)
        owner = patch.object(app, 'project_matches_engineering', return_value=True)
        owner.start(); self.addCleanup(owner.stop)

    def seed(self, code='U-001', count=24, pile=False):
        from PIL import Image
        buf=io.BytesIO(); Image.new('RGB',(64,48),(70,120,135)).save(buf,'JPEG'); image=buf.getvalue()
        data={'project_code':code,'display_project_code':code,'project_name':'灌注桩单元' if pile else '底板单元',
              'processes':['钻孔','验收'],'source_fields':{},'photos':[]}
        m=self.manager; m._photos_dir(code).mkdir(parents=True); m._originals_dir(code).mkdir(parents=True)
        counts={}
        for i in range(count):
            cat='supervision' if i%4==3 else 'construction'; counts[cat]=counts.get(cat,0)+1
            pid=m._archive_id_for_photo(data,{'process_name':''},cat,counts[cat])
            name=m._photo_filename(cat,pid,'.jpg')
            (m._photos_dir(code)/name).write_bytes(image); (m._originals_dir(code)/name).write_bytes(image)
            data['photos'].append({'id':pid,'photo_uuid':f'{code}-uuid-{i}','filename':name,'original_backup':name,
               'original_name':f'{i+1}号桩钻孔.jpg','title':f'{i+1}号桩钻孔' if pile else f'底板照片{i}',
               'photo_date':'2026-09-01','photographer':'甲','description':'原说明','category':cat,
               'category_label':self.app.PHOTO_CATEGORY_LABELS[cat], 'orientation':'landscape','rotation':0,
               'process_name':'','process_code':''})
        m._write_metadata(code,data); m._renumber_after_change(code,data)
        return m.get_project(code)

    def hashes(self):
        return {str(p.relative_to(self.manager.root)):hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.manager.root.rglob('*.jpg')}

    def test_caption_edit_keeps_all_images_ids_order_and_uses_one_write(self):
        data=self.seed(count=240); before=self.hashes(); photos=data['photos']; photo=photos[0]
        ids=[(p['id'],p['photo_uuid'],p['filename']) for p in photos]
        m=self.manager; self.settings.reset_mock()
        with patch.object(m,'_renumber_after_change', wraps=m._renumber_after_change) as reorder, \
             patch.object(m,'_write_metadata', wraps=m._write_metadata) as write:
            m.update_photo('U-001',photo['id'],title='新版题名',photographer='乙',description='说明',rotation=90,
                           photo_date='2026-09-01',process_name='',process_code='')
            self.assertEqual(reorder.call_count,0)
            self.assertEqual(write.call_count,1)
        self.assertLessEqual(self.settings.call_count,2)
        after=m.get_project('U-001')['photos']
        self.assertEqual(ids,[(p['id'],p['photo_uuid'],p['filename']) for p in after])
        self.assertEqual(after[0]['title'],'新版题名'); self.assertEqual(after[0]['rotation'],90)
        self.assertEqual(before,self.hashes())

    def test_numbering_reads_settings_once_for_entire_unit(self):
        self.seed(count=240); data=self.manager.get_project('U-001')
        self.settings.reset_mock()
        self.manager._renumber_after_change('U-001',data)
        self.assertEqual(self.settings.call_count,1)

    def test_scope_move_still_reorders_and_preserves_uuid(self):
        photo=self.seed()['photos'][0]; uid=photo['photo_uuid']; m=self.manager
        with patch.object(m,'_renumber_after_change', wraps=m._renumber_after_change) as reorder:
            result=m.update_photo('U-001',photo['id'],process_name='钻孔')
            self.assertEqual(reorder.call_count,1)
        self.assertEqual(result['photo_uuid'],uid); self.assertEqual(result['process_code'],'GY001')
        self.assertIn('GY001',result['id'])

    def test_same_scope_editor_payload_does_not_force_reorder(self):
        photo=self.seed()['photos'][0]; m=self.manager
        photo=m.update_photo('U-001',photo['id'],process_name='钻孔')
        with patch.object(m,'_renumber_after_change', wraps=m._renumber_after_change) as reorder:
            result=m.update_photo('U-001',photo['id'],process_name='钻孔',photo_date='2026-09-01',description='新说明')
            self.assertEqual(reorder.call_count,0)
        self.assertEqual(result['process_code'],'GY001')

    def test_pile_edits_keep_existing_auto_sort_even_for_caption(self):
        data=self.seed(pile=True); m=self.manager; photo=data['photos'][0]
        with patch.object(m,'_renumber_after_change', wraps=m._renumber_after_change) as reorder:
            m.update_photo('U-001',photo['id'],title='99号桩混凝土',photo_date='2026-09-05')
            self.assertEqual(reorder.call_count,1)
        after=m.get_project('U-001')['photos']
        self.assertNotEqual([p['photo_uuid'] for p in data['photos']],[p['photo_uuid'] for p in after])
        target=next(p for p in after if p['photo_uuid']==photo['photo_uuid'])
        with patch.object(m,'_renumber_after_change', wraps=m._renumber_after_change) as reorder:
            m.update_photo('U-001',target['id'],description='仅改说明')
            self.assertEqual(reorder.call_count,1)

    def test_legacy_or_gapped_metadata_is_repaired_not_skipped(self):
        data=self.seed(); m=self.manager; photo=data['photos'][0]
        data['photos'][1]['id']='LEGACY-SY999'
        m._write_metadata('U-001',data)
        with patch.object(m,'_renumber_after_change', wraps=m._renumber_after_change) as reorder:
            m.update_photo('U-001',photo['id'],description='安全修复')
            self.assertEqual(reorder.call_count,1)
        self.assertNotIn('LEGACY-SY999',[p['id'] for p in m.get_photos('U-001')])

    def test_custom_policy_change_still_applies_on_edit(self):
        data=self.seed(); m=self.manager
        settings=dict(self.app.DEFAULT_ENGINEERING_SETTINGS)
        settings['numbering_rules']={k:dict(v) for k,v in self.app.DEFAULT_NUMBERING_RULES.items()}
        settings['numbering_rules']['construction'].update(unit_template='{code}-GC{seq}',start=5)
        self.settings.return_value=settings
        result=m.update_photo('U-001',data['photos'][0]['id'],description='新规则')
        self.assertEqual(result['id'],'U-001-GC005')

    def test_write_failure_does_not_report_success_or_touch_image(self):
        data=self.seed(); m=self.manager; before=m._metadata_path('U-001').read_bytes(); hashes=self.hashes()
        with patch.object(m,'_write_metadata',side_effect=OSError('fixture disk unavailable')):
            with self.assertRaises(OSError): m.update_photo('U-001',data['photos'][0]['id'],description='不应保存')
        self.assertEqual(before,m._metadata_path('U-001').read_bytes()); self.assertEqual(hashes,self.hashes())

    def test_parallel_caption_edits_do_not_lose_other_photos(self):
        data=self.seed(); ids=[p['id'] for p in data['photos'][:12]]; before=self.hashes()
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda pair:self.manager.update_photo('U-001',pair[1],description=f'并发-{pair[0]}'),enumerate(ids)))
        updated=self.manager.get_project('U-001')['photos']
        self.assertEqual(len(updated),24)
        self.assertEqual([p['description'] for p in updated[:12]],[f'并发-{i}' for i in range(12)])
        self.assertEqual(before,self.hashes())

    def test_cross_unit_move_and_caches_keep_existing_boundaries(self):
        first=self.seed(); self.seed('U-002',4); m=self.manager; photo=first['photos'][0]
        m.get_photos('U-001'); m.get_photos('U-002')
        moved=m.move_photo('U-001',photo['id'],'U-002',category=photo['category'],target_process_name='验收')
        self.assertEqual(moved['photo_uuid'],photo['photo_uuid'])
        self.assertEqual(len(m.get_photos('U-001')),23); self.assertEqual(len(m.get_photos('U-002')),5)
        m.invalidate_projects_cache()
        with patch.object(self.app,'project_matches_engineering',return_value=False):
            with self.assertRaises(FileNotFoundError): m.update_photo('U-002',moved['id'],description='拒绝')

class PerformanceFrontendContractTest(unittest.TestCase):
    def test_edit_does_not_reload_workspace_or_reduce_complete_collections(self):
        root=Path(__file__).resolve().parents[1]; js=next((root/'assets').glob('app-A*.js')).read_text(encoding='utf-8')
        edit=js.split('async function savePhotoEdit(event) {',1)[1].split('function initPhotoForms()',1)[0]
        self.assertNotIn('refreshAll(',edit); self.assertIn('applyPhotoEditResponse(data)',edit)
        self.assertIn('state.activeEngineeringProjectId !== sourceEngineering',edit)
        self.assertIn('const PHOTOS_BATCH = 24',js)
        self.assertIn('data-photo-sentinel',js)
        self.assertIn('visibleIds.concat',js)
        self.assertIn('page_size=10000',js)
        self.assertIn('host.ondragstart',js)
        self.assertIn('if (!Array.isArray(data.photos))',js)
        self.assertIn('let photoEditSavePending = false',js)

if __name__=='__main__': unittest.main()
