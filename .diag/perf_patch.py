from pathlib import Path
p=Path('app.py');s=p.read_text(encoding='utf-8')
a=s.index('    def update_photo(');b=s.index('    def rename_process(',a);block=s[a:b]
old='''            for photo in data.get("photos", []):
                if str(photo.get("id") or "") == target_id:'''
new='''            requested_uuid = str(updates.get("photo_uuid") or "").strip()
            for photo in data.get("photos", []):
                matches = (str(photo.get("photo_uuid") or "") == requested_uuid) if requested_uuid else (str(photo.get("id") or "") == target_id)
                if matches:'''
assert old in block;block=block.replace(old,new);s=s[:a]+block+s[b:]
a=s.index('    def reorder_photos(');b=s.index('    def auto_sort_piles(',a);block=s[a:b]
block=block.replace('ordered_ids, category=""):', 'ordered_ids, category="", renumber=False):')
old='''            self._write_metadata(data["project_code"], data)'''
new='''            if renumber:
                self._renumber_category(project_code, data, category)
            self._write_metadata(data["project_code"], data)'''
assert block.count(old)==1;block=block.replace(old,new);s=s[:a]+block+s[b:]
a=s.index('def api_reorder_photos(');b=s.index('\n\ndef ',a);block=s[a:b]
block=block.replace('category=payload.get("category", ""))','category=payload.get("category", ""), renumber=payload.get("renumber") is True)');s=s[:a]+block+s[b:]
a=s.index('def api_update_photo(');b=s.index('\n\n@app.route',a);block=s[a:b]
block=block.replace('''        updates = {
''','''        updates = {
            "photo_uuid": str(data.get("photo_uuid") or "").strip(),
''');s=s[:a]+block+s[b:];p.write_text(s,encoding='utf-8',newline='\n')
p=Path('assets/app-A20260910-2.92.js');s=p.read_text(encoding='utf-8')
a=s.index('    async function saveDraggedPhotoOrder(');b=s.index('    async function renumberCategory(',a);block=s[a:b]
block=block.replace('JSON.stringify({ category, ordered_ids: orderedIds })','JSON.stringify({ category, ordered_ids: orderedIds, renumber: true })')
a2=block.index('      try {\n        await renumberCategory');b2=block.index('      showNotice("拖拽排序已保存',a2);block=block[:a2]+block[b2:];s=s[:a]+block+s[b:]
a=s.index('    async function openPhotoEdit(');b=s.index('    function closePhotoEdit(',a);block=s[a:b]
old='''      if (!(await ensureAuthenticated("修改照片信息"))) return;
      const photo = state.photos.find((item) => normalizePhotoCategory(item.category) === normalizePhotoCategory(category) && String(item.id || "") === String(photoId || ""));'''
new='''      const context = navigationContext();
      const code = state.selectedCode;
      const original = state.photos.find((item) => normalizePhotoCategory(item.category) === normalizePhotoCategory(category) && String(item.id || "") === String(photoId || ""));
      if (!original || !(await ensureAuthenticated("修改照片信息"))) return;
      if (context !== navigationContext() || code !== state.selectedCode) return;
      const photo = original.photo_uuid ? state.photos.find((item) => item.photo_uuid === original.photo_uuid) : original;'''
assert old in block;block=block.replace(old,new)
old='''      state.editingPhoto = { category: normalizePhotoCategory(category), photoId: String(photoId || "") };'''
new='''      state.editingPhoto = { category: normalizePhotoCategory(category), photoId: String(photo.id || ""), photoUuid: String(photo.photo_uuid || "") };'''
assert old in block;block=block.replace(old,new);s=s[:a]+block+s[b:]
a=s.index('    function currentEditingPhoto()');b=s.index('    async function',a);block=s[a:b]
old='''      return state.photos.find((item) => String(item.id || "") === state.editingPhoto.photoId) || null;'''
new='''      return state.photos.find((item) => state.editingPhoto.photoUuid
        ? String(item.photo_uuid || "") === state.editingPhoto.photoUuid
        : (normalizePhotoCategory(item.category) === state.editingPhoto.category && String(item.id || "") === state.editingPhoto.photoId)) || null;'''
