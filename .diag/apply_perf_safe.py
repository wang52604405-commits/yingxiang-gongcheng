from pathlib import Path
import gzip
R=Path.cwd()
def rep(text, old, new, label):
    if text.count(old)!=1: raise RuntimeError(f'{label}: expected one anchor, got {text.count(old)}')
    return text.replace(old,new,1)
p=R/'app.py'; a=p.read_text(encoding='utf-8-sig')
(R/'.diag/perf-base-app.py').write_text(a,encoding='utf-8')
a=rep(a, 'def numbering_start(category):\n    rule = read_numbering_rules().get(category) or {}', 'def numbering_start(category, rules=None):\n    rule = (read_numbering_rules() if rules is None else rules).get(category) or {}', 'numbering start snapshot')
a=rep(a, '    def _archive_id_for_photo(self, data, photo, category, sequence):', '    def _archive_id_for_photo(self, data, photo, category, sequence, settings=None):', 'archive signature')
start=a.index('    def _archive_id_for_photo('); end=a.index('    def _repair_renumber_leftovers',start)
piece=a[start:end]
piece=rep(piece,'        settings = read_engineering_settings()','        settings = self._numbering_snapshot() if settings is None else settings','archive settings')
a=a[:start]+piece+a[end:]
helper='''    def _numbering_snapshot(self):
        """One immutable-by-convention settings snapshot per operation, never a global cache."""
        settings = dict(read_engineering_settings())
        settings["numbering_rules"] = settings.get("numbering_rules") or read_numbering_rules()
        return settings

    def _numbering_is_current(self, data, settings):
        """Validate metadata only; edits must still repair legacy/gapped numbering.

        No image stat, directory scan, rename or thumbnail generation is needed
        when an ordinary unit already follows the current numbering policy.
        """
        counters = {}
        for photo in data.get("photos", []):
            category = self._normalize_category(photo.get("category"))
            process_name = str(photo.get("process_name") or "").strip()
            process_code = self._process_code(data, process_name) if process_name else ""
            scope = (category, process_code)
            index = counters.get(scope, numbering_start(category, settings["numbering_rules"]) - 1) + 1
            counters[scope] = index
            expected_id = self._archive_id_for_photo(data, photo, category, index, settings=settings)
            filename = str(photo.get("filename") or "")
            expected_name = self._photo_filename(category, expected_id, Path(filename).suffix.lower() or ".jpg", process_code)
            if (str(photo.get("id") or "") != expected_id or filename != expected_name
                    or photo.get("process_name", "") != process_name
                    or photo.get("process_code", "") != process_code):
                return False
        return True

'''
a=rep(a,'    def _archive_id_for_photo(',helper+'    def _archive_id_for_photo(', 'snapshot helper insertion')
a=rep(a,'    def _renumber_category(self, project_code, data, category):\n        category = self._normalize_category(category)', '    def _renumber_category(self, project_code, data, category, settings=None):\n        settings = self._numbering_snapshot() if settings is None else settings\n        category = self._normalize_category(category)', 'category settings')
start=a.index('    def _renumber_category(');end=a.index('    def create_project',start)
piece=a[start:end].replace('first_sequence = numbering_start(category)', 'first_sequence = numbering_start(category, settings["numbering_rules"])').replace('self._archive_id_for_photo(data, photo, category, index)', 'self._archive_id_for_photo(data, photo, category, index, settings=settings)')
a=a[:start]+piece+a[end:]
start=a.index('    def update_photo(');end=a.index('    def rename_process(', start)
piece=a[start:end]
piece=rep(piece, '                if str(photo.get("id") or "") == target_id:\n', '                if str(photo.get("id") or "") == target_id:\n                    previous_process = str(photo.get("process_name") or "").strip()\n', 'capture scope')
piece=rep(piece, '                    self._write_metadata(data["project_code"], data)\n                    self._renumber_after_change(project_code, data)\n', '''                    # The browser sends process_name even when only a caption changed.
                    # Keep pile sorting and all scope changes exactly as before. Ordinary
                    # canonical units need just one durable metadata write, not a full
                    # directory walk and two-category rename pass.
                    settings = self._numbering_snapshot()
                    scope_changed = previous_process != str(photo.get("process_name") or "").strip()
                    if is_pile_unit(data) or scope_changed or not self._numbering_is_current(data, settings):
                        self._renumber_after_change(project_code, data)
                    else:
                        self._write_metadata(data["project_code"], data)
''', 'edit fast path')
a=a[:start]+piece+a[end:]
for method,next_method in [('_auto_sort_piles_locked','_ensure_pile_sorted'),('_renumber_after_change','renumber_current_engineering_projects')]:
 start=a.index('    def '+method+'('); end=a.index('    def '+next_method+'(',start); piece=a[start:end]
 if method=='_auto_sort_piles_locked':
  piece=rep(piece,'        for category in PHOTO_CATEGORIES:\n            self._renumber_category(project_code, data, category)', '        settings = self._numbering_snapshot()\n        for category in PHOTO_CATEGORIES:\n            self._renumber_category(project_code, data, category, settings=settings)',method)
 else:
  piece=rep(piece,'            for category in PHOTO_CATEGORIES:\n                self._renumber_category(project_code, data, category)', '            settings = self._numbering_snapshot()\n            for category in PHOTO_CATEGORIES:\n                self._renumber_category(project_code, data, category, settings=settings)',method)
 a=a[:start]+piece+a[end:]
