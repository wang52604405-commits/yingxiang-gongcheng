from pathlib import Path
p=Path('app.py');s=p.read_text(encoding='utf-8');a=s.index('    def _renumber_category(');b=s.index('    def create_project(',a)
s=s[:a]+'''    def _renumber_category(self, project_code, data, category, settings=None):
        """Move images AND originals through a disjoint namespace before publishing.

        Original backup names can form cycles when a photo changes process. Never
        overwrite an occupied destination, and persist metadata before discarding
        the recovery map. Caller holds the unit write lock throughout.
        """
        settings = self._numbering_snapshot() if settings is None else settings
        category = self._normalize_category(category)
        photos_dir = self._photos_dir(project_code)
        self._repair_renumber_leftovers(project_code)
        counters, plans, moves = {}, [], []
        first_sequence = numbering_start(category, settings["numbering_rules"])
        for photo in data.get("photos", []):
            if self._normalize_category(photo.get("category")) != category:
                continue
            before = dict(photo)
            process_name = str(photo.get("process_name") or "").strip()
            process_code = self._process_code(data, process_name) if process_name else ""
            candidate = {**photo, "process_name": process_name, "process_code": process_code}
            scope = (category, process_code)
            index = counters.get(scope, first_sequence - 1) + 1
            counters[scope] = index
            new_id = self._archive_id_for_photo(data, candidate, category, index, settings=settings)
            old_name = str(photo.get("filename") or "")
            new_name = self._photo_filename(category, new_id, Path(old_name).suffix.lower() or ".jpg", process_code)
            normalized = {"id": new_id, "filename": new_name, "category": category,
                          "category_label": PHOTO_CATEGORY_LABELS[category],
                          "process_name": process_name, "process_code": process_code}
            if new_name == old_name and str(photo.get("id") or "") == new_id:
                photo.update(normalized)
                continue
            plan = {"photo": photo, "before": before, "after": normalized}
            plans.append(plan)
            old_image, new_image = photos_dir / Path(old_name).name, photos_dir / new_name
            if old_image.is_file() and old_image != new_image:
                moves.append({"old": old_image, "new": new_image})
            old_backup_name = str(photo.get("original_backup") or "")
            if old_backup_name:
                old_backup = self._original_path(project_code, old_backup_name)
                new_backup = self._original_path(project_code, new_name)
                if old_backup.is_file():
                    normalized["original_backup"] = new_name
                    if old_backup != new_backup:
                        moves.append({"old": old_backup, "new": new_backup})
        if not plans:
            return
        sources = [item["old"] for item in moves]
        destinations = [item["new"] for item in moves]
        if len(set(sources)) != len(sources) or len(set(destinations)) != len(destinations):
            raise ValueError("照片或原图备份引用重复，已停止重编号，未覆盖任何文件")
        for target in destinations:
            if target.exists() and target not in sources:
                raise ValueError("重编号目标存在未归属文件，已停止操作并保留原文件")
        stage_root = self._project_dir(project_code) / "_renumber_staging" / uuid.uuid4().hex
        stage_root.mkdir(parents=True, exist_ok=False)
        for index, item in enumerate(moves):
            item["stage"] = stage_root / f"stage-{index}{item['old'].suffix}"
            item["rollback"] = stage_root / f"rollback-{index}{item['old'].suffix}"
            item["current"] = item["old"]
        (stage_root / "recovery.json").write_text(json.dumps({
            "project_code": project_code,
            "moves": [{key: str(item[key]) for key in ("old", "new", "stage", "rollback")} for item in moves],
            "records": [{"before": item["before"], "after": item["after"]} for item in plans],
        }, ensure_ascii=False, indent=2), encoding="utf-8")

        def rename_preserving(source, target):
            for attempt in range(6):
                try:
                    if target.exists():
                        raise FileExistsError(f"目标文件已存在，拒绝覆盖：{target}")
                    source.rename(target)
                    return
                except PermissionError:
                    if attempt == 5:
                        raise
                    time.sleep(0.01 * (attempt + 1))

        try:
            for item in moves:
                rename_preserving(item["old"], item["stage"])
                item["current"] = item["stage"]
            for item in moves:
                rename_preserving(item["stage"], item["new"])
                item["current"] = item["new"]
            for item in plans:
                item["photo"].update(item["after"])
            self._write_metadata(project_code, data)
        except Exception as exc:
            rollback_errors = []
            for item in moves:
                if item["current"] == item["old"]:
                    continue
                try:
                    rename_preserving(item["current"], item["rollback"])
                    item["current"] = item["rollback"]
                except Exception as problem:
                    rollback_errors.append(str(problem))
            for item in moves:
                if item["current"] == item["old"]:
                    continue
                try:
                    rename_preserving(item["current"], item["old"])
                    item["current"] = item["old"]
                except Exception as problem:
                    rollback_errors.append(str(problem))
            for item in plans:
                item["photo"].clear()
                item["photo"].update(item["before"])
            self.invalidate_projects_cache(project_code)
            if not rollback_errors:
                shutil.rmtree(stage_root, ignore_errors=True)
            detail = f"；恢复文件保留在 {stage_root}" if rollback_errors else "；文件已恢复至操作前"
            raise RuntimeError(f"重编号未完成：{exc}{detail}") from exc
        else:
            shutil.rmtree(stage_root, ignore_errors=True)
            for item in plans:
                for name in (item["before"].get("filename", ""), item["after"]["filename"]):
                    try:
                        (photos_dir / self._thumb_filename(name)).unlink(missing_ok=True)
                    except OSError:
                        pass
            for item in plans:
                self._ensure_thumbnail(project_code, item["after"]["filename"])

'''+s[b:]
old='''            version = str(int(original_path.stat().st_mtime))'''
new='''            stamp = original_path.stat()
            # Same-second renumbering may reuse a filename for another UUID.
            identity = f"{item.get('photo_uuid', '')}:{stamp.st_mtime_ns}:{stamp.st_size}:{stamp.st_ino}"
            version = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]'''
assert s.count(old)==1;s=s.replace(old,new);p.write_text(s,encoding='utf-8',newline='\n')
p=Path('tests/test_z_performance_navigation.py');s=p.read_text(encoding='utf-8')
extra='''
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
'''
s=s.replace("if __name__=='__main__':unittest.main()",extra+"\nif __name__=='__main__':unittest.main()");p.write_text(s,encoding='utf-8',newline='\n')
