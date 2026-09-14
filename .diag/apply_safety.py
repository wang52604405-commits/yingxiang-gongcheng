from pathlib import Path
p=Path('app.py');s=p.read_text(encoding='utf-8')
a=s.index('    def update_photo(');b=s.index('    def rename_process(',a);block=s[a:b]
block=block.replace('''                        new_process_name = str(updates.get("process_name") or "").strip()
                        photo["process_name"] = new_process_name''','''                        new_process_name = str(updates.get("process_name") or "").strip()
                        if new_process_name and new_process_name not in (data.get("processes") or []):
                            raise ValueError("目标工序不存在，请重新选择")
                        photo["process_name"] = new_process_name''')
s=s[:a]+block+s[b:]
a=s.index('    def move_photo(');b=s.index('    def reorder_photo(',a);block=s[a:b]
block=block.replace('''                source_photo["photo_uuid"] = photo_uuid
''','''                if any(str(item.get("photo_uuid") or "") == photo_uuid for item in target.get("photos", [])):
                    raise ValueError("目标单元已存在同一照片，请刷新后核实")
                source_photo["photo_uuid"] = photo_uuid
''')
block=block.replace('''                rollback_errors = []

                try:''','''                rollback_errors = []
                cleanup_safe = False
                # Preserve a local recovery map with the staged image if rollback fails.
                (stage_root / "recovery.json").write_text(json.dumps({
                    "source_code": source_code, "target_code": target_code,
                    "photo_uuid": photo_uuid, "source_photo": original_source,
                }, ensure_ascii=False, indent=2), encoding="utf-8")

                try:''')
block=block.replace('''                    return self._photo_item(target, moved)
''','''                    result = self._photo_item(target, moved)
                    cleanup_safe = True
                    return result
''')
block=block.replace('''                    message = f"照片移动失败：{exc}"
''','''                    else:
                        # Failure can happen after staging the image but before the
                        # metadata pop. Restore staged files even in that early window.
                        try:
                            if stage_photo.is_file() and not source_path.exists():
                                shutil.copy2(stage_photo, source_path)
                            if stage_thumb and stage_thumb.is_file():
                                shutil.copy2(stage_thumb, self._photos_dir(source_code) / self._thumb_filename(source_filename))
                            backup_name = str(original_source.get("original_backup") or "")
                            if backup_name and stage_backup and stage_backup.is_file():
                                shutil.copy2(stage_backup, self._originals_dir(source_code) / backup_name)
                        except Exception as rollback_exc:
                            rollback_errors.append(f"源文件恢复失败：{rollback_exc}")
                    if not rollback_errors:
                        try:
                            restored_data = self.get_project(source_code)
                            restored_photo = next(item for item in restored_data.get("photos", []) if str(item.get("photo_uuid") or "") == photo_uuid)
                            restored_path = self._photos_dir(source_code) / restored_photo["filename"]
                            if stage_photo.is_file() and restored_path.is_file():
                                cleanup_safe = hashlib.sha256(stage_photo.read_bytes()).digest() == hashlib.sha256(restored_path.read_bytes()).digest()
                            if not cleanup_safe:
                                rollback_errors.append("恢复校验未通过，已保留暂存原图")
                        except Exception as rollback_exc:
                            rollback_errors.append(f"恢复校验失败：{rollback_exc}")
                    message = f"照片移动失败：{exc}"
''')
block=block.replace('''                        message += "；" + "；".join(rollback_errors)
''','''                        message += "；" + "；".join(rollback_errors) + f"；恢复文件保留在 {stage_root}"
''')
block=block.replace('''                    shutil.rmtree(stage_root, ignore_errors=True)
''','''                    if cleanup_safe:
                        shutil.rmtree(stage_root, ignore_errors=True)
''')
s=s[:a]+block+s[b:];p.write_text(s,encoding='utf-8',newline='\n')
p=Path('assets/app-A20260910-2.92.js');s=p.read_text(encoding='utf-8')
a=s.index('    async function refreshPhotoMoveProcesses() {');b=s.index('    async function renderPhotoMoveTargets()',a)
old=s[a:b];old=old.replace('    async function refreshPhotoMoveProcesses() {','''    let photoMoveProcessSequence = 0;
    let photoMovePending = false;
    async function refreshPhotoMoveProcesses() {
      const sequence = ++photoMoveProcessSequence;''')
old=old.replace('''      const summary = $("#photoMoveSummary");''','''      const summary = $("#photoMoveSummary");
      const confirm = $("#confirmPhotoMoveBtn");
      if (confirm) confirm.disabled = true;
      if (processSelect) processSelect.disabled = true;''')
