from pathlib import Path
p=Path('app.py');s=p.read_text(encoding='utf-8')
a=s.index('        id_set = set(ordered_ids)',s.index('    def reorder_photos('));b=s.index('\n    def auto_sort_piles(',a)
s=s[:a]+'\n'.join(('    '+line) if line.strip() else line for line in s[a:b].split('\n'))+s[b:];p.write_text(s,encoding='utf-8',newline='\n')
p=Path('assets/app-A20260910-2.92.js');s=p.read_text(encoding='utf-8')
for start,end in [('    async function reorderPhoto(', '    async function saveDraggedPhotoOrder('),('    async function saveDraggedPhotoOrder(', '    async function renumberCategory(')]:
 a=s.index(start);b=s.index(end,a);block=s[a:b];marker='      const data = await apiJson(';at=block.index(marker)
 block=block[:at]+'''      const sourceCode = state.selectedCode;
      const sourceContext = navigationContext();
'''+block[at:]
 block=block.replace('encodeURIComponent(state.selectedCode)', 'encodeURIComponent(sourceCode)')
 block=block.replace('''      state.photos = data.photos || [];
      renderPhotos();''','''      if (state.selectedCode === sourceCode && navigationContext() === sourceContext) {
        state.photos = data.photos || [];
        renderPhotos();
      }''')
 block=block.replace('await renumberCategory(category);','await renumberCategory(category, sourceCode, sourceContext);');s=s[:a]+block+s[b:]
a=s.index('    async function renumberCategory(');b=s.index('    function initPhotoDragSort(',a);block=s[a:b]
block=block.replace('async function renumberCategory(category)', 'async function renumberCategory(category, sourceCode = state.selectedCode, sourceContext = navigationContext())')
block=block.replace('encodeURIComponent(state.selectedCode)','encodeURIComponent(sourceCode)')
block=block.replace('      state.photos = data.photos || [];','''      if (state.selectedCode !== sourceCode || navigationContext() !== sourceContext) return;
      state.photos = data.photos || [];''')
s=s[:a]+block+s[b:];p.write_text(s,encoding='utf-8',newline='\n')
p=Path('tests/test_z_performance_navigation.py');s=p.read_text(encoding='utf-8')
extra='''
    def test_reorder_holds_unit_lock_until_durable_metadata_write(self):
        self.seed('U1',4);m=self.manager;real=m._write_metadata
        def guarded(code,data):
            self.assertTrue(m._project_write_lock(code).locked())
            return real(code,data)
        with patch.object(m,'_write_metadata',side_effect=guarded):
            m.reorder_photos('U1',['U1-SY004','U1-SY003','U1-SY002','U1-SY001'],category='construction')
        self.assertEqual([p['photo_uuid'] for p in m.get_photos('U1')],['U1-uuid-3','U1-uuid-2','U1-uuid-1','U1-uuid-0'])
'''
s=s.replace("if __name__=='__main__':unittest.main()",extra+"\nif __name__=='__main__':unittest.main()");p.write_text(s,encoding='utf-8',newline='\n')
p=Path('tests/run_performance_browser.py');s=p.read_text(encoding='utf-8')
s=s.replace('def main():','''def main():
    import faulthandler
    faulthandler.dump_traceback_later(90, repeat=True)''',1)
old='''                    with page.expect_response(lambda r:'/reorder-list' in r.url and r.request.method=='POST'):
                        page.locator('#photoSectionsHost .photo').nth(130).drag_to(page.locator('#photoSectionsHost .photo').nth(129),target_position={'x':5,'y':5})'''
new='''                    drag_id=page.locator('#photoSectionsHost .photo').nth(130).get_attribute('data-photo-id')
                    target_id=page.locator('#photoSectionsHost .photo').nth(129).get_attribute('data-photo-id')
                    source=page.locator(f'#photoSectionsHost .photo[data-photo-id="{drag_id}"]')
                    target=page.locator(f'#photoSectionsHost .photo[data-photo-id="{target_id}"]')
                    source.scroll_into_view_if_needed()
                    source.hover();bounds=target.bounding_box();assert bounds
                    print('DRAG begin',drag_id,target_id,flush=True)
                    with page.expect_response(lambda r:'/reorder-list' in r.url and r.request.method=='POST'):
                        page.mouse.down();print('DRAG down',flush=True)
                        page.mouse.move(bounds['x']+5,bounds['y']+5,steps=4);print('DRAG move1',flush=True)
                        page.mouse.move(bounds['x']+6,bounds['y']+6);print('DRAG move2',flush=True)
                        page.mouse.up();print('DRAG released',flush=True)'''
assert old in s;s=s.replace(old,new)
s=s.replace("                    pp=context.new_page();pp.on('pageerror',lambda e:errors.append(str(e)))", "                    print('PRINT matrix starting',flush=True)\n                    pp=context.new_page();pp.on('pageerror',lambda e:errors.append(str(e)))");p.write_text(s,encoding='utf-8',newline='\n')
