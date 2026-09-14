from pathlib import Path
p=Path('assets/app-A20260910-2.92.js'); s=p.read_text(encoding='utf-8')
def repl(old,new,n=1):
 global s
 assert s.count(old)>=n,(old[:100],s.count(old))
 s=s.replace(old,new,n)
def fn(name,new,nextname):
 global s
 a=s.index(name); b=s.index(nextname,a)
 s=s[:a]+new+'\n\n'+s[b:]
repl('''      } catch (error) {
        if (url !== "/api/client-error") {''','''      } catch (error) {
        if (error.name === "AbortError") throw error;
        if (url !== "/api/client-error") {''')
repl('''    function setView(mode) {
      state.viewMode = mode;''','''    let unitLoadSequence = 0;
    let unitLoadController = null;
    function navigationContext() {
      return `${state.activeEngineeringProjectId}::${state.auth.user?.id || ""}::${state.auth.user?.username || ""}`;
    }
    function cancelUnitLoad() {
      unitLoadSequence += 1;
      unitLoadController?.abort();
      unitLoadController = null;
    }

    function setView(mode) {
      if (mode !== "unit") cancelUnitLoad();
      state.viewMode = mode;''')
repl('''      part.projects = [];
      part.loading = true;
      renderPart();
      setView("part");
      try {
        await loadPartPage(part, 1);''','''      const cached = part.loadedContext === navigationContext() && part.loadedRevision === state.revision;
      if (!cached) part.projects = [];
      part.loading = !cached;
      renderPart();
      setView("part");
      try {
        if (!cached) await loadPartPage(part, 1);''')
fn('    async function loadPartPage(part, page = 1) {',r'''    async function loadPartPage(part, page = 1) {
      if (!part?.partKey) { renderPart(); return; }
      const context = navigationContext();
      const revision = state.revision;
      const requestKey = `${context}::${revision}`;
      if (part.pendingKey === requestKey && part.pendingLoad) return part.pendingLoad;
      part.loading = true;
      part.loadError = "";
      if (state.selectedPart === part) renderPart();
      part.pendingKey = requestKey;
      const pending = (async () => {
        try {
          // Retain complete metadata: search/filters/selectors must not be truncated.
          const data = await apiJson(`/api/units?part_key=${encodeURIComponent(part.partKey)}&page=1&page_size=10000`);
          if (navigationContext() !== context || part.pendingKey !== requestKey) return;
          part.projects = data.projects || [];
          part.currentPage = Number(data.page || 1);
          part.totalPages = Number(data.pages || 1);
          part.unitCount = Number(data.total || part.projects.length);
          part.loadedContext = context;
          part.loadedRevision = revision;
          const byCode = new Map(state.projects.map((item) => [projectCode(item), item]));
          part.projects.forEach((project) => byCode.set(projectCode(project), project));
          state.projects = Array.from(byCode.values());
        } finally {
          if (part.pendingKey === requestKey) {
            part.loading = false;
            part.pendingLoad = null;
            if (state.selectedPart === part && navigationContext() === context) renderPart();
          }
        }
      })();
      part.pendingLoad = pending;
      return pending;
    }''','    function renderPart() {')
a=s.index('    async function loadProject(code, tab = "detail") {'); b=s.index('    function renderUnit() {',a)
old=s[a:b]; body=old[old.index('      state.selectedProject = data.project;'):]
body=body.rsplit('    }',1)[0]
new=r'''    async function loadProject(code, tab = "detail") {
      cancelUnitLoad();
      const ticket = unitLoadSequence;
      const context = navigationContext();
      const controller = new AbortController();
      unitLoadController = controller;
      const summary = state.projects.find((item) => projectCode(item) === code);
      state.selectedCode = "";
      state.selectedProject = null;
      state.photos = [];
      $("#unitTitle").textContent = summary ? projectName(summary) : "单元工程";
      $("#unitSub").textContent = `${code} · 正在读取照片`;
      $("#unitBreadcrumbs").textContent = "";
      $("#photoSectionsHost").innerHTML = '<div class="first-load-skeleton" role="status" aria-label="正在读取照片"><span></span><span></span><span></span><span></span></div>';
      $("#unitProcessTabs").innerHTML = "";
      ["#unitConstructionCount", "#unitSupervisionCount"].forEach((selector) => { if ($(selector)) $(selector).textContent = "0"; });
      if ($("#unitGalleryCount")) $("#unitGalleryCount").textContent = "正在读取";
      if ($("#photoSelectionBar")) $("#photoSelectionBar").hidden = true;
      setView("unit");
      try {
        const data = await apiJson(`/api/photos/${encodeURIComponent(code)}`, { signal: controller.signal });
        if (ticket !== unitLoadSequence || navigationContext() !== context || state.viewMode !== "unit") return;
'''+body+r'''      } catch (error) {
        if (error.name === "AbortError" || ticket !== unitLoadSequence || navigationContext() !== context) return;
        $("#photoSectionsHost").innerHTML = `<div class="empty">加载失败：${escapeHtml(error.message)} <button type="button" class="secondary mini" data-retry-unit>重新加载</button></div>`;
        $("[data-retry-unit]")?.addEventListener("click", () => loadProject(code, tab));
        showNotice(error.message, true);
      } finally {
        if (ticket === unitLoadSequence) unitLoadController = null;
      }
    }

'''
s=s[:a]+new+s[b:]
repl('''      await apiJson(`/api/photos/${encodeURIComponent(currentCode)}/processes/${encodeURIComponent(processName)}`, {
        method: "PATCH",''','''      const context = navigationContext();
      const data = await apiJson(`/api/photos/${encodeURIComponent(currentCode)}/processes/${encodeURIComponent(processName)}`, {
        method: "PATCH",''')
