from pathlib import Path
p=Path('assets/app-A20260910-2.92.js');s=p.read_text(encoding='utf-8');a=s.index('    function initPhotoDragSort(host) {');b=s.index('    // 首屏冷启动',a)
s=s[:a]+'''    function initPhotoDragSort(host) {
      let dragged = null;
      let dropTarget = null;
      let dropAfter = false;
      const clearMarks = () => host.querySelectorAll(".photo.is-drag-over").forEach((item) => item.classList.remove("is-drag-over"));
      host.ondragstart = (event) => {
        const card = event.target.closest(".photo[draggable='true']");
        if (!card || !host.contains(card) || state.photoSelectionMode) return;
        if (event.target.closest("input, select, textarea, label")) { event.preventDefault(); return; }
        dragged = card;
        dropTarget = null;
        event.dataTransfer.effectAllowed = "move";
        event.dataTransfer.setData("text/plain", card.dataset.photoId || "");
        setTimeout(() => { if (dragged === card) card.classList.add("is-dragging-sort"); }, 0);
      };
      host.ondragend = () => {
        dragged?.classList.remove("is-dragging-sort");
        clearMarks();
        dragged = null;
        dropTarget = null;
      };
      host.ondragover = (event) => {
        const list = event.target.closest(".photos");
        if (!dragged || !list || dragged.parentElement !== list) return;
        event.preventDefault();
        event.dataTransfer.dropEffect = "move";
        const target = event.target.closest(".photo");
        if (!target || target === dragged || target.parentElement !== list) return;
        clearMarks();
        target.classList.add("is-drag-over");
        const rect = target.getBoundingClientRect();
        dropAfter = event.clientY > rect.top + rect.height / 2 || (Math.abs(event.clientY - rect.top - rect.height / 2) < rect.height / 3 && event.clientX > rect.left + rect.width / 2);
        dropTarget = target;
        // Moving the native drag source here can cancel Chromium's drag session,
        // leaving a reordered DOM but no drop/save. Keep it in place until drop.
      };
      host.ondrop = (event) => {
        const list = event.target.closest(".photos");
        const card = dragged;
        const target = dropTarget;
        if (!card || !list || card.parentElement !== list || !target || target.parentElement !== list || target === card) return;
        event.preventDefault();
        const category = card.dataset.category || list.querySelector(".photo[data-category]")?.dataset.category || "";
        card.classList.remove("is-dragging-sort");
        clearMarks();
        list.insertBefore(card, dropAfter ? target.nextSibling : target);
        dragged = null;
        dropTarget = null;
        saveDraggedPhotoOrder(list, category).catch((error) => { showNotice(error.message, true); renderPhotos(); });
      };
    }

'''+s[b:];p.write_text(s,encoding='utf-8',newline='\n')
p=Path('tests/run_performance_browser.py');s=p.read_text(encoding='utf-8')
old="                    print('DRAG begin',drag_id,target_id,flush=True)"
new=old+"\n                    old_dom_ids=page.evaluate('()=>Array.from(document.querySelectorAll(\"#photoSectionsHost .photo\")).map(p=>p.dataset.photoId)')"
assert old in s;s=s.replace(old,new)
old="                        page.mouse.up();print('DRAG released',flush=True)"
new="""                        assert page.evaluate('()=>Array.from(document.querySelectorAll("#photoSectionsHost .photo")).map(p=>p.dataset.photoId)')==old_dom_ids, 'dragover must not silently rearrange unsaved cards'
                        page.mouse.up();print('DRAG released',flush=True)"""
assert old in s;s=s.replace(old,new);p.write_text(s,encoding='utf-8',newline='\n')