old=old.replace('''      const project = data.project || {};''','''      if (sequence !== photoMoveProcessSequence || $("#photoMoveTargetSelect")?.value !== targetCode) return;
      const project = data.project || {};''')
old=old.replace('''      if (summary) {
        summary.textContent''','''      if (processSelect) processSelect.disabled = false;
      if (confirm) confirm.disabled = photoMovePending;
      if (summary) {
        summary.textContent''')
s=s[:a]+old+s[b:]
a=s.index('    async function confirmPhotoMove() {');b=s.index('    function applyPhotoEditResponse(',a);block=s[a:b]
block=block.replace('''      if (!photo || !state.selectedCode) return;''','''      if (!photo || !state.selectedCode || photoMovePending || $("#photoMoveProcessSelect")?.disabled) return;''')
block=block.replace('''      await apiJson(`/api/photos/${encodeURIComponent(sourceCode)}/${encodeURIComponent(photo.id)}/move`, {''','''      const context = navigationContext();
      photoMovePending = true;
      $("#confirmPhotoMoveBtn").disabled = true;
      try {
      await apiJson(`/api/photos/${encodeURIComponent(sourceCode)}/${encodeURIComponent(photo.id)}/move`, {''')
block=block.replace('''      closePhotoMoveModal();''','''      if (state.selectedCode !== sourceCode || navigationContext() !== context) return;
      closePhotoMoveModal();''')
block=block.replace('''      showNotice(`照片已移动到 ${targetLabel}${targetProcess ? ` / ${targetProcess}` : ""}。`);
    }''','''      showNotice(`照片已移动到 ${targetLabel}${targetProcess ? ` / ${targetProcess}` : ""}。`);
      } finally {
        photoMovePending = false;
        $("#confirmPhotoMoveBtn").disabled = Boolean($("#photoMoveProcessSelect")?.disabled);
      }
    }''')
s=s[:a]+block+s[b:]
s=s.replace('if (!(await ensureAuthenticated("移动照片"))) return;\n      const sourceCode', 'if (!(await ensureAuthenticated("移动照片"))) return;\n      if (photoMovePending || currentEditingPhoto() !== photo) return;\n      const sourceCode')
s=s.replace('    async function deleteSelectedPhotos(sectionKey) {\n      const selected', '    let bulkDeletePending = false;\n    async function deleteSelectedPhotos(sectionKey) {\n      if (bulkDeletePending) return;\n      const selected')
s=s.replace('      const ordered = [...selected].reverse();\n      for (const item of ordered) {', '      const ordered = [...selected].reverse();\n      bulkDeletePending = true;\n      let completed = 0;\n      const deleteButton = $("#deleteSelectedCurrentPhotosBtn");\n      if (deleteButton) deleteButton.disabled = true;\n      try {\n      for (const item of ordered) {\n        if (state.selectedCode !== sourceCode || navigationContext() !== sourceContext) throw new Error("当前工程或单元已切换，已停止剩余删除。");')
s=s.replace('        latestPhotos = data.photos || latestPhotos;\n      }\n      if (state.selectedCode', '        latestPhotos = data.photos || latestPhotos;\n        completed += 1;\n      }\n      if (state.selectedCode')
s=s.replace('      showNotice(`已删除 ${selected.length} 张照片。`);\n    }', '''      showNotice(`已删除 ${selected.length} 张照片。`);
      } catch (error) {
        if (state.selectedCode === sourceCode && navigationContext() === sourceContext && completed) {
          applyPhotoEditResponse({ photos: latestPhotos });
          renderPhotos();
          scheduleSummaryRefresh();
        }
        throw new Error(`${completed ? `已删除 ${completed} 张；` : ""}${error.message || "删除未完成，请刷新核实。"}`);
      } finally {
        bulkDeletePending = false;
        updatePhotoSelectionBar();
      }
    }''')
p.write_text(s,encoding='utf-8',newline='\n')
import gzip
p.with_suffix('.js.gz').write_bytes(gzip.compress(p.read_bytes(),mtime=0))
t=Path('tests/test_z_performance_edit.py');s=t.read_text(encoding='utf-8');s=s.replace("self.assertIn('const PHOTOS_BATCH = 120',js)","self.assertIn('const PHOTOS_BATCH = 24',js)\n        self.assertIn('data-photo-sentinel',js)\n        self.assertIn('visibleIds.concat',js)");t.write_text(s,encoding='utf-8',newline='\n')