repl('''      if (state.activeProcessName === processName) state.activeProcessName = nextName;
      await loadProject(currentCode, "detail");''','''      if (state.selectedCode !== currentCode || navigationContext() !== context) return;
      state.selectedProject.processes = data.processes || [];
      if (state.activeProcessName === processName) state.activeProcessName = nextName;
      applyPhotoEditResponse(data);
      renderPhotos();
      scheduleSummaryRefresh();''')
repl('''      await apiJson(`/api/photos/${encodeURIComponent(currentCode)}/processes/${encodeURIComponent(processName)}`, { method: "DELETE" });
      if (state.activeProcessName === processName) state.activeProcessName = "";
      await loadProject(currentCode, "detail");''','''      const context = navigationContext();
      const data = await apiJson(`/api/photos/${encodeURIComponent(currentCode)}/processes/${encodeURIComponent(processName)}`, { method: "DELETE" });
      if (state.selectedCode !== currentCode || navigationContext() !== context) return;
      state.selectedProject.processes = data.processes || [];
      if (state.activeProcessName === processName) state.activeProcessName = "";
      applyPhotoEditResponse(data);
      renderPhotos();
      scheduleSummaryRefresh();''')
repl('''    // 照片列表分批渲染：每批 120 张，滚动到底自动加载下一批，避免一次性渲染上千节点
    const PHOTOS_BATCH = 120;
    let photoLazyObserver = null;''','''    // Only DOM is batched. Complete photo metadata remains available to selection/printing.
    const PHOTOS_BATCH = 24;
    let photoLazyObserver = null;
    let photoLazyFrame = 0;
    function scheduleLazyPhotoLoad() {
      if (!photoLazyFrame) photoLazyFrame = requestAnimationFrame(() => { photoLazyFrame = 0; setupLazyPhotoLoad(); });
    }''')
repl('''      bindPhotoGalleryEvents(listEl);
    }

    function setupLazyPhotoLoad()''','''      bindPhotoGalleryEvents(listEl);
      scheduleLazyPhotoLoad();
    }

    function setupLazyPhotoLoad()''')
fn('    function setupLazyPhotoLoad() {',r'''    function setupLazyPhotoLoad() {
      photoLazyObserver?.disconnect();
      photoLazyObserver = null;
      if (state.viewMode !== "unit") return;
      document.querySelectorAll("#photoSectionsHost .photo-section").forEach((sectionEl) => {
        const listEl = sectionEl.querySelector(".photos");
        const total = photosForSection(sectionEl.dataset.category, sectionEl.dataset.processName || "").length;
        const rendered = Number(listEl?.dataset.rendered || 0);
        let sentinel = sectionEl.querySelector("[data-photo-sentinel]");
        if (rendered >= total) { sentinel?.remove(); return; }
        if (!sentinel) {
          sentinel = document.createElement("div");
          sentinel.dataset.photoSentinel = "";
          sentinel.setAttribute("aria-hidden", "true");
          sentinel.style.cssText = "height:1px;pointer-events:none;";
          sectionEl.appendChild(sentinel);
        }
        if (!("IntersectionObserver" in window)) {
          while (Number(listEl.dataset.rendered || 0) < total) loadMorePhotos(sectionEl);
          sentinel.remove();
          return;
        }
        photoLazyObserver = photoLazyObserver || new IntersectionObserver((entries) => {
          entries.forEach((entry) => {
            if (!entry.isIntersecting || !entry.target.isConnected || state.viewMode !== "unit") return;
            const section = entry.target.closest(".photo-section");
            if (section) loadMorePhotos(section);
          });
        }, { rootMargin: "400px 0px" });
        photoLazyObserver.observe(sentinel);
      });
    }''','    function clearPhotoSelection(')
repl('''      const photos = photosForSection(category, processName);
      const categoryLabel''','''      const photos = photosForSection(category, processName);
      const renderScope = `${navigationContext()}::${state.selectedCode}::${sectionKey}`;
      const oldRendered = host.dataset.renderScope === renderScope ? Number(host.querySelector(".photos")?.dataset.rendered || 0) : 0;
      const renderLimit = Math.min(photos.length, Math.max(PHOTOS_BATCH, oldRendered));
      host.dataset.renderScope = renderScope;
      const categoryLabel''')