assert old in block;block=block.replace(old,new);s=s[:a]+block+s[b:]
a=s.index('    async function savePhotoEdit(');b=s.index('    function initPhotoForms(',a);block=s[a:b]
old='''      const currentPhoto = state.photos.find((item) => normalizePhotoCategory(item.category) === state.editingPhoto.category && String(item.id || "") === state.editingPhoto.photoId);'''
new='''      const currentPhoto = currentEditingPhoto();
      if (!currentPhoto) return showNotice("照片已发生变化，请关闭后重新选择。", true);'''
assert old in block;block=block.replace(old,new);block=block.replace('JSON.stringify({ title, photo_date:', 'JSON.stringify({ photo_uuid: editing.photoUuid, title, photo_date:');s=s[:a]+block+s[b:]
anchor='    async function loadProject(code, tab = "detail") {'
helper='''    function setUnitLoadingState(busy) {
      $("#unitView")?.setAttribute("aria-busy", busy ? "true" : "false");
      ["#galleryUploadBtn", "#unitPrintCurrentBtn", "#addProcessBtn", "#unitMoreMenuBtn", "#unitCategoryConstructionBtn", "#unitCategorySupervisionBtn"].forEach((selector) => { if ($(selector)) $(selector).disabled = busy; });
      if ($("#gallerySelectBtn")) $("#gallerySelectBtn").disabled = busy || !activeGalleryPhotos().length;
      if (busy) { $("#unitMoreMenu")?.classList.remove("open"); $("#unitMoreMenuBtn")?.setAttribute("aria-expanded", "false"); }
    }

'''
assert s.count(anchor)==1;s=s.replace(anchor,helper+anchor)
a=s.index(anchor);b=s.index('    function renderUnit()',a);block=s[a:b]
block=block.replace('      setView("unit");\n      try {','      setView("unit");\n      setUnitLoadingState(true);\n      try {')
block=block.replace('      renderUnit();','      setUnitLoadingState(false);\n      renderUnit();');s=s[:a]+block+s[b:];p.write_text(s,encoding='utf-8',newline='\n')
p=Path('tests/test_z_performance_navigation.py');s=p.read_text(encoding='utf-8')
extra='''
    def test_atomic_drag_response_has_final_numbering_before_next_edit(self):
        self.seed('U1',4);m=self.manager;expected=self.distinct_original_hashes('U1')
        m.reorder_photos('U1',['U1-SY004','U1-SY003','U1-SY002','U1-SY001'],category='construction',renumber=True)
        photos=m.get_photos('U1')
        self.assertEqual([p['id'] for p in photos],['U1-SY001','U1-SY002','U1-SY003','U1-SY004'])
        self.assertEqual(photos[0]['photo_uuid'],'U1-uuid-3')
        m.update_photo('U1','U1-SY004',photo_uuid='U1-uuid-3',title='准确更新')
        self.assertEqual(next(p for p in m.get_photos('U1') if p['photo_uuid']=='U1-uuid-3')['title'],'准确更新')
        self.assert_original_hashes('U1',expected)

    def test_unknown_edit_uuid_never_falls_back_to_another_display_id(self):
        self.seed('U1',2);m=self.manager;before=m._metadata_path('U1').read_bytes()
        with self.assertRaises(ValueError):m.update_photo('U1','U1-SY001',photo_uuid='already-gone',title='不得写入')
        self.assertEqual(m._metadata_path('U1').read_bytes(),before)
'''
s=s.replace("if __name__=='__main__':unittest.main()",extra+"\nif __name__=='__main__':unittest.main()");p.write_text(s,encoding='utf-8',newline='\n')
p=Path('tests/run_performance_browser.py');s=p.read_text(encoding='utf-8')
s=s.replace("assert page.evaluate('(id)=>state.photos.find(p=>p.photo_uuid===id).title',selected_uuid)=='已核对的现场记录';assert page.locator('#photoSectionsHost .photo').count()>130", "assert page.evaluate('(id)=>state.photos.find(p=>p.photo_uuid===id).title',selected_uuid)=='已核对的现场记录', {'uuid':selected_uuid,'records':page.evaluate('()=>state.photos.map(p=>({uuid:p.photo_uuid,id:p.id,title:p.title})).slice(125,135)')};assert page.locator('#photoSectionsHost .photo').count()>130")
p.write_text(s,encoding='utf-8',newline='\n')
