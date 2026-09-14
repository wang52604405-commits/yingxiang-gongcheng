from pathlib import Path
r=Path.cwd()
p=r/'app.py'; s=p.read_text(encoding='utf-8')
def repl(old,new,n=1):
 global s
 assert s.count(old)>=n,(old[:110],s.count(old))
 s=s.replace(old,new,n)
repl('import csv\n','import csv\nimport copy\nfrom collections import OrderedDict\n')
repl('        self._revision = 1\n','''        self._revision = 1
        self._cache_lock = threading.RLock()
        self._metadata_cache = OrderedDict()
        self._unit_summaries = {}
        self._legacy_checked = {}
''')
a=s.index('    def invalidate_projects_cache(self):'); b=s.index('    def revision(self):',a)
s=s[:a]+'''    def invalidate_projects_cache(self, project_code=None):
        """Invalidate derived totals, retaining unrelated immutable unit snapshots.

        Account/project switches and external bulk changes still use a full clear.
        Cache entries never replace the existing engineering ownership check.
        """
        with self._cache_lock:
            self._projects_cache = {}
            self._hierarchy_cache = {}
            self._part_units_cache = {}
            if project_code is None:
                self._photos_cache = {}
                self._metadata_cache.clear()
                self._unit_summaries.clear()
                self._legacy_checked.clear()
            else:
                code = self._safe_code(project_code)
                self._metadata_cache.pop(code, None)
                self._unit_summaries.pop(code, None)
                for cache in (self._photos_cache, self._legacy_checked):
                    for key in list(cache):
                        if (isinstance(key, tuple) and key[-1] == code) or key == code:
                            cache.pop(key, None)
            self._revision += 1

    @staticmethod
    def _metadata_signature(path):
        try:
            stat = path.stat()
            return (stat.st_mtime_ns, stat.st_size, stat.st_ino)
        except OSError:
            return None

'''+s[b:]
repl('''    def _read_metadata(self, project_code):
        path = self._metadata_path(project_code)
''','''    def _read_metadata(self, project_code):
        path = self._metadata_path(project_code)
        key = self._safe_code(project_code)
        signature = self._metadata_signature(path)
        with self._cache_lock:
            cached = self._metadata_cache.get(key)
            if signature is not None and cached is not None and cached[0] == signature:
                self._metadata_cache.move_to_end(key)
                return copy.deepcopy(cached[1])
''')
repl('''                photo.setdefault("process_code", "")
        return data

    def _write_metadata''','''                photo.setdefault("process_code", "")
        # Check again after reading: do not label a concurrently replaced file with
        # the old snapshot's fingerprint. Always return a caller-owned mutable copy.
        if signature is not None and signature == self._metadata_signature(path) and signature[1] <= 4 * 1024 * 1024:
            with self._cache_lock:
                self._metadata_cache[key] = (signature, copy.deepcopy(data))
                self._metadata_cache.move_to_end(key)
                while len(self._metadata_cache) > 16:
                    self._metadata_cache.popitem(last=False)
        return data

    def _write_metadata''')
repl('''        with self._metadata_path(project_code).open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        self.invalidate_projects_cache()
''','''        destination = self._metadata_path(project_code)
        temporary = destination.with_name(f".metadata-{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        self.invalidate_projects_cache(project_code)
''')
a=s.index('    def list_projects(self, query="", include_other=False):'); b=s.index('    def _project_sort_key(',a)
old=s[a:b]
new=old.replace('        cache_key = (active_engineering_project_id(), str(query or ""), bool(include_other))','''        engineering_id = active_engineering_project_id()
        revision = self._revision
        cache_key = (engineering_id, str(query or ""), bool(include_other))''')
