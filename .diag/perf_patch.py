from pathlib import Path
p=Path('assets/app-A20260910-2.92.js');s=p.read_text(encoding='utf-8');a=s.index('    function initPhotoDragSort(host) {');b=s.index('    // 首屏冷启动',a)
s=s[:a]+'''    function initPhotoDragSort(host) {
      // Internal pointer sorting avoids native OS image drag conflicts. A click
      // remains a click; only a deliberate mouse movement starts sorting.
      let candidate = null, dragging = false, dropTarget = null, dropAfter = false;
      let suppressClick = false, scrollFrame = 0, scrollBox = null;
      let lastPoint = { x: 0, y: 0 };
      const previousSelect = host.style.userSelect;
      const clearMarks = () => host.querySelectorAll(".photo.is-drag-over").forEach((item) => item.classList.remove("is-drag-over"));
      const reset = () => {
        cancelAnimationFrame(scrollFrame); scrollFrame = 0;
        if (candidate) {
          candidate.card.classList.remove("is-dragging-sort");
          try { if (candidate.card.hasPointerCapture(candidate.pointerId)) candidate.card.releasePointerCapture(candidate.pointerId); } catch (_) {}
        }
        clearMarks(); host.style.userSelect = previousSelect;
        candidate = null; dragging = false; dropTarget = null;
      };
      const markTarget = (x, y) => {
        if (!candidate) return;
        const target = document.elementFromPoint(x, y)?.closest(".photo");
        if (!target || target === candidate.card || target.parentElement !== candidate.card.parentElement) { clearMarks(); dropTarget = null; return; }
        clearMarks(); target.classList.add("is-drag-over");
        const rect = target.getBoundingClientRect();
        dropAfter = y > rect.top + rect.height / 2 || (Math.abs(y - rect.top - rect.height / 2) < rect.height / 3 && x > rect.left + rect.width / 2);
        dropTarget = target;
      };
      const scrollOnEdge = () => {
        if (!dragging || !candidate || !scrollBox) return;
        const r = scrollBox === document.scrollingElement ? { top: 0, bottom: innerHeight } : scrollBox.getBoundingClientRect();
        const top = Math.max(0, r.top), bottom = Math.min(innerHeight, r.bottom);
        const dy = lastPoint.y < top + 36 ? -12 : (lastPoint.y > bottom - 36 ? 12 : 0);
        if (dy) { scrollBox.scrollTop += dy; markTarget(lastPoint.x, lastPoint.y); }
        scrollFrame = requestAnimationFrame(scrollOnEdge);
      };
      if (host._photoDragClickGuard) host.removeEventListener("click", host._photoDragClickGuard, true);
      host._photoDragClickGuard = (event) => {
        if (!suppressClick) return;
        suppressClick = false; event.preventDefault(); event.stopImmediatePropagation();
      };
      host.addEventListener("click", host._photoDragClickGuard, true);
      host.ondragstart = (event) => { if (event.target.closest(".photo[draggable='true']")) event.preventDefault(); };
      host.ondragover = null; host.ondrop = null; host.ondragend = null;
      host.onpointerdown = (event) => {
        if (event.pointerType !== "mouse" || event.button !== 0 || state.photoSelectionMode || host.dataset.sortSaving === "1") return;
        if (event.target.closest("input, select, textarea, label")) return;
        const card = event.target.closest(".photo[draggable='true']");
        if (!card || !host.contains(card)) return;
        candidate = { card, pointerId: event.pointerId, x: event.clientX, y: event.clientY, context: navigationContext(), code: state.selectedCode };
      };
      host.onpointermove = (event) => {
        if (!candidate || event.pointerId !== candidate.pointerId) return;
        if (candidate.context !== navigationContext() || candidate.code !== state.selectedCode || !candidate.card.isConnected) { reset(); return; }
        if (!dragging) {
          if (Math.hypot(event.clientX - candidate.x, event.clientY - candidate.y) < 6) return;
          dragging = true; candidate.card.classList.add("is-dragging-sort");
          host.style.userSelect = "none"; candidate.card.setPointerCapture(event.pointerId);
        }
        event.preventDefault(); lastPoint = { x: event.clientX, y: event.clientY };
        markTarget(lastPoint.x, lastPoint.y);
        if (!scrollFrame) {
          scrollBox = host;
          while (scrollBox && !(scrollBox.scrollHeight > scrollBox.clientHeight + 1 && /auto|scroll/.test(getComputedStyle(scrollBox).overflowY))) scrollBox = scrollBox.parentElement;
          scrollBox = scrollBox || document.scrollingElement;
          scrollFrame = requestAnimationFrame(scrollOnEdge);
        }
      };
      host.onpointerup = (event) => {
        if (!candidate || event.pointerId !== candidate.pointerId) return;
        const current = candidate, target = dropTarget, after = dropAfter, didDrag = dragging;
        const list = current.card.parentElement;
        reset();
        if (!didDrag) return;
        event.preventDefault(); suppressClick = true;
        setTimeout(() => { suppressClick = false; }, 0);
        if (!target || !list || target.parentElement !== list || current.code !== state.selectedCode || current.context !== navigationContext()) return;
        list.insertBefore(current.card, after ? target.nextSibling : target);
        host.dataset.sortSaving = "1";
        saveDraggedPhotoOrder(list, current.card.dataset.category || state.activePhotoCategory)
          .catch((error) => {
            showNotice(error.message, true);
            if (current.code === state.selectedCode && current.context === navigationContext()) renderPhotos();
          })
          .finally(() => { delete host.dataset.sortSaving; });
      };
      host.onpointercancel = reset;
      host.onkeydown = (event) => { if (event.key === "Escape" && candidate) { event.preventDefault(); reset(); } };
    }

'''+s[b:];p.write_text(s,encoding='utf-8',newline='\n')
p=Path('tests/run_performance_browser.py');s=p.read_text(encoding='utf-8')
old="                    def delay(route):time.sleep(.25);route.continue_()"
new="""                    import zipfile, xml.etree.ElementTree as ET
                    current=m.get_photos('U-MAIN')
                    page.locator('#unitMoreMenuBtn').click()
                    with page.expect_download() as download:page.locator('#exportZipBtn').click()
                    package=out/'unit-export.zip';download.value.save_as(package)
                    with zipfile.ZipFile(package) as archive:
                        assert archive.testzip() is None
                        metadata=json.loads(archive.read('metadata.json'))
                        assert {p['photo_uuid'] for p in metadata['photos']}=={p['photo_uuid'] for p in current}
                        for photo in current:assert 'photos/'+photo['filename'] in archive.namelist()
                    if not page.locator('#unitMoreMenu.open').count():page.locator('#unitMoreMenuBtn').click()
                    with page.expect_download() as download:page.locator('#exportUnitStatsBtn').click()
                    stats=out/'unit-statistics.xlsx';download.value.save_as(stats)
                    with zipfile.ZipFile(stats) as archive:
                        sheet=ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
                        rows=sheet.findall('.//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}sheetData/{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row')
                        assert len(rows)==len(current)+1,(len(rows),len(current))
                    page.keyboard.press('Escape');check('real unit ZIP and statistics downloads contain every retained photo')
                    def delay(route):time.sleep(.25);route.continue_()"""
assert old in s;s=s.replace(old,new)
old="page.evaluate('()=>{loadProject(\"U-MAIN\");openOverview();}');page.wait_for_timeout(500)"
new="page.evaluate('()=>{loadProject(\"U-MAIN\");if(!document.querySelector(\"#galleryUploadBtn\").disabled)throw new Error(\"Loading view exposes wrong-unit action\");openOverview();}');page.wait_for_timeout(500)"
assert old in s;s=s.replace(old,new)
old="                    assert not errors,errors;check('all retained originals unchanged; no uncaught browser errors')"
new=old+"""
                    page.locator('#logoutBtn').click()
                    page.wait_for_function('()=>!state.auth.user')
                    assert context.request.get(origin+'/api/units?part_key=invalid').status==401
                    page.screenshot(path=str(out/'logged-out.png'));check('logout ends the real local session and protected operations reject it')"""
assert old in s;s=s.replace(old,new);p.write_text(s,encoding='utf-8',newline='\n')
