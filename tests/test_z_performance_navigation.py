"""Regression gates for read caching, atomic saves, ownership and stable selections."""
from __future__ import annotations
import copy
import hashlib
import io
import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

class UnitSnapshotPerformanceTest(unittest.TestCase):
    def setUp(self):
        import app
        self.app=app
        self.temp=tempfile.TemporaryDirectory(prefix='album-full-perf-')
        self.addCleanup(self.temp.cleanup)
        self.manager=app.AlbumManager(Path(self.temp.name))
        self.engineering='engineering-A'
        for name,kwargs in (
            ('active_engineering_project_id',{'side_effect':lambda:self.engineering}),
            ('read_engineering_settings',{'return_value':copy.deepcopy(app.DEFAULT_ENGINEERING_SETTINGS)}),
        ):
            p=patch.object(app,name,**kwargs);p.start();self.addCleanup(p.stop)

    def seed(self,code,count=8,owner='engineering-A'):
        from PIL import Image
        buf=io.BytesIO();Image.new('RGB',(64,48),(64,120,130)).save(buf,'JPEG')
        m=self.manager
        data={'project_code':code,'display_project_code':code,'project_name':'底板'+code,
              'engineering_project_id':owner,'source_fields':{'工程项目ID':owner,'合同工程名称':'验收合同','单位工程名称':'验收单位','分部工程名称':'验收分部'},
              'processes':['开挖','验收'],'photos':[]}
        m._photos_dir(code).mkdir(parents=True);m._originals_dir(code).mkdir(parents=True)
        for i in range(count):
            pid=f'{code}-SY{i+1:03d}';name=m._photo_filename('construction',pid,'.jpg')
            (m._photos_dir(code)/name).write_bytes(buf.getvalue());(m._originals_dir(code)/name).write_bytes(buf.getvalue())
            data['photos'].append({'id':pid,'photo_uuid':f'{code}-uuid-{i}','filename':name,'original_backup':name,
              'category':'construction','title':f'底板{i}','photo_date':'2026-09-14','description':'原始记录',
              'photographer':'验收员','process_name':'','process_code':'','orientation':'landscape','rotation':0})
        m._write_metadata(code,data)
        return data

    def test_reads_are_cached_but_return_independent_mutable_objects(self):
        self.seed('U1');m=self.manager;original=m._read_metadata('U1')
        with patch.object(self.app.json,'load',wraps=self.app.json.load) as parse:
            one=m._read_metadata('U1');one['photos'][0]['title']='未保存修改'
            two=m._read_metadata('U1')
        self.assertEqual(parse.call_count,0);self.assertEqual(two,original)

    def test_atomic_write_failure_keeps_previous_metadata_and_no_temp_files(self):
        self.seed('U1');m=self.manager;before=m._metadata_path('U1').read_bytes()
        data=m._read_metadata('U1');data['photos'][0]['title']='新值'
        with patch.object(self.app.os,'replace',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):m._write_metadata('U1',data)
        self.assertEqual(m._metadata_path('U1').read_bytes(),before)
        self.assertFalse(list(m._project_dir('U1').glob('.metadata-*.tmp')))
        self.assertNotEqual(m._read_metadata('U1')['photos'][0]['title'],'新值')

    def test_foreign_project_cannot_reuse_warm_photo_cache(self):
        self.seed('U1');self.manager.get_photos('U1');self.engineering='engineering-B'
        with self.assertRaises(FileNotFoundError):self.manager.get_photos('U1')
        self.assertEqual(self.manager.list_projects(),[])

    def test_external_metadata_replacement_invalidates_file_snapshots(self):
        self.seed('U1');m=self.manager;m.get_photos('U1')
        data=m._read_metadata('U1');data['photos'][0]['title']='外部已更新'
        temp=m._metadata_path('U1').with_suffix('.replace')
        temp.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8');os.replace(temp,m._metadata_path('U1'))
        self.assertEqual(m.get_photos('U1')[0]['title'],'外部已更新')

    def test_one_unit_edit_only_reparses_one_summary_and_counts_stay_exact(self):
        m=self.manager
        for i in range(40):self.seed(f'U{i}',3)
        self.assertEqual(sum(x['photo_count'] for x in m.list_projects()),120)
        warm=m.get_photos('U20')
        data=m.get_project('U0');data['photos'][0]['title']='已保存';m._write_metadata('U0',data)
        with patch.object(m,'_read_metadata',wraps=m._read_metadata) as read:projects=m.list_projects()
        self.assertEqual(read.call_count,1);self.assertEqual(len(projects),40)
        self.assertEqual(sum(x['photo_count'] for x in projects),120)
        self.assertEqual(m.get_photos('U20'),warm)

    def test_checked_legacy_scopes_are_not_rescanned_until_unit_changes(self):
        self.seed('U1');m=self.manager;self.assertEqual(m.repair_legacy_process_photo_scopes('U1'),0)
        with patch.object(m,'get_project',wraps=m.get_project) as read:
            for _ in range(5):self.assertEqual(m.repair_legacy_process_photo_scopes('U1'),0)
        self.assertEqual(read.call_count,0)
        data=m.get_project('U1');data['photos'][0]['process_code']='GY001';m._write_metadata('U1',data)
        self.assertEqual(m.repair_legacy_process_photo_scopes('U1'),1)
        self.assertEqual(m.get_project('U1')['photos'][0]['process_code'],'')

    def test_cache_bound_and_cross_unit_move_still_preserve_file_bytes(self):
        m=self.manager
        for i in range(20):self.seed(f'U{i}',1);m.get_photos(f'U{i}')
        self.assertLessEqual(len(m._metadata_cache),16);self.assertLessEqual(len(m._photos_cache),16)
        before=m.get_photos('U0')[0];digest=hashlib.sha256((m._photos_dir('U0')/before['filename']).read_bytes()).hexdigest()
        moved=m.move_photo('U0',before['id'],'U1',category='construction',target_process_name='验收')
        self.assertEqual(moved['photo_uuid'],before['photo_uuid']);self.assertEqual(len(m.get_photos('U0')),0)
        self.assertEqual(len(m.get_photos('U1')),2)
        self.assertEqual(hashlib.sha256((m._photos_dir('U1')/moved['filename']).read_bytes()).hexdigest(),digest)

    def test_concurrent_reads_never_observe_half_written_json(self):
        self.seed('U1',24);m=self.manager;errors=[]
        def read():
            for _ in range(40):
                try:
                    raw=m.get_project('U1');self.assertEqual(len(raw['photos']),24)
                except Exception as e:errors.append(str(e))
        def write():
            for i in range(12):m.update_photo('U1','U1-SY001',description=f'记录{i}')
        with ThreadPoolExecutor(max_workers=3) as ex:
            fs=[ex.submit(read),ex.submit(read),ex.submit(write)]
            for f in fs:f.result()
        self.assertEqual(errors,[]);self.assertEqual(len(m.get_photos('U1')),24)

    def test_uuid_delete_ignores_reused_display_number(self):
        self.seed('U1',3);m=self.manager
        with patch.object(self.app,'manager',m),patch.object(self.app,'ensure_engineering_delete_password',return_value=None),patch.object(self.app,'desktop_mobile_sync_service') as service:
            service.return_value.enqueue_photo_delete.return_value={'ok':True,'queued':True}
            client=self.app.app.test_client()
            with client.session_transaction() as session:session['username']='隔离验收员'
            first=client.post('/api/delete-photo/U1/U1-SY001',json={'category':'construction','photo_uuid':'U1-uuid-0','safety_password':'test-only'})
            self.assertEqual(first.status_code,200)
            second=client.post('/api/delete-photo/U1/U1-SY002',json={'category':'construction','photo_uuid':'U1-uuid-1','safety_password':'test-only'})
            self.assertEqual(second.status_code,200)
            self.assertEqual([x['photo_uuid'] for x in m.get_photos('U1')],['U1-uuid-2'])

    def test_same_unit_move_rejects_unknown_process_without_mutation(self):
        self.seed('U1',2);m=self.manager;before=m._metadata_path('U1').read_bytes()
        with self.assertRaises(ValueError):m.move_photo('U1','U1-SY001','U1',target_process_name='不存在')
        self.assertEqual(m._metadata_path('U1').read_bytes(),before)

    def test_move_early_file_error_restores_staged_source_bytes(self):
        self.seed('U1',2);self.seed('U2',1);m=self.manager
        before=m.get_photos('U1')[0];filename=before['filename'];raw=(m._photos_dir('U1')/filename).read_bytes()
        real_move=self.app.shutil.move
        def fail_backup(src,dst,*args,**kwargs):
            if '_originals' in str(src):raise OSError('backup staging denied')
            return real_move(src,dst,*args,**kwargs)
        with patch.object(self.app.shutil,'move',side_effect=fail_backup):
            with self.assertRaises(RuntimeError):m.move_photo('U1',before['id'],'U2')
        self.assertEqual((m._photos_dir('U1')/filename).read_bytes(),raw)
        self.assertEqual(len(m.get_photos('U1')),2);self.assertEqual(len(m.get_photos('U2')),1)

    def test_failed_rollback_keeps_recovery_map_and_only_full_image(self):
        self.seed('U1',1);self.seed('U2',1);m=self.manager
        photo=m.get_photos('U1')[0];raw=(m._photos_dir('U1')/photo['filename']).read_bytes()
        with patch.object(m,'_renumber_after_change',side_effect=OSError('persistent disk failure')):
            with self.assertRaises(RuntimeError):m.move_photo('U1',photo['id'],'U2')
        recovery=list((m.root/'_move_staging').glob('*/recovery.json'))
        self.assertEqual(len(recovery),1);self.assertEqual((recovery[0].parent/'photo.jpg').read_bytes(),raw)
        self.assertEqual(json.loads(recovery[0].read_text(encoding='utf-8'))['photo_uuid'],photo['photo_uuid'])


    def test_transient_windows_lock_retries_without_removing_previous_record(self):
        self.seed('U1',2);m=self.manager;old=m._metadata_path('U1').read_bytes();d=m.get_project('U1');d['photos'][0]['title']='重试成功'
        real=self.app.os.replace;calls=[]
        def busy(src,dst):
            calls.append(1)
            if len(calls)<3:
                self.assertEqual(m._metadata_path('U1').read_bytes(),old)
                raise PermissionError('transient Windows handle')
            return real(src,dst)
        with patch.object(self.app.os,'replace',side_effect=busy):m._write_metadata('U1',d)
        self.assertEqual(len(calls),3);self.assertEqual(m.get_project('U1')['photos'][0]['title'],'重试成功')

    def test_permanent_windows_lock_is_bounded_and_keeps_previous_record(self):
        self.seed('U1',2);m=self.manager;old=m._metadata_path('U1').read_bytes();d=m.get_project('U1');d['photos'][0]['title']='不得保存'
        with patch.object(self.app.os,'replace',side_effect=PermissionError('persistent lock')) as replace:
            with self.assertRaises(PermissionError):m._write_metadata('U1',d)
        self.assertEqual(replace.call_count,6);self.assertEqual(m._metadata_path('U1').read_bytes(),old)


    def test_transient_reader_conflict_returns_full_records_not_empty_defaults(self):
        self.seed('U1',24);m=self.manager;m.invalidate_projects_cache()
        path=m._metadata_path('U1');real=Path.open;attempts=[]
        def busy(p,*args,**kwargs):
            if p==path:
                attempts.append(1)
                if len(attempts)<3:raise PermissionError('Windows reader conflict')
            return real(p,*args,**kwargs)
        with patch.object(Path,'open',busy):data=m.get_project('U1')
        self.assertEqual(len(data['photos']),24);self.assertEqual(len(attempts),3)

    def test_unreadable_or_corrupt_metadata_never_turns_into_empty_collection(self):
        self.seed('U1',24);m=self.manager;m.invalidate_projects_cache()
        path=m._metadata_path('U1');before=path.read_bytes();real=Path.open;attempts=[]
        def busy(p,*args,**kwargs):
            if p==path:
                attempts.append(1);raise PermissionError('persistent denial')
            return real(p,*args,**kwargs)
        with patch.object(Path,'open',busy):
            with self.assertRaises(PermissionError):m.get_project('U1')
        self.assertEqual(len(attempts),6);self.assertEqual(path.read_bytes(),before)
        path.write_text('{broken-record',encoding='utf-8');m.invalidate_projects_cache()
        with self.assertRaises(ValueError):m.get_project('U1')
        self.assertEqual(path.read_text(encoding='utf-8'),'{broken-record')


    def test_reorder_holds_unit_lock_until_durable_metadata_write(self):
        self.seed('U1',4);m=self.manager;real=m._write_metadata
        def guarded(code,data):
            self.assertTrue(m._project_write_lock(code).locked())
            return real(code,data)
        with patch.object(m,'_write_metadata',side_effect=guarded):
            m.reorder_photos('U1',['U1-SY004','U1-SY003','U1-SY002','U1-SY001'],category='construction')
        self.assertEqual([p['photo_uuid'] for p in m.get_photos('U1')],['U1-uuid-3','U1-uuid-2','U1-uuid-1','U1-uuid-0'])


    def distinct_original_hashes(self,code):
        from PIL import Image
        m=self.manager;records=m.get_project(code)['photos'];hashes={}
        for i,photo in enumerate(records):
            buf=io.BytesIO();Image.new('RGB',(64,48),((i*19)%255,(i*31)%255,(i*43)%255)).save(buf,'JPEG')
            raw=buf.getvalue();(m._photos_dir(code)/photo['filename']).write_bytes(raw)
            (m._originals_dir(code)/photo['original_backup']).write_bytes(raw)
            hashes[photo['photo_uuid']]=hashlib.sha256(raw).hexdigest()
        m.invalidate_projects_cache(code)
        return hashes

    def assert_original_hashes(self,code,expected):
        for photo in self.manager.get_photos(code):
            if photo['photo_uuid'] in expected:
                original=self.manager._originals_dir(code)/photo['original_backup']
                self.assertTrue(original.is_file(),photo)
                self.assertEqual(hashlib.sha256(original.read_bytes()).hexdigest(),expected[photo['photo_uuid']])

    def test_process_move_with_occupied_original_names_preserves_every_original(self):
        self.seed('U1',14);self.seed('U2',2);m=self.manager;expected=self.distinct_original_hashes('U1')
        data=m.get_project('U1')
        for photo in data['photos'][7:]:photo.update(process_name='开挖',process_code='GY001')
        m._renumber_after_change('U1',data);self.assert_original_hashes('U1',expected)
        photo=m.get_photos('U1')[0];permanent=photo['photo_uuid']
        m.move_photo('U1',photo['id'],'U1',target_process_name='开挖')
        self.assert_original_hashes('U1',expected)
        moved=next(p for p in m.get_photos('U1') if p['photo_uuid']==permanent)
        m.move_photo('U1',moved['id'],'U2',target_process_name='验收')
        self.assert_original_hashes('U1',expected);self.assert_original_hashes('U2',expected)

    def test_cyclic_reorder_preserves_distinct_image_and_backup_bytes(self):
        self.seed('U1',8);m=self.manager;expected=self.distinct_original_hashes('U1')
        data=m.get_project('U1');data['photos']=list(reversed(data['photos']))
        m._renumber_after_change('U1',data);self.assert_original_hashes('U1',expected)
        for photo in m.get_photos('U1'):
            self.assertEqual(hashlib.sha256((m._photos_dir('U1')/photo['filename']).read_bytes()).hexdigest(),expected[photo['photo_uuid']])

    def test_renumber_metadata_failure_restores_all_images_and_backups(self):
        self.seed('U1',8);m=self.manager;expected=self.distinct_original_hashes('U1')
        before=m._metadata_path('U1').read_bytes();data=m.get_project('U1');data['photos']=list(reversed(data['photos']))
        with patch.object(m,'_write_metadata',side_effect=OSError('failed metadata save')):
            with self.assertRaises(RuntimeError):m._renumber_category('U1',data,'construction')
        self.assertEqual(m._metadata_path('U1').read_bytes(),before);self.assert_original_hashes('U1',expected)
        for photo in m.get_photos('U1'):
            self.assertEqual(hashlib.sha256((m._photos_dir('U1')/photo['filename']).read_bytes()).hexdigest(),expected[photo['photo_uuid']])

    def test_thumbnail_revision_changes_when_same_timestamp_name_is_reused(self):
        self.seed('U1',2);m=self.manager;data=m.get_project('U1')
        for photo in data['photos']:os.utime(m._photos_dir('U1')/photo['filename'],ns=(1700000000000000000,1700000000000000000))
        m.invalidate_projects_cache('U1');before=m.get_photos('U1')
        data['photos'].reverse();m._renumber_after_change('U1',data);after=m.get_photos('U1')
        self.assertEqual(before[0]['filename'],after[0]['filename'])
        self.assertNotEqual(before[0]['photo_uuid'],after[0]['photo_uuid'])
        self.assertNotEqual(before[0]['thumb_url'],after[0]['thumb_url'])

if __name__=='__main__':unittest.main()