start=new.index('            try:\n                data = self._read_metadata'); end=new.index('            haystack = ',start)
block=new[start:end]
itemstart=block.index('            source_fields = ')
summary=block[itemstart:]
summary=summary.replace('''            if is_other_image and not include_other:
                continue
''','')
summary='\n'.join('    '+line if line else line for line in summary.rstrip().splitlines())+'\n'
newblock='''            signature = self._metadata_signature(project_dir / "metadata.json")
            with self._cache_lock:
                cached = self._unit_summaries.get(project_dir.name)
            if signature is not None and cached is not None and cached[0] == signature:
                membership, item = cached[1], copy.deepcopy(cached[2])
            else:
                try:
                    data = self._read_metadata(project_dir.name)
                except Exception:
                    continue
                membership = {
                    "engineering_project_id": data.get("engineering_project_id", ""),
                    "source_fields": {"工程项目ID": (data.get("source_fields") or {}).get("工程项目ID", "")},
                }
'''+summary+'''                if signature is not None and signature == self._metadata_signature(project_dir / "metadata.json"):
                    with self._cache_lock:
                        self._unit_summaries[project_dir.name] = (signature, membership, copy.deepcopy(item))
            if not project_matches_engineering(membership, engineering_id):
                continue
            if item["is_other_image"] and not include_other:
                continue
'''
new=new[:start]+newblock+new[end:]
new=new.replace('        self._projects_cache[cache_key] = result','''        if revision == self._revision:
            with self._cache_lock:
                if len(self._projects_cache) >= 32:
                    self._projects_cache.clear()
                self._projects_cache[cache_key] = result''')
s=s[:a]+new+s[b:]
a=s.index('    def get_photos(self, project_code):'); b=s.index('    def repair_legacy_process_photo_scopes(',a)
s=s[:a]+'''    def get_photos(self, project_code):
        code = self._safe_code(project_code)
        engineering_id = active_engineering_project_id()
        key = (engineering_id, code)
        path = self._metadata_path(code)
        signature = self._metadata_signature(path)
        with self._cache_lock:
            cached = self._photos_cache.get(key)
        if signature is not None and cached is not None and cached[0] == signature:
            if not project_matches_engineering(cached[2], engineering_id):
                raise FileNotFoundError("项目不属于当前工程")
            return copy.deepcopy(cached[1])
        data = self.get_project(code)
        if not project_matches_engineering(data, engineering_id):
            raise FileNotFoundError("项目不属于当前工程")
        items = [self._photo_item(data, photo) for photo in data.get("photos", [])]
        membership = {"engineering_project_id": data.get("engineering_project_id", ""), "source_fields": data.get("source_fields", {})}
        if signature is not None and signature == self._metadata_signature(path):
            with self._cache_lock:
                if len(self._photos_cache) >= 16:
                    self._photos_cache.clear()
                self._photos_cache[key] = (signature, copy.deepcopy(items), membership)
        return items

'''+s[b:]
a=s.index('    def repair_legacy_process_photo_scopes('); b=s.index('    def optimize_existing_photo(',a); block=s[a:b]
block=block.replace('''        with self._project_write_lock(project_code):
            data = self.get_project(project_code)
''','''        cache_key = (active_engineering_project_id(), self._safe_code(project_code))
        path = self._metadata_path(project_code)
        with self._project_write_lock(project_code):
            signature = self._metadata_signature(path)
            with self._cache_lock:
                checked = self._legacy_checked.get(cache_key)
            if signature is not None and checked == signature:
                return 0
            data = self.get_project(project_code)
''')
block=block.replace('''            if not needs_repair:
                return 0
''','''            if not needs_repair:
                if signature is not None and signature == self._metadata_signature(path):
                    with self._cache_lock:
                        self._legacy_checked[cache_key] = signature
                return 0
''')
block=block.replace('''            self.invalidate_projects_cache()
            return 1
''','''            return 1
''')
s=s[:a]+block+s[b:]
repl('''        self._write_metadata(data["project_code"], data)
        self.invalidate_projects_cache()

    def _ensure_pile_sorted''','''        self._write_metadata(data["project_code"], data)

    def _ensure_pile_sorted''')
repl('''            self._write_metadata(data["project_code"], data)
            self.invalidate_projects_cache()

    def renumber_current_engineering_projects''','''            self._write_metadata(data["project_code"], data)

    def renumber_current_engineering_projects''')
a=s.index('def delete_photo(project_code, photo_id):'); b=s.index('\n\n@app.route',a); block=s[a:b]
block=block.replace('''        delete_event = {}
''','''        requested_uuid = str(payload.get("photo_uuid") or "").strip()
        delete_event = {}
''')
block=block.replace('''                if photo.get("id") == photo_id and photo_category == category:
''','''                matches = (str(photo.get("photo_uuid") or "") == requested_uuid) if requested_uuid else (photo.get("id") == photo_id)
                if matches and photo_category == category:
''')
s=s[:a]+block+s[b:]
p.write_text(s,encoding='utf-8',newline='\n')