repl('data-rendered="${Math.min(photos.length, PHOTOS_BATCH)}"','data-rendered="${renderLimit}"')
repl('photos.slice(0, PHOTOS_BATCH).map((photo, index) => photoCardHTML','photos.slice(0, renderLimit).map((photo, index) => photoCardHTML')
repl('''        card.closest(".photos")?.querySelectorAll(".photo[data-photo-index]").forEach((item) => {
          const index = Number(item.dataset.photoIndex || 0);
          if (index < start || index > end) return;
          setPhotoSelected(item.dataset.category, item.dataset.photoId, next);
          syncPhotoCardSelection(item, next);
        });''','''        activeGalleryPhotos().slice(start, end + 1).forEach((photo) => setPhotoSelected(category, photo.id, next));
        card.closest(".photos")?.querySelectorAll(".photo[data-photo-index]").forEach((item) => {
          const index = Number(item.dataset.photoIndex || 0);
          if (index >= start && index <= end) syncPhotoCardSelection(item, next);
        });''')
repl('''      const orderedIds = Array.from(list.querySelectorAll(".photo[data-photo-id]")).map((item) => item.dataset.photoId).filter(Boolean);''','''      const visibleIds = Array.from(list.querySelectorAll(".photo[data-photo-id]")).map((item) => item.dataset.photoId).filter(Boolean);
      const visible = new Set(visibleIds);
      const section = list.closest(".photo-section");
      const orderedIds = visibleIds.concat(photosForSection(category, section?.dataset.processName || "").map((photo) => String(photo.id)).filter((id) => !visible.has(id)));''')
repl('''        .map((photo) => ({ category, photoId: String(photo.id || "") }))''','''        .map((photo) => ({ category, photoId: String(photo.id || ""), photoUuid: String(photo.photo_uuid || "") }))''')
a=s.index('    async function deleteSelectedPhotos('); b=s.index('    async function deletePhoto(',a)
block=s[a:b]
block=block.replace('''      let latestPhotos = state.photos;
      for (const item of selected) {''','''      const sourceCode = state.selectedCode;
      const sourceContext = navigationContext();
      let latestPhotos = state.photos;
      // Older imports may lack UUID: delete backwards to avoid renumbered IDs.
      const ordered = [...selected].reverse();
      for (const item of ordered) {
        const current = item.photoUuid ? latestPhotos.find((photo) => String(photo.photo_uuid || "") === item.photoUuid) : latestPhotos.find((photo) => String(photo.id) === item.photoId && normalizePhotoCategory(photo.category) === item.category);
        if (!current) throw new Error("待删除照片已发生变化，请刷新后重新选择。");''')
block=block.replace('encodeURIComponent(state.selectedCode)}/${encodeURIComponent(item.photoId)', 'encodeURIComponent(sourceCode)}/${encodeURIComponent(current.id)')
block=block.replace('JSON.stringify({ category: item.category, safety_password: safetyPassword })','JSON.stringify({ category: item.category, safety_password: safetyPassword, photo_uuid: item.photoUuid })')
block=block.replace('''        latestPhotos = data.photos || latestPhotos;
        delete state.selectedPrintPhotos[printSelectionKey(item.category, item.photoId)];''','''        if (!data.deleted) throw new Error("照片未删除，请刷新后核实，避免误删其它照片。");
        latestPhotos = data.photos || latestPhotos;''')
block=block.replace('''      state.photos = latestPhotos || [];''','''      if (state.selectedCode !== sourceCode || navigationContext() !== sourceContext) return;
      state.photos = latestPhotos || [];''')
s=s[:a]+block+s[b:]
repl('''    async function refreshAll(options = {}) {
      return loadBootstrap(options);
    }''','''    let summaryRefreshTimer = 0;
    let summaryRefreshPending = null;
    function scheduleSummaryRefresh() {
      clearTimeout(summaryRefreshTimer);
      const context = navigationContext();
      summaryRefreshTimer = setTimeout(async () => {
        if (context !== navigationContext()) return;
        if (summaryRefreshPending) { scheduleSummaryRefresh(); return; }
        summaryRefreshPending = loadBootstrap({ silent: true, skipOtherImages: true });
        try { await summaryRefreshPending; } catch (error) { showNotice("统计刷新失败，可点击刷新重试。", true); }
        finally { summaryRefreshPending = null; }
      }, 250);
    }
    async function refreshAll(options = {}) {
      return loadBootstrap(options);
    }''')
repl('''      const skipOtherImages = Boolean(options.skipOtherImages);
      bootStart();
      const data = await apiJson("/api/bootstrap");''','''      const skipOtherImages = Boolean(options.skipOtherImages);
      const context = navigationContext();
      if (!options.silent) bootStart();
      const data = await apiJson("/api/bootstrap");
      if (options.silent && context !== navigationContext()) return;''')
repl('''      bootShow();
      bootProgress(8);''','''      if (!options.silent) bootShow();
      bootProgress(8);''')
for name,nextname in [('    async function addProcess(', '    // 列表缩略图'),('    async function deleteSelectedPhotos(', '    async function deletePhoto('),('    async function deletePhoto(', '    async function reorderPhoto(')]:
 a=s.index(name); b=s.index(nextname,a)
 block=s[a:b].replace('await refreshAll();','scheduleSummaryRefresh();')
 s=s[:a]+block+s[b:]
p.write_text(s,encoding='utf-8',newline='\n')
