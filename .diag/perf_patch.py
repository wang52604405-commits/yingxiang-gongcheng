from pathlib import Path
p=Path('app.py');s=p.read_text(encoding='utf-8')
a=s.index('    def _write_metadata(');b=s.index('    def _photo_url(',a);block=s[a:b]
old='            os.replace(temporary, destination)\n'
new='''            # Windows readers/antivirus can briefly hold a non-delete-shared
            # handle. Retry only access conflicts, with a small bounded delay;
            # never remove the previous file or claim success after failure.
            for attempt in range(6):
                try:
                    os.replace(temporary, destination)
                    break
                except PermissionError:
                    if attempt == 5:
                        raise
                    time.sleep(0.01 * (attempt + 1))
'''
assert block.count(old)==1;block=block.replace(old,new);s=s[:a]+block+s[b:];p.write_text(s,encoding='utf-8',newline='\n')
p=Path('tests/test_z_performance_navigation.py');s=p.read_text(encoding='utf-8')
extra='''
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
'''
assert "if __name__=='__main__':unittest.main()" in s;s=s.replace("if __name__=='__main__':unittest.main()",extra+"\nif __name__=='__main__':unittest.main()")
p.write_text(s,encoding='utf-8',newline='\n')
p=Path('tests/run_performance_browser.py');s=p.read_text(encoding='utf-8')
old="                    check('DOM batches while complete 164 records remain available');load_all();assert page.locator('#photoSectionsHost .photo').count()==150"
new="""                    check('DOM batches while complete 164 records remain available')
                    page.locator('#gallerySelectBtn').click();page.locator('#selectAllCurrentPhotosBtn').click()
                    assert page.locator('#photoSelectionCount').inner_text()=='已选 150 张'
                    assert page.locator('#photoSectionsHost .photo').count()<150
                    page.locator('#printSelectedPhotosBtn').click();page.locator('#printSetupModal.open').wait_for()
                    assert len(page.evaluate('()=>new URL(state.printSourceUrl,location.origin).searchParams.get("ids").split(",")'))==150
                    page.locator('#closePrintSetupBtn').click();page.locator('#cancelPhotoSelectionBtn').click()
                    check('select-all and print include not-yet-rendered photos')
                    load_all();assert page.locator('#photoSectionsHost .photo').count()==150"""
assert old in s;s=s.replace(old,new);p.write_text(s,encoding='utf-8',newline='\n')