p.write_text(a,encoding='utf-8',newline='\n')
p=next((R/'assets').glob('app-A*.js')); j=p.read_text(encoding='utf-8')
helper=r'''    function applyPhotoEditResponse(data) {
      // Keep the complete collection for search, select-all and printing.
      // Preserve selection by permanent UUID if a scope/date edit renumbered IDs.
      if (!Array.isArray(data.photos)) throw new Error("照片保存结果不完整，请刷新后核实。");
      const oldPhotos = state.photos;
      const oldGallery = activeGalleryPhotos();
      const identity = (photo) => photo.photo_uuid || printSelectionKey(photo.category, photo.id);
      const selected = new Set(oldPhotos.filter((photo) => state.selectedPrintPhotos[printSelectionKey(photo.category, photo.id)]).map(identity));
      const host = $("#photoSectionsHost");
      const list = host?.querySelector(".photos");
      const oldRendered = Number(list?.dataset.rendered || 0);
      const scroll = [];
      for (let el = host; el; el = el.parentElement) scroll.push([el, el.scrollTop, el.scrollLeft]);
      state.photos = data.photos;
      if (state.selectedProject) state.selectedProject.photos = data.photos;
      state.selectedPrintPhotos = {};
      state.photos.forEach((photo) => {
        if (selected.has(identity(photo))) state.selectedPrintPhotos[printSelectionKey(photo.category, photo.id)] = true;
      });
      const nextGallery = activeGalleryPhotos();
      const nextByIdentity = new Map(state.photos.map((photo) => [identity(photo), photo]));
      const sameScopes = oldPhotos.length === state.photos.length && oldPhotos.every((photo) => {
        const next = nextByIdentity.get(identity(photo));
        return next && normalizePhotoCategory(next.category) === normalizePhotoCategory(photo.category)
          && String(next.process_name || "") === String(photo.process_name || "");
      });
      const unchangedOrder = sameScopes && oldGallery.length === nextGallery.length && oldGallery.every((photo, i) =>
        identity(photo) === identity(nextGallery[i]) && photo.id === nextGallery[i].id);
      if (list && unchangedOrder) {
        // Replace changed visible cards only. Other thumbnails stay decoded and
        // the scroll container is not rebuilt for a title/photographer edit.
        const before = new Map(oldGallery.map((photo) => [identity(photo), photo]));
        const cards = Array.from(list.querySelectorAll(".photo[data-photo-id]"));
        cards.forEach((card, i) => {
          const photo = nextGallery[i];
          if (!photo || JSON.stringify(before.get(identity(photo))) === JSON.stringify(photo)) return;
          const holder = document.createElement("div");
          holder.innerHTML = photoCardHTML(photo, state.activePhotoCategory, photoSectionKey(state.activePhotoCategory, state.activeProcessName), state.photoSelectionMode, i);
          card.replaceWith(holder.firstElementChild);
        });
        bindPhotoGalleryEvents(list);
        if (!state.photoSelectionMode) initPhotoDragSort(host);
        updatePhotoSelectionBar();
      } else {
        renderPhotos();
        const section = host?.querySelector(".photo-section");
        const nextList = section?.querySelector(".photos");
        const target = Math.min(oldRendered, nextGallery.length);
        while (nextList && Number(nextList.dataset.rendered || 0) < target) loadMorePhotos(section);
      }
      scroll.forEach(([el, top, left]) => { if (el.isConnected) { el.scrollTop = top; el.scrollLeft = left; } });
    }

    let photoEditSavePending = false;
'''
j=rep(j,'    async function savePhotoEdit(event) {\n',helper+'    async function savePhotoEdit(event) {\n','edit response helper')
start=j.index('    async function savePhotoEdit(');end=j.index('    function initPhotoForms(',start)
piece=j[start:end]
piece=rep(piece,'      if (!state.editingPhoto) return;','      if (!state.editingPhoto || photoEditSavePending) return;', 'save guard')
piece=rep(piece, '      if (!(await ensureAuthenticated("修改照片信息"))) return;', '\n'.join([
    '      const requestedEditor = state.editingPhoto;',
    '      const requestedCode = state.selectedCode;',
    '      const requestedEngineering = state.activeEngineeringProjectId;',
    '      if (!(await ensureAuthenticated("修改照片信息"))) return;',
    '      if (photoEditSavePending || state.editingPhoto !== requestedEditor || state.selectedCode !== requestedCode || state.activeEngineeringProjectId !== requestedEngineering) return;',
]), 'stale editor guard')
old='''      const data = await apiJson(`/api/photos/${encodeURIComponent(state.selectedCode)}/${encodeURIComponent(state.editingPhoto.photoId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title, photo_date: photoDate, photographer, process_name: processName, process_code: processCode, orientation, rotation, description })
      });
      state.photos = data.photos || [];
      closePhotoEdit();
      renderPhotos();
      await refreshAll();
      showNotice("照片信息已修改。");
'''
new='''      const sourceCode = state.selectedCode;
      const sourceEngineering = state.activeEngineeringProjectId;
      const editing = state.editingPhoto;
      const submit = $("#photoEditForm button[type='submit']");
      photoEditSavePending = true;
      if (submit) submit.disabled = true;
      try {
        const data = await apiJson(`/api/photos/${encodeURIComponent(sourceCode)}/${encodeURIComponent(editing.photoId)}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ title, photo_date: photoDate, photographer, process_name: processName, process_code: processCode, orientation, rotation, description })
        });
        // A late response must not overwrite a different unit/engineering context.
        if (state.selectedCode !== sourceCode || state.activeEngineeringProjectId !== sourceEngineering) return;
        applyPhotoEditResponse(data);
        if (state.editingPhoto === editing) closePhotoEdit();
        showNotice("照片信息已修改。");
      } finally {
        photoEditSavePending = false;
        if (submit) submit.disabled = false;
      }
'''
piece=rep(piece,old,new,'remove whole-project refresh')
j=j[:start]+piece+j[end:]
start=j.index('    function initPhotoDragSort(host) {');end=j.index('    // 首屏冷启动',start)
new=r'''    function initPhotoDragSort(host) {
      let dragged = null;
      host.ondragstart = (event) => {
        const card = event.target.closest(".photo[draggable='true']");
        if (!card || !host.contains(card) || state.photoSelectionMode) return;
        if (event.target.closest("input, select, textarea, label")) { event.preventDefault(); return; }
        dragged = card;
        event.dataTransfer.effectAllowed = "move";
        event.dataTransfer.setData("text/plain", card.dataset.photoId || "");
        setTimeout(() => card.classList.add("is-dragging-sort"), 0);
      };
      host.ondragend = () => {
        dragged?.classList.remove("is-dragging-sort");
        host.querySelectorAll(".photo.is-drag-over").forEach((item) => item.classList.remove("is-drag-over"));
        dragged = null;
      };
      host.ondragover = (event) => {
        const list = event.target.closest(".photos");
        if (!dragged || !list || dragged.parentElement !== list) return;
        event.preventDefault();
        const target = event.target.closest(".photo");
        if (!target || target === dragged || target.parentElement !== list) return;
        host.querySelectorAll(".photo.is-drag-over").forEach((item) => item.classList.remove("is-drag-over"));
        target.classList.add("is-drag-over");
        const rect = target.getBoundingClientRect();
        const targetCenterY = rect.top + rect.height / 2;
        const targetCenterX = rect.left + rect.width / 2;
        const insertAfter = event.clientY > targetCenterY || (Math.abs(event.clientY - targetCenterY) < rect.height / 3 && event.clientX > targetCenterX);
        list.insertBefore(dragged, insertAfter ? target.nextSibling : target);
      };
      host.ondrop = (event) => {
        const list = event.target.closest(".photos");
        if (!dragged || !list || dragged.parentElement !== list) return;
        event.preventDefault();
        const category = dragged.dataset.category || list.querySelector(".photo[data-category]")?.dataset.category || "";
        host.querySelectorAll(".photo.is-drag-over").forEach((item) => item.classList.remove("is-drag-over"));
        saveDraggedPhotoOrder(list, category).catch((error) => { showNotice(error.message, true); renderPhotos(); });
      };
    }

'''
j=j[:start]+new+j[end:]
p.write_text(j,encoding='utf-8',newline='\n')
p=R/'tests/test_z_batch_print_order.py'; t=p.read_text(encoding='utf-8')
t=rep(t, 'import unittest\n','import unittest\nfrom unittest.mock import patch\n','batch test import')
t=rep(t, '    @staticmethod\n    def _jpg', '''    def setUp(self):
        # These tests assert MEMBER batch ordering, not free-plan eligibility.
        # This scoped test double never changes production authorization rules.
        member = patch.object(self.appmod, "is_member_user", return_value=True)
        member.start()
        self.addCleanup(member.stop)

    @staticmethod
    def _jpg''','batch test member fixture')
p.write_text(t,encoding='utf-8',newline='\n')
for p in (R/'assets').glob('app-A*.js'):
 p.with_name(p.name+'.gz').write_bytes(gzip.compress(p.read_bytes(),compresslevel=6,mtime=0))
print('Applied scoped performance update; HTML/CSS, full collections, login/license and sync unchanged')
