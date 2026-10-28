const $ = (selector) => document.querySelector(selector);
    // 助手正常会很快关闭当前程序；仍持续返回“安装中”时也必须脱离遮罩，
    // 给用户明确失败和安全重试入口，不能只在网络断开时才检查超时。
    const UPDATE_INSTALL_WATCHDOG_MS = 90 * 1000;
    const state = {
      dashboard: {},
      projectInfo: {},
      engineeringSettings: {},
      engineeringProjects: [],
      activeEngineeringProjectId: "",
      projects: [],
      allProjectsLoaded: false,
      hierarchy: [],
      revision: 0,
      treeRoot: null,
      expanded: new Set(),
      selectedPart: null,
      selectedProject: null,
      selectedCode: "",
      photos: [],
      viewMode: "overview",
      overviewScope: "construction",
      treeLevelFilter: "all",
      unitPage: 1,
      unitListQuery: "",
      unitUploadFilter: "all",
      moveTargets: [],
      pageSize: 20,
      photoPage: { construction: 1, supervision: 1 },
      photoPageSize: 18,
      unitImages: null,
      activeUnitImageCategory: "",
      unitImagePickerKey: "",
      pickerExpanded: new Set(),
      otherImages: { nodes: [], photo_count: 0 },
      otherExpanded: new Set(),
      selectedOtherCode: "",
      otherImageParentCode: "",
      uploadChoiceCategory: "construction",
      pendingUploadCategory: "",
      batchPrintCategory: "construction",
      batchPrintMode: "print",
      printPageSize: 4,
      printStyle: "default",
      pendingPrintUrl: "",
      printSourceUrl: "",
      batchSelectedUnits: new Set(),
      batchSelectedProcesses: new Set(),
      batchSelectionOrder: [],
      batchVisibleCodes: [],
      photoPreviewScale: 1,
      photoPreviewFitScale: 1,
      editingPhoto: null,
      folderReviewFiles: [],
      folderReviewRows: [],
      folderReviewCategory: "construction",
      batchTouchY: 0,
      photoSelectMode: {},
      selectedPrintPhotos: {},
      activePhotoCategory: "construction",
      activeProcessName: "",
      photoSelectionMode: false,
      photoSelectionAnchor: -1,
      uploadQueuedFiles: [],
      uploadQueueResults: [],
      overviewExpandedUnits: new Set(),
      optimizationStatus: {},
      projectMembers: [],
      projectInvites: [],
      projectMembership: {},
      projectMembersProjectId: "",
      projectMembersLoading: false,
      projectMembersError: "",
      latestProjectInvite: null,
      update: {
        manifest: null,
        checkPromise: null,
        pollTimer: null,
        pollFailures: 0,
        lastActiveState: "checking",
        installingSince: 0,
        reloadScheduled: false
      },
      auth: { user: null }
    };

    const photoCategories = [
      { key: "construction" },
      { key: "supervision" }
    ];

    function normalizePhotoCategory(category) {
      return category === "supervision" ? "supervision" : "construction";
    }

    function categoryPhotos(category) {
      return state.photos.filter((photo) => normalizePhotoCategory(photo.category) === category);
    }

    function printSelectionKey(category, photoId) {
      return `${normalizePhotoCategory(category)}::${String(photoId || "")}`;
    }

    function selectedPrintIds(category) {
      const prefix = `${normalizePhotoCategory(category)}::`;
      return Object.keys(state.selectedPrintPhotos || {})
        .filter((key) => key.startsWith(prefix) && state.selectedPrintPhotos[key])
        .map((key) => key.slice(prefix.length))
        .filter(Boolean);
    }

    function photoSectionKey(category, processName = "") {
      return `${normalizePhotoCategory(category)}::${String(processName || "")}`;
    }

    function selectedProcesses() {
      const proj = state.selectedProject || {};
      return Array.isArray(proj.processes) ? proj.processes : [];
    }

    function isProcessProject() {
      const proj = state.selectedProject || {};
      return Array.isArray(proj.processes) && proj.processes.length > 0;
    }

    function processCodeForName(name) {
      const settings = state.engineeringSettings || {};
      const index = Math.max(1, selectedProcesses().indexOf(name) + 1);
      const digits = Math.max(1, Math.min(8, Number(settings.process_digits || 3)));
      return `GY${String(index).padStart(digits, "0")}`;
    }

    function displayPhotoDate(photo) {
      return String(photo.photo_date || "").slice(0, 10);
    }

    function normalizePhotoOrientation(orientation) {
      return orientation === "portrait" ? "portrait" : "landscape";
    }

    function photoOrientationLabel(orientation) {
      return normalizePhotoOrientation(orientation) === "portrait" ? "竖版" : "横版";
    }

    // 照片编号尾部（SY001 / JY001），从编号提取最后一个 SY/JY 段
    // 从文件名提取日期（前端版，与后端 parse_photo_name_parts 规则一致）
    function parseDateFromName(name) {
      const text = String(name || "");
      let m = text.match(/(20\d{2})\s*[年.\-/]\s*(\d{1,2})\s*[月.\-/]\s*(\d{1,2})\s*日?/);
      if (m) return `${m[1]}-${String(m[2]).padStart(2, "0")}-${String(m[3]).padStart(2, "0")}`;
      m = text.match(/(20\d{2})(\d{2})(\d{2})/);
      if (m) return `${m[1]}-${m[2]}-${m[3]}`;
      const now = new Date().getFullYear();
      m = text.match(/(\d{1,2})\s*月\s*(\d{1,2})\s*日/);
      if (m) return `${now}-${String(m[1]).padStart(2, "0")}-${String(m[2]).padStart(2, "0")}`;
      return "";
    }

    // 选文件后自动填充题名/日期（文件名含日期和文字时）
    function autoFillUploadFromFiles(files, titleSel, dateSel) {
      const first = files && files[0] ? files[0].name : "";
      if (!first) return;
      const titleInput = $(titleSel);
      const dateInput = $(dateSel);
      if (titleInput && !titleInput.value.trim()) {
        const clean = first.replace(/\.(jpe?g|png)$/i, "")
          .replace(/^(?:IMG|VID|DSC|PANO)_?/, "")
          .replace(/(20\d{2})\s*[年.\-/]\s*\d{1,2}\s*[月.\-/]\s*\d{1,2}\s*日?/, "")
          .replace(/(20\d{2})(\d{2})(\d{2})/, "")
          .replace(/^\s*\d+[号#\s]*/, "")
          .replace(/^[\s_\-—–·.]+|[\s_\-—–·.]+$/, "");
        if (clean) titleInput.value = clean;
      }
      if (dateInput && !dateInput.value) {
        const d = parseDateFromName(first);
        if (d) dateInput.value = d;
      }
    }

    function photoIdTail(photo) {
      const id = String(photo.id || "");
      const m = id.match(/(?:SY|JY)\d+$/i) || id.match(/(?:SY|JY)\d+/i);
      return m ? m[0] : id;
    }

    // 缩略图题名 = 完整题名 + 尾部编号（如 "右岸Q11-3钻孔深度20米-SY01"），不使用桩号/工序缩写
    function photoShortLabel(photo) {
      const title = String(photo.title || "").trim();
      const tail = photoIdTail(photo);
      const name = title || String(photo.original_name || "").trim();
      return name ? `${name}-${tail}` : tail;
    }

    const PINYIN_INITIALS = {
      a: "岸安按暗案",
      b: "坝板背泵标保北边部玻",
      c: "仓槽层程池出衬侧村",
      d: "堤底段洞道电点顶东导",
      e: "二",
      f: "防分封缝房方附扶",
      g: "工管灌沟钢高固构过",
      h: "混涵河洪横护化海后厚",
      j: "井浆基机监检接结金进降浇",
      k: "口孔坑开控",
      l: "梁廊路龙连临栏砌拦",
      m: "面门明模末",
      n: "南内",
      p: "坡排平铺喷",
      q: "墙桥渠强清启前",
      r: "人闸入",
      s: "水砂石施输伸上竖速室",
      t: "土台填通天条铜",
      w: "围外弯稳完五",
      x: "线箱消小下斜新形向",
      y: "翼右隐预压沿验引永",
      z: "左桩注支止闸中纵砖"
    };
    const INITIAL_BY_CHAR = Object.entries(PINYIN_INITIALS).reduce((map, [initial, chars]) => {
      Array.from(chars).forEach((char) => { map[char] = initial; });
      return map;
    }, {});

    function acronymText(value) {
      return Array.from(String(value || "")).map((char) => {
        if (/[A-Za-z0-9]/.test(char)) return char.toLowerCase();
        return INITIAL_BY_CHAR[char] || "";
      }).join("");
    }

    const aliases = {
      contractName: ["合同工程名称", "鍚堝悓宸ョ▼鍚嶇О"],
      unitProjectName: ["单位工程名称", "鍗曚綅宸ョ▼鍚嶇О"],
      unitProjectCode: ["单位工程编码", "单位工程编号", "鍗曚綅宸ョ▼缂栫爜", "鍗曚綅宸ョ▼缂栧彿"],
      unitProjectCombined: ["单位工程名称及编码", "单位工程", "鍗曚綅宸ョ▼鍚嶇О鍙婄紪鐮", "鍗曚綅宸ョ▼"],
      partName: ["分部工程名称", "分项工程名称", "鍒嗛儴宸ョ▼鍚嶇О", "鍒嗛」宸ョ▼鍚嶇О"],
      partCode: ["分部工程编码", "分部工程编号", "分项工程编码", "鍒嗛儴宸ョ▼缂栫爜", "鍒嗛儴宸ョ▼缂栧彿"],
      partCombined: ["分部工程名称及编码", "分部工程", "分项工程", "鍒嗛儴宸ョ▼鍚嶇О鍙婄紪鐮", "鍒嗛儴宸ョ▼", "鍒嗛」宸ョ▼"],
      unitName: ["单元工程名称", "单元名称", "鍗曞厓宸ョ▼鍚嶇О", "鍗曞厓鍚嶇О"],
      unitCode: ["单元工程编码", "单元工程编号", "单元编码", "鍗曞厓宸ョ▼缂栫爜", "鍗曞厓宸ョ▼缂栧彿", "鍗曞厓缂栫爜"]
    };

    const UNIT_IMAGE_STORAGE_KEY = "unit-image-manager-v1";
    const UNIT_IMAGE_DEFAULTS = {
      construction: {
        label: "施工单元影像",
        baseCode: "GC-001-01-001",
        projectName: "",
        title: "",
        date: "",
        photographer: "",
        description: "",
        photos: []
      },
      supervision: {
        label: "监理单元影像",
        baseCode: "GC-001-01-001",
        projectName: "",
        title: "",
        date: "",
        photographer: "",
        description: "",
        photos: []
      }
    };

    function cloneUnitImageDefaults() {
      return JSON.parse(JSON.stringify(UNIT_IMAGE_DEFAULTS));
    }

    function loadUnitImages() {
      const defaults = cloneUnitImageDefaults();
      try {
        const saved = JSON.parse(localStorage.getItem(UNIT_IMAGE_STORAGE_KEY) || "{}");
        state.unitImages = {
          construction: {
            ...defaults.construction,
            ...(saved.construction || {}),
            photos: Array.isArray(saved.construction?.photos) ? saved.construction.photos : []
          },
          supervision: {
            ...defaults.supervision,
            ...(saved.supervision || {}),
            photos: Array.isArray(saved.supervision?.photos) ? saved.supervision.photos : []
          }
        };
      } catch {
        state.unitImages = defaults;
      }
      Object.keys(state.unitImages).forEach(renumberUnitImages);
    }

    function saveUnitImages() {
      localStorage.setItem(UNIT_IMAGE_STORAGE_KEY, JSON.stringify(state.unitImages));
    }

    function renumberUnitImages(unitKey) {
      const unit = state.unitImages[unitKey];
      const counters = new Map();
      unit.photos.forEach((photo) => {
        photo.baseCode = photo.baseCode || unit.baseCode;
        photo.projectName = photo.projectName || unit.projectName || "";
        const baseCode = photo.baseCode || unit.baseCode;
        const next = (counters.get(baseCode) || 0) + 1;
        counters.set(baseCode, next);
        photo.number = `${baseCode}-YX${String(next).padStart(3, "0")}`;
      });
    }

    function syncUnitImageForm(unitKey) {
      const unit = state.unitImages[unitKey];
      unit.baseCode = $(`#${unitKey}BaseCode`).value.trim() || UNIT_IMAGE_DEFAULTS[unitKey].baseCode;
      unit.title = $(`#${unitKey}ImageTitle`).value.trim();
      unit.date = $(`#${unitKey}ImageDate`).value;
      unit.photographer = $(`#${unitKey}ImagePhotographer`).value.trim();
      unit.description = $(`#${unitKey}ImageDescription`).value.trim();
      renumberUnitImages(unitKey);
      saveUnitImages();
      renderUnitImageSection(unitKey);
    }

    function unitImageRecords(unit) {
      const groups = new Map();
      unit.photos.forEach((photo, index) => {
        const batchId = photo.batchId || `${photo.uploadTime || ""}|${photo.baseCode || unit.baseCode}|${photo.title || ""}`;
        photo.batchId = batchId;
        if (!groups.has(batchId)) {
          groups.set(batchId, {
            batchId,
            baseCode: photo.baseCode || unit.baseCode,
            projectName: photo.projectName || unit.projectName || "",
            title: photo.title || "",
            date: photo.date || "",
            photographer: photo.photographer || "",
            description: photo.description || "",
            uploadTime: photo.uploadTime || "",
            uploadedBy: photo.uploadedBy || "本机",
            photos: [],
            indexes: []
          });
        }
        const group = groups.get(batchId);
        group.photos.push(photo);
        group.indexes.push(index);
      });
      return Array.from(groups.values()).sort((a, b) => String(b.uploadTime).localeCompare(String(a.uploadTime)) || String(b.date).localeCompare(String(a.date)));
    }

    function openUnitImageRecord(unitKey, batchId) {
      const record = unitImageRecords(state.unitImages[unitKey]).find((item) => item.batchId === batchId);
      if (!record) return;
      if (state.projects.some((project) => projectCode(project) === record.baseCode)) {
        loadProject(record.baseCode, "detail").catch((error) => showNotice(error.message, true));
        return;
      }
      showNotice("未在项目划分表中找到该单元，无法打开单元页面。", true);
    }

    function deleteUnitImageRecord(unitKey, batchId) {
      const unit = state.unitImages[unitKey];
      unit.photos = unit.photos.filter((photo) => photo.batchId !== batchId);
      renumberUnitImages(unitKey);
      saveUnitImages();
      renderUnitImageSection(unitKey);
      showNotice("上传记录已删除，编号已重排。");
    }

    function renderUnitImageSection(unitKey) {
      const unit = state.unitImages[unitKey];
      $(`#${unitKey}BaseCode`).value = unit.baseCode;
      $(`#${unitKey}ImageTitle`).value = unit.title;
      $(`#${unitKey}ImageDate`).value = unit.date;
      $(`#${unitKey}ImagePhotographer`).value = unit.photographer;
      $(`#${unitKey}ImageDescription`).value = unit.description;

      const list = $(`#${unitKey}UnitImageList`);
      if (!unit.photos.length) {
        list.innerHTML = `<div class="unit-image-empty">暂无照片，上传后将自动生成编号。</div>`;
        return;
      }

      const records = unitImageRecords(unit);
      list.innerHTML = `
        <div class="unit-image-records">
          <table>
            <thead>
              <tr>
                <th>上传记录</th>
                <th>单元编号</th>
                <th>影像日期</th>
                <th>上传日期</th>
                <th>上传账号</th>
                <th>张数</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              ${records.map((record) => `
                <tr>
                  <td>
                    <div class="record-title">
                      <strong>${escapeHtml(record.title || record.projectName || record.baseCode)}</strong>
                      <span>${escapeHtml(record.description || "-")}</span>
                    </div>
                  </td>
                  <td class="code">${escapeHtml(record.baseCode)}</td>
                  <td>${escapeHtml(record.date || "-")}</td>
                  <td>${escapeHtml(record.uploadTime || "-")}</td>
                  <td>${escapeHtml(record.uploadedBy || "-")}</td>
                  <td>${record.photos.length}</td>
                  <td>
                    <div class="row-actions">
                      <button class="secondary mini" type="button" data-unit-image-open="${unitKey}" data-batch="${escapeHtml(record.batchId)}">详情</button>
                      <button class="danger mini" type="button" data-unit-image-delete="${unitKey}" data-batch="${escapeHtml(record.batchId)}">删除</button>
                    </div>
                  </td>
                </tr>
              `).join("")}
            </tbody>
          </table>
        </div>
      `;

      list.querySelectorAll("[data-unit-image-open]").forEach((button) => {
        button.addEventListener("click", () => openUnitImageRecord(button.dataset.unitImageOpen, button.dataset.batch));
      });
      list.querySelectorAll("[data-unit-image-delete]").forEach((button) => {
        button.addEventListener("click", () => {
          deleteUnitImageRecord(button.dataset.unitImageDelete, button.dataset.batch);
        });
      });
    }

    function renderUnitImages() {
      const activeKey = state.activeUnitImageCategory;
      $("#unitImageEntrances").style.display = activeKey ? "none" : "";
      $("#unitImageActiveWrap").style.display = activeKey ? "" : "none";

      ["construction", "supervision"].forEach((unitKey) => {
        const board = document.querySelector(`[data-unit-image-board="${unitKey}"]`);
        if (board) board.style.display = activeKey === unitKey ? "" : "none";
      });

      if (!activeKey) return;
      $("#unitImageActiveTitle").textContent = state.unitImages[activeKey].label;
      renderUnitImageSection(activeKey);
    }

    async function openProjectPicker(unitKey) {
      state.unitImagePickerKey = unitKey;
      $("#projectPickerSearch").value = "";
      $("#projectPickerSub").textContent = `${state.unitImages[unitKey].label}：选择一个单元工程作为编号来源。`;
      $("#projectPickerModal").classList.add("open");
      $("#projectPickerModal").setAttribute("aria-hidden", "false");
      $("#projectPickerBody").innerHTML = `<div class="unit-image-empty">正在加载单元工程…</div>`;
      await ensureAllProjectsLoaded();
      renderProjectPicker();
      setTimeout(() => $("#projectPickerSearch").focus(), 0);
    }

    function closeProjectPicker() {
      $("#projectPickerModal").classList.remove("open");
      $("#projectPickerModal").setAttribute("aria-hidden", "true");
      state.unitImagePickerKey = "";
    }

    function projectPickerText(project) {
      const h = getHierarchy(project);
      const parts = [
        h.contractName,
        h.unitProjectName,
        h.unitProjectCode,
        h.partName,
        h.partCode,
        h.unitName,
        h.unitCode,
        projectCode(project)
      ];
      return `${parts.join(" ")} ${parts.map(acronymText).join(" ")}`.toLowerCase();
    }

    function renderPickerProject(project) {
      const h = getHierarchy(project);
      const code = projectCode(project);
      const activeClass = state.selectedCode === code ? " active" : "";
      return `
        <button class="picker-project${activeClass}" type="button" data-picker-code="${escapeHtml(code)}">
          <strong>${escapeHtml(h.unitName || projectName(project))}</strong>
          <span>${escapeHtml(h.unitCode || code)}</span>
        </button>
      `;
    }

    function pickerProjectCount(node) {
      if (!node) return 0;
      if (node.type === "part") return node.projects.length || Number(node.unitCount || 0);
      return node.children.reduce((sum, childNode) => sum + pickerProjectCount(childNode), 0);
    }

    function partHierarchyLookupKey(part) {
      const unit = part?.parent;
      const contract = unit?.parent;
      return [contract?.name, unit?.name, unit?.code, part?.name, part?.code]
        .map((value) => String(value || "").trim())
        .join("\u001f");
    }

    function projectHierarchyLookupKey(project) {
      const h = getHierarchy(project);
      return [h.contractName, h.unitProjectName, h.unitProjectCode, h.partName, h.partCode]
        .map((value) => String(value || "").trim())
        .join("\u001f");
    }

    function hydrateTreeProjects(root, projects) {
      const parts = [];
      const byPartKey = new Map();
      const byHierarchy = new Map();
      const walk = (node) => {
        if (!node) return;
        if (node.type === "part") {
          node.projects = [];
          parts.push(node);
          if (node.partKey) byPartKey.set(String(node.partKey), node);
          byHierarchy.set(partHierarchyLookupKey(node), node);
          return;
        }
        node.children.forEach(walk);
      };
      walk(root);
      (projects || []).forEach((project) => {
        const partKey = String(project?.part_key || "");
        const part = (partKey && byPartKey.get(partKey)) || byHierarchy.get(projectHierarchyLookupKey(project));
        if (part) part.projects.push(project);
      });
      parts.forEach((part) => {
        part.projects.sort((a, b) => (projectOrder(a) - projectOrder(b)) || compareNatural(projectCode(a), projectCode(b)));
        if (part.projects.length) part.unitCount = part.projects.length;
      });
    }

    function ensurePickerExpanded() {
      if (!state.treeRoot || state.pickerExpanded.size) return;
      state.treeRoot.children.forEach((contract, index) => {
        if (index === 0) {
          state.pickerExpanded.add(contract.key);
          const firstUnit = contract.children[0];
          if (firstUnit) {
            state.pickerExpanded.add(firstUnit.key);
            const firstPart = firstUnit.children[0];
            if (firstPart) state.pickerExpanded.add(firstPart.key);
          }
        }
      });
    }

    function renderPickerTreeNode(node) {
      if (!node) return "";
      if (node.type === "root") {
        ensurePickerExpanded();
        return node.children.map(renderPickerTreeNode).join("");
      }
      const className = node.type === "contract" ? "picker-contract" : node.type === "unitProject" ? "picker-unit" : "picker-part";
      const headClass = `${className}-head`;
      const isOpen = state.pickerExpanded.has(node.key);
      const count = pickerProjectCount(node);
      const childHtml = node.type === "part"
        ? `<div class="picker-projects">${node.projects.map(renderPickerProject).join("") || `<div class="empty">暂无单元工程</div>`}</div>`
        : node.children.map(renderPickerTreeNode).join("");
      return `
        <section class="${className}">
          <button class="${headClass}" type="button" data-picker-toggle="${escapeHtml(node.key)}">
            <span class="picker-head-main">
              <span class="picker-caret">${isOpen ? "▾" : "▸"}</span>
              <span>${escapeHtml(displayTreeNodeName(node) || "未命名")}</span>
            </span>
            <span class="picker-count">${escapeHtml(node.code || "")}${node.code ? " · " : ""}${count} 个</span>
          </button>
          ${isOpen ? childHtml : ""}
        </section>
      `;
    }

    function bindPickerTreeEvents(body, onSelect) {
      body.querySelectorAll("[data-picker-toggle]").forEach((button) => {
        button.addEventListener("click", () => {
          const key = button.dataset.pickerToggle;
          state.pickerExpanded.has(key) ? state.pickerExpanded.delete(key) : state.pickerExpanded.add(key);
          onSelect === selectUploadProject ? renderUploadProjectPicker() : renderProjectPicker();
        });
      });
      body.querySelectorAll("[data-picker-code]").forEach((button) => {
        button.addEventListener("click", () => onSelect(button.dataset.pickerCode));
      });
    }

    function batchLabel(category) {
      return normalizePhotoCategory(category) === "supervision" ? "监理" : "施工";
    }

    function syncBatchPrintCategoryButtons() {
      const active = normalizePhotoCategory(state.batchPrintCategory);
      document.querySelectorAll("[data-batch-category]").forEach((button) => {
        const isActive = normalizePhotoCategory(button.dataset.batchCategory) === active;
        button.classList.toggle("active", isActive);
        button.setAttribute("aria-pressed", isActive ? "true" : "false");
      });
    }

    async function openBatchPrint(category, mode = "print") {
      const [productData, licenseData] = await Promise.all([
        apiJson("/api/cloud/product-config").catch(() => ({ product: {} })),
        apiJson("/api/license/status").catch(() => ({ license: {} }))
      ]);
      const freePolicy = productData?.product?.free || {};
      const license = licenseData?.license || {};
      if (!license.ok && freePolicy.batch_print_enabled !== true) {
        showNotice("免费版不支持批量打印，请进入单元后选择“打印当前”。", true);
        return;
      }
      state.batchPrintCategory = normalizePhotoCategory(category);
      state.batchPrintMode = mode === "pdf" ? "pdf" : "print";
      state.batchSelectedUnits = new Set();
      state.batchSelectedProcesses = new Set();
      state.batchSelectionOrder = [];
      state.batchVisibleCodes = [];
      $("#batchPrintTitle").textContent = `${batchLabel(state.batchPrintCategory)}${state.batchPrintMode === "pdf" ? "批量导出PDF" : "批量打印"}`;
      syncBatchPrintCategoryButtons();
      $("#batchPrintSearch").value = "";
      $("#batchPrintModal").classList.add("open");
      $("#batchPrintModal").setAttribute("aria-hidden", "false");
      $("#batchPrintBody").innerHTML = `<div class="unit-image-empty">正在加载单元工程…</div>`;
      await ensureAllProjectsLoaded();
      renderBatchPrintPicker();
      resizeBatchPrintBody();
      $("#batchPrintBody").scrollTop = 0;
      setTimeout(() => $("#batchPrintSearch").focus(), 0);
    }

    function closeBatchPrint() {
      $("#batchPrintModal").classList.remove("open");
      $("#batchPrintModal").setAttribute("aria-hidden", "true");
      state.batchVisibleCodes = [];
    }

    function renderBatchProject(project) {
      const h = getHierarchy(project);
      const code = projectCode(project);
      const hasProcess = Array.isArray(project.processes) && project.processes.length > 0;
      const unitOn = state.batchSelectedUnits.has(code);
      const procOn = hasProcess && state.batchSelectedProcesses.has(code);
      const activeClass = unitOn || procOn ? " active" : "";
      const procBtn = hasProcess
        ? `<button type="button" class="batch-level${procOn ? " active" : ""}" data-batch-process="${escapeHtml(code)}">工序</button>`
        : "";
      return `
        <div class="picker-project batch-project${activeClass}" data-batch-code="${escapeHtml(code)}">
          <strong>${escapeHtml(h.unitName || projectName(project))}</strong>
          <span>${escapeHtml(h.unitCode || code)}</span>
          <div class="batch-level-buttons">
            <button type="button" class="batch-level${unitOn ? " active" : ""}" data-batch-unit="${escapeHtml(code)}">单元</button>
            ${procBtn}
          </div>
        </div>
      `;
    }

    function nodeDescendantCodes(node) {
      if (!node) return [];
      if (node.type === "part") return node.projects.map(projectCode).filter(Boolean);
      return node.children.flatMap((childNode) => nodeDescendantCodes(childNode));
    }

    function nodeAllSelected(node) {
      const codes = nodeDescendantCodes(node);
      return codes.length > 0 && codes.every((code) => state.batchSelectedUnits.has(code) && state.batchSelectedProcesses.has(code));
    }

    function renderBatchTreeNode(node) {
      if (!node) return "";
      if (node.type === "root") {
        ensurePickerExpanded();
        return node.children.map(renderBatchTreeNode).join("");
      }
      const className = node.type === "contract" ? "picker-contract" : node.type === "unitProject" ? "picker-unit" : "picker-part";
      const headClass = `${className}-head`;
      const isOpen = state.pickerExpanded.has(node.key);
      const count = pickerProjectCount(node);
      const allSelected = nodeAllSelected(node);
      const childHtml = node.type === "part"
        ? `<div class="picker-projects">${node.projects.map(renderBatchProject).join("") || `<div class="empty">暂无单元工程</div>`}</div>`
        : node.children.map(renderBatchTreeNode).join("");
      return `
        <section class="${className}">
          <div class="${headClass}">
            <button class="picker-head-toggle" type="button" data-batch-toggle="${escapeHtml(node.key)}">
              <span class="picker-head-main">
                <span class="picker-caret">${isOpen ? "▾" : "▸"}</span>
                <span>${escapeHtml(displayTreeNodeName(node) || "未命名")}</span>
              </span>
              <span class="picker-count">${escapeHtml(node.code || "")}${node.code ? " · " : ""}${count} 个</span>
            </button>
            <button class="batch-node-select${allSelected ? " active" : ""}" type="button" data-batch-select-node="${escapeHtml(node.key)}">${allSelected ? "☑ 已全选" : "☐ 全选"}</button>
          </div>
          ${isOpen ? childHtml : ""}
        </section>
      `;
    }

    function bindBatchPrintEvents() {
      const body = $("#batchPrintBody");
      body.querySelectorAll("[data-batch-toggle]").forEach((button) => {
        button.addEventListener("click", () => {
          const key = button.dataset.batchToggle;
          state.pickerExpanded.has(key) ? state.pickerExpanded.delete(key) : state.pickerExpanded.add(key);
          renderBatchPrintPicker();
        });
      });
      body.querySelectorAll("[data-batch-unit]").forEach((button) => {
        button.addEventListener("click", () => {
          const code = button.dataset.batchUnit;
          if (state.batchSelectedUnits.has(code)) {
            state.batchSelectedUnits.delete(code);
          } else {
            state.batchSelectedUnits.add(code);
          }
          syncBatchSelectionOrder();
          renderBatchPrintPicker();
        });
      });
      body.querySelectorAll("[data-batch-process]").forEach((button) => {
        button.addEventListener("click", () => {
          const code = button.dataset.batchProcess;
          if (state.batchSelectedProcesses.has(code)) {
            state.batchSelectedProcesses.delete(code);
          } else {
            state.batchSelectedProcesses.add(code);
          }
          syncBatchSelectionOrder();
          renderBatchPrintPicker();
        });
      });
      body.querySelectorAll("[data-batch-select-node]").forEach((button) => {
        button.addEventListener("click", () => {
          const node = findNode(state.treeRoot, button.dataset.batchSelectNode);
          const codes = nodeDescendantCodes(node);
          if (!codes.length) return;
          const allSelected = codes.every((code) => state.batchSelectedUnits.has(code) && state.batchSelectedProcesses.has(code));
          codes.forEach((code) => {
            if (allSelected) {
              state.batchSelectedUnits.delete(code);
              state.batchSelectedProcesses.delete(code);
            } else {
              state.batchSelectedUnits.add(code);
              state.batchSelectedProcesses.add(code);
            }
          });
          syncBatchSelectionOrder();
          renderBatchPrintPicker();
        });
      });
    }

    function batchSelectionCodes() {
      return [...state.batchSelectedUnits, ...state.batchSelectedProcesses].map((item) => String(item));
    }

    function syncBatchSelectionOrder() {
      const selected = new Set(batchSelectionCodes());
      const present = new Set();
      const kept = (Array.isArray(state.batchSelectionOrder) ? state.batchSelectionOrder : [])
        .map((item) => String(item))
        .filter((code) => selected.has(code) && !present.has(code) && present.add(code));
      const appended = batchSelectionCodes().filter((code) => !present.has(code));
      state.batchSelectionOrder = kept.concat(appended);
    }

    function updateBatchPrintCount() {
      const codes = new Set([...state.batchSelectedUnits, ...state.batchSelectedProcesses]);
      $("#batchPrintCount").textContent = `已选 ${codes.size} 个单元`;
      $("#batchPrintSubmitBtn").textContent = `${state.batchPrintMode === "pdf" ? "导出PDF" : "打印"}已选 ${codes.size} 个单元`;
    }

    function renderBatchPrintPicker() {
      const body = $("#batchPrintBody");
      const query = $("#batchPrintSearch").value.trim().toLowerCase();
      state.batchVisibleCodes = [];
      if (!state.projects.length) {
        body.innerHTML = `<div class="unit-image-empty">暂无项目划分数据，请先导入项目划分表。</div>`;
        updateBatchPrintCount();
        return;
      }
      if (query) {
        const results = state.projects.filter((project) => projectPickerText(project).includes(query)).slice(0, 200);
        state.batchVisibleCodes = results.map(projectCode).filter(Boolean);
        body.innerHTML = results.length
          ? `<div class="picker-projects">${results.map(renderBatchProject).join("")}</div>`
          : `<div class="unit-image-empty">没有匹配的单元工程。</div>`;
      } else {
        state.batchVisibleCodes = state.projects.map(projectCode).filter(Boolean);
        body.innerHTML = renderBatchTreeNode(state.treeRoot);
      }
      bindBatchPrintEvents();
      updateBatchPrintCount();
      resizeBatchPrintBody();
    }

    function resizeBatchPrintBody() {
      const body = $("#batchPrintBody");
      if (!body) return;
      body.style.height = "auto";
    }

    function selectVisibleBatchProjects() {
      state.batchVisibleCodes.forEach((code) => {
        state.batchSelectedUnits.add(code);
        state.batchSelectedProcesses.add(code);
      });
      syncBatchSelectionOrder();
      renderBatchPrintPicker();
    }

    function submitBatchPrint() {
      const units = Array.from(state.batchSelectedUnits);
      const processes = Array.from(state.batchSelectedProcesses);
      if (!units.length && !processes.length) {
        showNotice(`请先选择要${state.batchPrintMode === "pdf" ? "导出PDF" : "批量打印"}的单元工程。`, true);
        return;
      }
      syncBatchSelectionOrder();
      const ordered = state.batchSelectionOrder.slice();
      const params = new URLSearchParams();
      if (units.length) params.set("units", units.join(","));
      if (processes.length) params.set("processes", processes.join(","));
      // codes 按真实勾选顺序提交（单元/工序交错也保留），服务端按此顺序出册
      params.set("codes", ordered.join(","));
      params.set("mode", state.batchPrintMode);
      const url = `/print/${encodeURIComponent(state.batchPrintCategory)}/batch?${params.toString()}`;
      closeBatchPrint();
      openPrintSetup(url);
    }

    function renderProjectPicker() {
      const body = $("#projectPickerBody");
      const query = $("#projectPickerSearch").value.trim().toLowerCase();
      if (!state.projects.length) {
        body.innerHTML = `<div class="unit-image-empty">暂无项目划分数据，请先导入项目划分表。</div>`;
        return;
      }
      if (query) {
        const results = state.projects.filter((project) => projectPickerText(project).includes(query)).slice(0, 120);
        body.innerHTML = results.length
          ? `<div class="picker-projects">${results.map(renderPickerProject).join("")}</div>`
          : `<div class="unit-image-empty">没有匹配的单元工程。</div>`;
      } else {
        body.innerHTML = renderPickerTreeNode(state.treeRoot);
      }
      bindPickerTreeEvents(body, selectProjectForUnitImage);
    }

    function selectProjectForUnitImage(code) {
      const unitKey = state.unitImagePickerKey;
      const project = state.projects.find((item) => projectCode(item) === code);
      if (!unitKey || !project) return;
      const unit = state.unitImages[unitKey];
      unit.baseCode = projectCode(project);
      unit.projectName = projectName(project);
      if (!unit.title || unit.title === UNIT_IMAGE_DEFAULTS[unitKey].title) unit.title = unit.projectName;
      renumberUnitImages(unitKey);
      saveUnitImages();
      closeProjectPicker();
      renderUnitImageSection(unitKey);
      showNotice("已选择单元工程。");
    }

    function setUploadChoiceCategory(category) {
      state.uploadChoiceCategory = normalizePhotoCategory(category);
      document.querySelectorAll("[data-upload-choice]").forEach((button) => {
        button.classList.toggle("active", normalizePhotoCategory(button.dataset.uploadChoice) === state.uploadChoiceCategory);
        button.setAttribute("aria-pressed", button.classList.contains("active") ? "true" : "false");
      });
      renderUploadTargetSummary();
    }

    function renderUploadProjectPicker() {
      const body = $("#uploadProjectPickerBody");
      const search = $("#uploadProjectSearch");
      if (!body || !search) return;
      const query = search.value.trim().toLowerCase();
      if (!state.projects.length) {
        body.innerHTML = `<div class="unit-image-empty">暂无项目划分数据，请先导入项目划分表。</div>`;
        return;
      }
      if (query) {
        const results = state.projects.filter((project) => projectPickerText(project).includes(query)).slice(0, 120);
        body.innerHTML = results.length
          ? `<div class="picker-projects">${results.map(renderPickerProject).join("")}</div>`
          : `<div class="unit-image-empty">没有匹配的单元工程。</div>`;
      } else {
        body.innerHTML = renderPickerTreeNode(state.treeRoot);
      }
      bindPickerTreeEvents(body, selectUploadProject);
    }

    function selectUploadProject(code) {
      const project = state.projects.find((item) => projectCode(item) === code);
      if (!project) return;
      state.selectedProject = project;
      state.selectedCode = projectCode(project);
      renderUploadProjectPicker();
      renderUploadProcessOptions();
      renderUploadTargetSummary();
    }

    function syncSelectedProjectFromList() {
      if (!state.selectedCode) return;
      const updated = state.projects.find((item) => projectCode(item) === state.selectedCode);
      if (updated) state.selectedProject = updated;
    }

    function readUnitImageFile(file) {
      return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = () => reject(new Error("照片读取失败"));
        reader.readAsDataURL(file);
      });
    }

    async function handleUnitImageUpload(unitKey, files) {
      if (!files.length) return;
      syncUnitImageForm(unitKey);
      const unit = state.unitImages[unitKey];
      const batchId = `${unitKey}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
      const uploadTime = new Date().toLocaleString("zh-CN", { hour12: false });
      const uploadedBy = state.auth.user?.username || "本机";

      for (const file of Array.from(files)) {
        const src = await readUnitImageFile(file);
        unit.photos.push({
          batchId,
          src,
          name: file.name,
          baseCode: unit.baseCode,
          projectName: unit.projectName || "",
          title: unit.title,
          date: unit.date,
          photographer: unit.photographer,
          description: unit.description,
          uploadTime,
          uploadedBy,
          number: ""
        });
      }

      renumberUnitImages(unitKey);
      saveUnitImages();
      renderUnitImageSection(unitKey);
      $(`#${unitKey}ImageFiles`).value = "";
      showNotice("照片已上传。");
    }

    function openUnitImages() {
      state.selectedPart = null;
      state.activeUnitImageCategory = "";
      setView("unitImages");
      renderTree();
      renderUnitImages();
    }

    function openUnitImageCategory(unitKey) {
      state.selectedPart = null;
      state.activeUnitImageCategory = unitKey;
      setView("unitImages");
      renderTree();
      renderUnitImages();
    }

    function initUnitImages() {
      loadUnitImages();
      ["construction", "supervision"].forEach((unitKey) => {
        ["ImageTitle", "ImageDate", "ImagePhotographer", "ImageDescription"].forEach((suffix) => {
          $(`#${unitKey}${suffix}`).addEventListener("input", () => syncUnitImageForm(unitKey));
        });
        $(`#${unitKey}ImageFiles`).addEventListener("change", (event) => {
          handleUnitImageUpload(unitKey, event.target.files).catch((error) => showNotice(error.message, true));
        });
      });
      document.querySelectorAll("[data-open-project-picker]").forEach((button) => {
        button.addEventListener("click", () => openProjectPicker(button.dataset.openProjectPicker));
      });
      renderUnitImages();
    }

    function showNotice(message, isError = false) {
      const box = document.body.classList.contains("is-authed") ? $("#notice") : $("#gateNotice");
      box.textContent = message;
      box.className = `notice${isError ? " error" : ""}`;
      box.style.display = "block";
      clearTimeout(showNotice.timer);
      showNotice.timer = setTimeout(() => { box.style.display = "none"; }, 4200);
    }

    function showInlineUploadSuccess(selector, message) {
      const box = $(selector);
      if (!box) return;
      box.textContent = message;
      box.style.display = "flex";
    }

    function reportClientError(message, context = {}, stack = "", severity = "error") {
      const payload = {
        source: "desktop_browser",
        message: String(message || "浏览器错误").slice(0, 2000),
        stack: String(stack || "").slice(0, 12000),
        severity,
        page: location.pathname,
        context
      };
      fetch("/api/client-error", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        keepalive: true
      }).catch(() => {});
    }

    window.addEventListener("error", (event) => {
      reportClientError(event.message, {
        filename: String(event.filename || "").split(/[\\/]/).pop(),
        line: event.lineno,
        column: event.colno
      }, event.error?.stack || "", "error");
    });

    window.addEventListener("unhandledrejection", (event) => {
      const reason = event.reason;
      reportClientError(reason?.message || String(reason || "未处理的异步错误"), {
        kind: "unhandledrejection"
      }, reason?.stack || "", "error");
    });

    async function apiJson(url, options) {
      let response;
      try {
        response = await fetch(url, options);
      } catch (error) {
        if (error.name === "AbortError") throw error;
        if (url !== "/api/client-error") {
          reportClientError(error.message || "网络请求失败", { url, method: options?.method || "GET" }, error.stack || "", "warning");
        }
        throw error;
      }
      const text = await response.text();
      let data = {};
      try {
        data = text ? JSON.parse(text) : {};
      } catch (_error) {
        data = {};
      }
      if (!response.ok || data.ok === false) {
        const detail = data.error || data.message || text.trim();
        if (url !== "/api/client-error") {
          reportClientError(detail || `HTTP ${response.status}`, {
            url,
            method: options?.method || "GET",
            status: response.status
          }, "", response.status >= 500 ? "error" : "warning");
        }
        throw new Error(detail || `请求失败（HTTP ${response.status}）`);
      }
      return data;
    }

    async function copyText(text) {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
        return;
      }
      const textarea = document.createElement("textarea");
      textarea.value = text;
      textarea.setAttribute("readonly", "");
      textarea.style.position = "fixed";
      textarea.style.left = "-9999px";
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand("copy");
      textarea.remove();
    }

    async function openMachineIdModal() {
      const data = await apiJson("/api/license/status");
      const license = data.license || {};
      const machineId = license.machine_id || "-";
      $("#machineIdValue").textContent = machineId;
      $("#machineIdStatus").textContent = license.ok
        ? `软件已授权${license.owner ? `：${license.owner}` : ""}${license.expires_at ? `，到期时间：${license.expires_at.slice(0, 10)}` : ""}。`
        : (license.upload_locked ? "一个月试用期已到期，请联系管理员继续使用。" : `试用版：剩余 ${license.trial_remaining || 0} 天。`);
      $("#machineIdModal").classList.add("open");
      $("#machineIdModal").setAttribute("aria-hidden", "false");
    }

    function closeMachineIdModal() {
      $("#machineIdModal").classList.remove("open");
      $("#machineIdModal").setAttribute("aria-hidden", "true");
    }

    async function copyMachineId() {
      const machineId = $("#machineIdValue").textContent.trim();
      if (!machineId || machineId === "-") {
        showNotice("未读取到机器 ID。", true);
        return;
      }
      await copyText(machineId);
      showNotice("机器 ID 已复制。");
    }

    function projectInfoValue(key) {
      return String(state.projectInfo?.[key] || "").trim();
    }

    function projectInfoContractName() {
      return projectInfoValue("project_name");
    }

    function isMissingContractName(name) {
      const value = String(name || "").trim();
      return !value || value === "未填写合同工程";
    }

    function displayContractName(name) {
      return isMissingContractName(name) ? (projectInfoContractName() || "未填写合同工程") : String(name || "").trim();
    }

    function displayTreeNodeName(node) {
      if (!node) return "";
      return node.type === "contract" ? displayContractName(node.name) : String(node.name || "").trim();
    }

    function engineeringProjectLabel(project) {
      if (!project) return "";
      // 顶部只显示用户填写的工程名称。project-xxxx 是内部隔离 ID，
      // 对用户没有意义，也不应该因为工程编号留空就出现在界面上。
      return project.project_name || projectInfoContractName() || "未命名工程";
    }

    function engineeringProjectDisplayCode(project) {
      const code = String(project?.project_code || "").trim();
      const id = String(project?.id || "").trim();
      return code && !(code === id && /^project-[a-f0-9]{12}$/i.test(code)) ? code : "";
    }

    function currentEngineeringProject() {
      return state.engineeringProjects.find((item) => item.id === state.activeEngineeringProjectId) || state.engineeringProjects[0] || null;
    }

    function renderEngineeringProjectSelect() {
      const select = $("#engineeringProjectSelect");
      if (!select) return;
      select.innerHTML = state.engineeringProjects.map((project) => `
        <option value="${escapeHtml(project.id || "")}" ${project.id === state.activeEngineeringProjectId ? "selected" : ""}>${escapeHtml(engineeringProjectLabel(project))}</option>
      `).join("");
      const active = currentEngineeringProject();
      const label = engineeringProjectLabel(active);
      select.title = label ? `当前工程：${label}。展开可查看全部工程。` : "展开查看并切换工程";
    }

    async function setActiveEngineeringProject(projectId) {
      const data = await apiJson("/api/engineering-projects/active", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: projectId })
      });
      state.projectInfo = data.project_info || {};
      state.engineeringProjects = data.engineering_projects || [];
      state.activeEngineeringProjectId = data.active_engineering_project_id || projectId;
      state.selectedProject = null;
      state.selectedCode = "";
      state.selectedOtherCode = "";
      setRouteUnitCode("");
      openOverview("construction");
      renderEngineeringProjectSelect();
      renderProjectInfo();
      await refreshAll();
      showNotice("当前工程已切换。");
    }

    function renderProjectInfo() {
      renderEngineeringProjectSelect();
      const current = currentEngineeringProject();
      if (current) {
        $("#overviewCrumbs").textContent = `当前工程：${engineeringProjectLabel(current)}`;
      }
    }

    function openNewEngineeringProjectModal() {
      const form = $("#newEngineeringProjectForm");
      form?.reset();
      const industry = $("#newEngineeringProjectIndustryInput");
      if (industry) industry.value = "水利工程";
      $("#newEngineeringProjectModal").classList.add("open");
      $("#newEngineeringProjectModal").setAttribute("aria-hidden", "false");
      setTimeout(() => $("#newEngineeringProjectNameInput")?.focus(), 0);
    }

    function closeNewEngineeringProjectModal() {
      $("#newEngineeringProjectModal").classList.remove("open");
      $("#newEngineeringProjectModal").setAttribute("aria-hidden", "true");
      $("#newEngineeringProjectForm")?.reset();
    }

    async function createEngineeringProject(event) {
      event.preventDefault();
      if (!(await ensureAuthenticated("新建工程"))) return;
      const password = $("#newEngineeringProjectDeletePasswordInput").value;
      const confirmPassword = $("#newEngineeringProjectDeletePasswordConfirmInput").value;
      if (password !== confirmPassword) {
        showNotice("两次输入的工程删除密码不一致。", true);
        return;
      }
      const submitButton = $("#submitNewEngineeringProjectBtn");
      if (submitButton) submitButton.disabled = true;
      try {
        const data = await apiJson("/api/engineering-projects", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            project_name: $("#newEngineeringProjectNameInput").value.trim(),
            project_code: $("#newEngineeringProjectCodeInput").value.trim(),
            industry: $("#newEngineeringProjectIndustryInput").value,
            project_type: $("#newEngineeringProjectTypeInput").value.trim(),
            region: $("#newEngineeringProjectRegionInput").value.trim(),
            delete_password: password
          })
        });
        state.projectInfo = data.project_info || {};
        state.engineeringProjects = data.engineering_projects || state.engineeringProjects;
        state.activeEngineeringProjectId = data.active_engineering_project_id || "";
        state.selectedProject = null;
        state.selectedCode = "";
        state.selectedOtherCode = "";
        closeNewEngineeringProjectModal();
        renderProjectInfo();
        await refreshAll();
        showNotice("新工程已创建，当前资料与专业规则均为独立空白。请先导入项目划分。");
      } finally {
        if (submitButton && submitButton.isConnected) submitButton.disabled = false;
      }
    }

    const NUMBER_TEMPLATE_LABELS = [
      ["{unit_code}", "【单元编号】"],
      ["{unit_order}", "【单元顺序号】"],
      ["{seq}", "【流水号】"],
      ["{category}", "【类别】"],
      ["{code}", "【单元编号】"],
      ["{process_code}", "【工序编码】"]
    ];

    function numberTemplateToReadable(template) {
      let value = String(template || "");
      NUMBER_TEMPLATE_LABELS.forEach(([token, label]) => {
        value = value.split(token).join(label);
      });
      return value;
    }

    // 显示用：把等价的 {unit_code} 统一成 {code} 再转中文占位符，
    // 避免界面上出现 "…-SY【流水号】" 这种半截英文的写法。
    function numberTemplateToReadableDisplay(template) {
      return numberTemplateToReadable(String(template || "").split("{unit_code}").join("{code}"));
    }

    // 工序格式留空时，自动把单元格式的 {seq} 位置插入工序编码，
    // 保证工序照片编号里一定带工序，不会和单元照片撞号。
    function processTemplateFromUnit(unitTemplate, category) {
      const template = String(unitTemplate || "").trim();
      const fallback = category === "supervision"
        ? "{unit_code}-{process_code}-JY{seq}"
        : "{unit_code}-{process_code}-SY{seq}";
      if (!template) return fallback;
      if (!template.includes("{seq}")) return `${template}{process_code}{seq}`;
      return template.replace("{seq}", "{process_code}{seq}");
    }

    function readableToNumberTemplate(template) {
      let value = String(template || "").trim();
      NUMBER_TEMPLATE_LABELS.forEach(([token, label]) => {
        const normalizedToken = token === "{code}" ? "{unit_code}" : token;
        value = value.split(label).join(normalizedToken);
      });
      return value;
    }

    function mountUnifiedSettings() {
      const host = $("#settingsAccountHost");
      const panel = $("#supportPanel");
      if (!host || !panel) return;
      if (panel.parentElement !== host) host.appendChild(panel);
      panel.classList.add("is-settings-embedded", "open");
      panel.setAttribute("aria-hidden", "false");
    }

    function setProjectSettingsTab(tab) {
      const nextTab = tab || "info";
      document.querySelectorAll("[data-project-settings-tab]").forEach((button) => {
        button.classList.toggle("active", button.dataset.projectSettingsTab === nextTab);
      });
      document.querySelectorAll("[data-project-settings-panel]").forEach((panel) => {
        panel.classList.toggle(
          "active",
          panel.dataset.projectSettingsPanel === nextTab || panel.dataset.projectSettingsGroup === nextTab
        );
      });
      const membersMode = nextTab === "members";
      const form = $("#projectInfoForm");
      if (form) {
        form.classList.toggle("members-mode", membersMode);
        form.dataset.activeTab = nextTab;
      }
      const cancelButton = $("#cancelProjectInfoBtn");
      const utilityMode = ["division", "members", "account", "device"].includes(nextTab);
      if (cancelButton) cancelButton.textContent = utilityMode ? "关闭" : "取消";
      if (membersMode && !state.projectMembersLoading && state.projectMembersProjectId !== state.activeEngineeringProjectId) {
        loadProjectMembers().catch(() => {});
      }
      if (nextTab === "account") {
        mountUnifiedSettings();
        setSupportTab("status");
        loadProductConfig().catch(() => {});
        loadSharePoints().catch((error) => showNotice(error.message, true));
      }
    }

    const PROJECT_MEMBER_ROLES = ["admin", "capturer", "viewer"];

    function projectMemberRoleLabel(role) {
      return ({ owner: "负责人", admin: "管理员", capturer: "采集员", viewer: "只读" })[String(role || "")] || "成员";
    }

    function projectMemberAccountId(member) {
      return String(member?.member_account_id ?? member?.account_id ?? member?.id ?? "").trim();
    }

    function projectInviteId(invite) {
      return String(invite?.invite_id ?? invite?.id ?? "").trim();
    }

    function projectMemberDisplayName(member) {
      return String(member?.display_name || member?.username || member?.account || `账号 ${projectMemberAccountId(member)}`).trim();
    }

    function compactDateTime(value) {
      return String(value || "").slice(0, 16).replace("T", " ");
    }

    function renderProjectInvites() {
      const section = $("#projectInvitesSection");
      const list = $("#projectInvitesList");
      if (!section || !list) return;
      const invites = (state.projectInvites || []).filter((invite) => {
        const status = String(invite?.status || "active");
        return !["used", "revoked", "expired"].includes(status);
      });
      section.hidden = invites.length === 0;
      list.innerHTML = invites.map((invite) => {
        const inviteId = projectInviteId(invite);
        const expiresAt = compactDateTime(invite.expires_at);
        const createdAt = compactDateTime(invite.created_at);
        return `<div class="project-invite-row">
          <div class="project-invite-main">
            <span class="project-member-name">${escapeHtml(projectMemberRoleLabel(invite.role))}邀请码</span>
            <span class="project-invite-meta">${escapeHtml(expiresAt ? `有效至 ${expiresAt}` : createdAt ? `创建于 ${createdAt}` : "等待成员使用")}</span>
          </div>
          <button class="project-invite-revoke" type="button" data-project-invite-revoke="${escapeHtml(inviteId)}">撤销</button>
        </div>`;
      }).join("");
    }

    function renderProjectMembers() {
      const list = $("#projectMembersList");
      const count = $("#projectMemberCount");
      const summary = $("#projectMembersSummary");
      const createButton = $("#createProjectInviteBtn");
      const refreshButton = $("#refreshProjectMembersBtn");
      if (!list || !count || !summary) return;
      const members = Array.isArray(state.projectMembers) ? state.projectMembers : [];
      count.textContent = `${members.length} 人`;
      if (state.projectMembersLoading) {
        summary.textContent = "正在读取成员…";
        list.innerHTML = `<div class="empty">正在读取成员…</div>`;
      } else if (state.projectMembersError) {
        summary.textContent = state.projectMembersError;
        list.innerHTML = `<div class="empty">${escapeHtml(state.projectMembersError)}</div>`;
      } else {
        summary.textContent = members.length > 1 ? "成员照片统一归档到这台电脑" : "本机为项目归档电脑";
        list.innerHTML = members.length ? members.map((member) => {
          const accountId = projectMemberAccountId(member);
          const role = String(member.role || member.membership_role || "viewer");
          const isOwner = role === "owner" || Boolean(member.is_owner);
          const displayName = projectMemberDisplayName(member);
          const username = String(member.username || member.account || "").trim();
          const joinedAt = compactDateTime(member.joined_at || member.created_at);
          const meta = [username && username !== displayName ? username : "", joinedAt ? `加入 ${joinedAt}` : ""].filter(Boolean).join(" · ");
          const roleControl = isOwner
            ? `<span class="project-member-role-badge">负责人</span>`
            : `<select class="project-member-role-select" data-project-member-role="${escapeHtml(accountId)}" aria-label="调整 ${escapeHtml(displayName)} 的角色">
                ${PROJECT_MEMBER_ROLES.map((value) => `<option value="${value}" ${value === role ? "selected" : ""}>${projectMemberRoleLabel(value)}</option>`).join("")}
              </select>
              <button class="project-member-remove" type="button" data-project-member-remove="${escapeHtml(accountId)}" data-project-member-name="${escapeHtml(displayName)}">移除</button>`;
          return `<div class="project-member-row">
            <span class="project-member-avatar" aria-hidden="true">${escapeHtml(displayName.slice(0, 1) || "人")}</span>
            <div class="project-member-main">
              <span class="project-member-name">${escapeHtml(displayName)}</span>
              <span class="project-member-meta">${escapeHtml(meta || projectMemberRoleLabel(role))}</span>
            </div>
            ${roleControl}
          </div>`;
        }).join("") : `<div class="empty">暂无成员</div>`;
      }
      if (createButton) createButton.disabled = state.projectMembersLoading || Boolean(state.projectMembersError);
      if (refreshButton) refreshButton.disabled = state.projectMembersLoading;
      renderProjectInvites();
    }

    async function loadProjectMembers() {
      const projectId = String(state.activeEngineeringProjectId || "");
      if (state.projectMembersProjectId !== projectId) {
        state.latestProjectInvite = null;
        state.projectMembers = [];
        state.projectInvites = [];
        const latestInvite = $("#projectInviteResult");
        if (latestInvite) latestInvite.hidden = true;
      }
      state.projectMembersProjectId = projectId;
      state.projectMembersLoading = true;
      state.projectMembersError = "";
      renderProjectMembers();
      const [membersResult, invitesResult] = await Promise.allSettled([
        apiJson("/api/cloud/project-members"),
        apiJson("/api/cloud/project-invites")
      ]);
      if (membersResult.status === "fulfilled") {
        const data = membersResult.value || {};
        state.projectMembers = Array.isArray(data.members) ? data.members : [];
        state.projectMembership = data.membership || data.project?.membership || {};
      } else {
        state.projectMembers = [];
        state.projectMembership = {};
        state.projectMembersError = membersResult.reason?.message || "成员读取失败";
      }
      if (invitesResult.status === "fulfilled") {
        state.projectInvites = Array.isArray(invitesResult.value?.invites) ? invitesResult.value.invites : [];
      } else if (!state.projectMembersError) {
        state.projectMembersError = invitesResult.reason?.message || "邀请状态读取失败";
      }
      state.projectMembersLoading = false;
      renderProjectMembers();
    }

    async function createProjectInvite() {
      const role = $("#projectInviteRoleInput")?.value || "capturer";
      const button = $("#createProjectInviteBtn");
      if (button) button.disabled = true;
      try {
        const data = await apiJson("/api/cloud/project-invites", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ role })
        });
        const invite = data.invite || data;
        const code = String(invite.code || invite.invite_code || "").trim();
        if (!code) throw new Error("服务器没有返回邀请码，请重试");
        state.latestProjectInvite = { ...invite, code };
        const result = $("#projectInviteResult");
        if (result) result.hidden = false;
        $("#projectInviteCode").textContent = code;
        const expiry = compactDateTime(invite.expires_at);
        $("#projectInviteMeta").textContent = `${projectMemberRoleLabel(invite.role || role)}${expiry ? ` · 有效至 ${expiry}` : ""}`;
        await loadProjectMembers();
        showNotice("邀请码已生成，可以发给成员。 ");
      } finally {
        if (button) button.disabled = false;
      }
    }

    async function updateProjectMemberRole(accountId, role, select) {
      if (!PROJECT_MEMBER_ROLES.includes(role)) return;
      if (select) select.disabled = true;
      try {
        await apiJson(`/api/cloud/project-members/${encodeURIComponent(accountId)}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ role })
        });
        await loadProjectMembers();
        showNotice("成员角色已更新。 ");
      } catch (error) {
        await loadProjectMembers().catch(() => {});
        throw error;
      } finally {
        if (select && select.isConnected) select.disabled = false;
      }
    }

    async function removeProjectMember(accountId, displayName, button) {
      if (!window.confirm(`确认移除成员“${displayName || accountId}”？历史照片仍会保留。`)) return;
      if (button) button.disabled = true;
      try {
        await apiJson(`/api/cloud/project-members/${encodeURIComponent(accountId)}`, { method: "DELETE" });
        await loadProjectMembers();
        showNotice("成员已移除，历史照片保持不变。 ");
      } finally {
        if (button && button.isConnected) button.disabled = false;
      }
    }

    async function revokeProjectInvite(inviteId, button) {
      if (!window.confirm("确认撤销这个邀请码？")) return;
      if (button) button.disabled = true;
      try {
        await apiJson(`/api/cloud/project-invites/${encodeURIComponent(inviteId)}`, { method: "DELETE" });
        if (projectInviteId(state.latestProjectInvite) === String(inviteId)) {
          state.latestProjectInvite = null;
          $("#projectInviteResult").hidden = true;
        }
        await loadProjectMembers();
        showNotice("邀请码已撤销。 ");
      } finally {
        if (button && button.isConnected) button.disabled = false;
      }
    }

    function syncPrintPhotoPresetInputs() {
      const preset = $("#settingsPrintPhotoPresetInput").value;
      const sizes = {
        "4inch": [10.2, 7.6],
        "5inch": [12.7, 8.9],
        "6inch": [15.2, 10.2]
      };
      const custom = preset === "custom";
      $("#settingsPrintPhotoWidthInput").disabled = !custom;
      $("#settingsPrintPhotoHeightInput").disabled = !custom;
      if (sizes[preset]) {
        $("#settingsPrintPhotoWidthInput").value = sizes[preset][0];
        $("#settingsPrintPhotoHeightInput").value = sizes[preset][1];
      }
    }

    function formatStorageBytes(value) {
      const bytes = Math.max(0, Number(value || 0));
      if (bytes < 1024) return `${bytes} B`;
      if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
      return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
    }

    function renderPhotoOptimizationStatus() {
      const status = state.optimizationStatus || {};
      const total = Number(status.total || 0);
      const completed = Number(status.completed || 0);
      const stateLabel = status.paused ? "已暂停" : status.state === "running" ? "正在后台优化" : status.state === "complete" ? "已完成" : "等待开始";
      const percent = total ? Math.min(100, Math.round(completed * 100 / total)) : 100;
      const node = $("#photoOptimizationStatus");
      if (!node) return;
      node.innerHTML = `<strong>${stateLabel}</strong><span>${completed} / ${total} 张（${percent}%）</span><span>已节省 ${formatStorageBytes(status.saved_bytes)}，失败 ${Number(status.failed || 0)} 张</span>${status.current ? `<small>正在处理：${escapeHtml(status.current)}</small>` : ""}`;
    }

    async function refreshPhotoOptimizationStatus() {
      const data = await apiJson("/api/photo-optimization/status");
      state.optimizationStatus = data.status || {};
      renderPhotoOptimizationStatus();
      if ($("#projectInfoModal").classList.contains("open") && state.optimizationStatus.state === "running" && !state.optimizationStatus.paused) {
        setTimeout(() => refreshPhotoOptimizationStatus().catch(() => {}), 1000);
      }
    }

    async function controlPhotoOptimization(action) {
      const data = await apiJson(`/api/photo-optimization/${action}`, { method: "POST" });
      state.optimizationStatus = data.status || {};
      renderPhotoOptimizationStatus();
      if (action === "start") setTimeout(() => refreshPhotoOptimizationStatus().catch(() => {}), 500);
    }

    async function refreshProfessionalProjectTypes(preferredType = "") {
      const industryInput = $("#projectInfoIndustryInput");
      const typeInput = $("#projectInfoProjectTypeInput");
      if (!industryInput || !typeInput) return;
      try {
        const data = await apiJson("/api/professional-templates/catalog");
        const currentIndustry = industryInput.value || "水利工程";
        const group = (data.industries || []).find((item) => item.name === currentIndustry);
        const types = group?.project_types || [];
        typeInput.innerHTML = types.length
          ? types.map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`).join("")
          : `<option value="">通用/沿用项目划分</option>`;
        const wanted = preferredType || projectInfoValue("project_type");
        if (wanted && types.includes(wanted)) typeInput.value = wanted;
        else if (types.length) typeInput.value = types[0];
        await refreshProfessionalPlanSummary();
      } catch (error) {
        const fallback = preferredType || projectInfoValue("project_type") || "通用/沿用项目划分";
        typeInput.innerHTML = `<option value="${escapeHtml(fallback)}">${escapeHtml(fallback)}</option>`;
      }
    }

    async function refreshProfessionalPlanSummary() {
      const node = $("#professionalPlanSummary");
      const industry = $("#projectInfoIndustryInput")?.value || "水利工程";
      const projectType = $("#projectInfoProjectTypeInput")?.value || "";
      if (!node) return;
      if (industry === "水利工程") {
        node.innerHTML = `<strong>水利工程 · 沿用现有项目划分</strong><p class="import-hint">水利模块继续使用你现有的单位工程—分部工程—单元工程体系，不改变既有照片和编码。</p>`;
        return;
      }
      try {
        const data = await apiJson(`/api/professional-templates/requirements?industry=${encodeURIComponent(industry)}&project_type=${encodeURIComponent(projectType)}`);
        const summary = data.summary || {};
        node.innerHTML = `<strong>${escapeHtml(industry)} · ${escapeHtml(projectType || "通用")}</strong><p class="import-hint">模板 ${escapeHtml(summary.template_version || "V1.0")}：共 ${Number(summary.total || 0)} 项；必拍 ${Number(summary.required || 0)} 项，条件必拍 ${Number(summary.conditional || 0)} 项，推荐 ${Number(summary.recommended || 0)} 项。保存后自动同步到云端和小程序。</p>`;
      } catch (error) {
        node.innerHTML = `<strong>专业影像采集模板</strong><p class="import-hint">模板暂时无法读取，保存工程不受影响；联网后会自动同步。</p>`;
      }
    }

    function openProjectInfoModal() {
      mountUnifiedSettings();
      const settings = state.engineeringSettings || {};
      const rules = settings.numbering_rules || {};
      const construction = rules.construction || {};
      const supervision = rules.supervision || {};
      $("#projectInfoNameInput").value = projectInfoValue("project_name");
      $("#projectInfoCodeInput").value = engineeringProjectDisplayCode(currentEngineeringProject());
      $("#projectInfoIndustryInput").value = projectInfoValue("industry") || "水利工程";
      $("#projectInfoRegionInput").value = projectInfoValue("region");
      refreshProfessionalProjectTypes(projectInfoValue("project_type")).catch(() => {});
      $("#projectInfoOwnerInput").value = projectInfoValue("owner");
      $("#projectInfoContractorInput").value = projectInfoValue("contractor");
      $("#projectInfoSupervisorInput").value = projectInfoValue("supervisor");
      $("#projectInfoLocationInput").value = projectInfoValue("location");
      $("#projectInfoStartDateInput").value = projectInfoValue("start_date");
      const deletePasswordInput = $("#projectInfoDeletePasswordInput");
      deletePasswordInput.value = "";
      deletePasswordInput.required = !Boolean(state.projectInfo?.delete_password_set);
      deletePasswordInput.placeholder = state.projectInfo?.delete_password_set
        ? "已设置；留空表示不修改"
        : "尚未设置，保存工程前必须填写";
      $("#projectInfoDescriptionInput").value = projectInfoValue("description");
      $("#settingsNumberingModeInput").value = settings.numbering_mode || "custom";
      $("#settingsUnitOrderDigitsInput").value = settings.unit_order_digits || 3;
      const constructionUnitReadable = construction.unit_template || construction.template || "{unit_code}-SY{seq}";
      const supervisionUnitReadable = supervision.unit_template || supervision.template || "{unit_code}-JY{seq}";
      $("#settingsConstructionUnitTemplate").value = numberTemplateToReadableDisplay(constructionUnitReadable);
      $("#settingsConstructionStart").value = construction.start || 1;
      $("#settingsConstructionDigits").value = construction.digits || 3;
      $("#settingsSupervisionUnitTemplate").value = numberTemplateToReadableDisplay(supervisionUnitReadable);
      $("#settingsSupervisionStart").value = supervision.start || 1;
      $("#settingsSupervisionDigits").value = supervision.digits || 3;
      // 工序格式：优先用工程已保存的值；没存过就按单元格式自动推导，界面上看得见、可改。
      if ($("#settingsConstructionProcessTemplate")) {
        $("#settingsConstructionProcessTemplate").value = numberTemplateToReadableDisplay(
          construction.process_template || processTemplateFromUnit(constructionUnitReadable, "construction")
        );
      }
      if ($("#settingsSupervisionProcessTemplate")) {
        $("#settingsSupervisionProcessTemplate").value = numberTemplateToReadableDisplay(
          supervision.process_template || processTemplateFromUnit(supervisionUnitReadable, "supervision")
        );
      }
      $("#settingsPrintLayoutInput").value = settings.print_layout || "landscape";
      $("#settingsPrintPageSizeInput").value = String(settings.print_page_size || 4);
      $("#settingsPrintSingleAlignmentInput").value = settings.print_single_alignment || "center";
      $("#settingsPrintPhotoPresetInput").value = settings.print_photo_preset || "5inch";
      $("#settingsPrintPhotoWidthInput").value = settings.print_photo_width_cm || "";
      $("#settingsPrintPhotoHeightInput").value = settings.print_photo_height_cm || "";
      $("#settingsPrintCaptionFontSizeInput").value = settings.print_caption_font_size || 10;
      $("#settingsPrintCaptionPositionInput").value = settings.print_caption_position || "left";
      syncPrintPhotoPresetInputs();
      $("#settingsPhotoFieldsInput").value = (settings.photo_detail_fields || []).map((field) => `${field.label || ""}=${field.source === "custom" ? (field.value || "") : (field.source || "")}`).join("\n");
      setProjectSettingsTab("info");
      $("#projectInfoModal").classList.add("open");
      $("#projectInfoModal").setAttribute("aria-hidden", "false");
      renderPhotoOptimizationStatus();
      refreshPhotoOptimizationStatus().catch(() => {});
      loadProjectMembers().catch(() => {});
      setTimeout(() => $("#projectInfoNameInput").focus(), 0);
    }

    function closeProjectInfoModal() {
      $("#projectInfoModal").classList.remove("open");
      $("#projectInfoModal").setAttribute("aria-hidden", "true");
      $("#projectInfoForm").reset();
    }

    async function openNumberingRulesModal() {
      const data = await apiJson("/api/numbering-rules");
      const rules = data.rules || {};
      const construction = rules.construction || {};
      const supervision = rules.supervision || {};
      $("#constructionNumberTemplate").value = numberTemplateToReadable(construction.template || "{code}-SY{seq}");
      $("#constructionNumberStart").value = construction.start || 1;
      $("#constructionNumberDigits").value = construction.digits || 3;
      $("#supervisionNumberTemplate").value = numberTemplateToReadable(supervision.template || "{code}-JY{seq}");
      $("#supervisionNumberStart").value = supervision.start || 1;
      $("#supervisionNumberDigits").value = supervision.digits || 3;
      $("#numberingRulesModal").classList.add("open");
      $("#numberingRulesModal").setAttribute("aria-hidden", "false");
      setTimeout(() => $("#constructionNumberTemplate").focus(), 0);
    }

    function closeNumberingRulesModal() {
      $("#numberingRulesModal").classList.remove("open");
      $("#numberingRulesModal").setAttribute("aria-hidden", "true");
      $("#numberingRulesForm").reset();
    }

    async function saveNumberingRules(event) {
      event.preventDefault();
      // 设置里只有"一个"模板输入框，但编号实际分单元/工序两套模板。
      // 只提交 template 会让 process_template 永远停留在默认值（旧值里的
      // SY/JY 前缀会一直出现，客户以为改的设置没生效）。这里三个字段一起提交：
      // 工序模板 = 用户模板把 {seq} 换成 {process_code}{seq}，保证工序照片也
      // 沿用用户选定的编码与样式。
      const processTemplateFrom = (template) => {
        if (template.includes("{seq}")) {
          return template.replace("{seq}", "{process_code}{seq}");
        }
        return template + "{process_code}{seq}";
      };
      const buildRule = (template, start, digits) => ({
        template,
        unit_template: template,
        process_template: processTemplateFrom(template),
        start,
        digits
      });
      const rules = {
        construction: buildRule(
          readableToNumberTemplate($("#constructionNumberTemplate").value),
          Number($("#constructionNumberStart").value || 1),
          Number($("#constructionNumberDigits").value || 3)
        ),
        supervision: buildRule(
          readableToNumberTemplate($("#supervisionNumberTemplate").value),
          Number($("#supervisionNumberStart").value || 1),
          Number($("#supervisionNumberDigits").value || 3)
        )
      };
      await apiJson("/api/numbering-rules", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rules })
      });
      closeNumberingRulesModal();
      showNotice("照片编号规则已保存。新上传照片将按新规则编号。");
    }

    async function saveProjectInfo(event) {
      event.preventDefault();
      if (!(await ensureAuthenticated("保存工程信息"))) return;
      const payload = {
        id: currentEngineeringProject()?.id || state.activeEngineeringProjectId || "",
        project_name: $("#projectInfoNameInput").value.trim(),
        project_code: $("#projectInfoCodeInput").value.trim(),
        industry: $("#projectInfoIndustryInput").value,
        project_type: $("#projectInfoProjectTypeInput").value,
        region: $("#projectInfoRegionInput").value.trim(),
        template_version: "V1.0",
        owner: $("#projectInfoOwnerInput").value.trim(),
        contractor: $("#projectInfoContractorInput").value.trim(),
        supervisor: $("#projectInfoSupervisorInput").value.trim(),
        location: $("#projectInfoLocationInput").value.trim(),
        start_date: $("#projectInfoStartDateInput").value,
        delete_password: $("#projectInfoDeletePasswordInput").value.trim(),
        description: $("#projectInfoDescriptionInput").value.trim()
      };
      const photoFields = $("#settingsPhotoFieldsInput").value.split(/\r?\n/).map((line) => {
        const [label, ...rest] = line.split("=");
        const value = rest.join("=").trim();
        const source = ["id", "title", "project_name", "photo_date", "photographer", "description"].includes(value) ? value : "custom";
        return { label: (label || "").trim(), source, value: source === "custom" ? value : "" };
      }).filter((field) => field.label);
      const constructionUnitTemplate = readableToNumberTemplate($("#settingsConstructionUnitTemplate").value);
      const supervisionUnitTemplate = readableToNumberTemplate($("#settingsSupervisionUnitTemplate").value);
      const constructionProcessInput = $("#settingsConstructionProcessTemplate");
      const supervisionProcessInput = $("#settingsSupervisionProcessTemplate");
      const constructionProcessTemplate = readableToNumberTemplate(
        (constructionProcessInput && constructionProcessInput.value) || ""
      ) || processTemplateFromUnit(constructionUnitTemplate, "construction");
      const supervisionProcessTemplate = readableToNumberTemplate(
        (supervisionProcessInput && supervisionProcessInput.value) || ""
      ) || processTemplateFromUnit(supervisionUnitTemplate, "supervision");
      const settingsPayload = {
        numbering_mode: $("#settingsNumberingModeInput").value,
        process_prefix: "",
        process_digits: 3,
        unit_order_digits: Number($("#settingsUnitOrderDigitsInput").value || 3),
        print_layout: $("#settingsPrintLayoutInput").value,
        print_page_size: Number($("#settingsPrintPageSizeInput").value || 4),
        print_single_alignment: $("#settingsPrintSingleAlignmentInput").value,
        print_photo_preset: $("#settingsPrintPhotoPresetInput").value,
        print_photo_width_cm: Number($("#settingsPrintPhotoWidthInput").value || 0),
        print_photo_height_cm: Number($("#settingsPrintPhotoHeightInput").value || 0),
        print_caption_font_size: Number($("#settingsPrintCaptionFontSizeInput").value || 10),
        print_caption_position: $("#settingsPrintCaptionPositionInput").value,
        watermark_ocr_enabled: true,
        photo_detail_fields: photoFields,
        numbering_rules: {
          construction: {
            template: constructionUnitTemplate,
            unit_template: constructionUnitTemplate,
            process_template: constructionProcessTemplate,
            start: Number($("#settingsConstructionStart").value || 1),
            digits: Number($("#settingsConstructionDigits").value || 3)
          },
          supervision: {
            template: supervisionUnitTemplate,
            unit_template: supervisionUnitTemplate,
            process_template: supervisionProcessTemplate,
            start: Number($("#settingsSupervisionStart").value || 1),
            digits: Number($("#settingsSupervisionDigits").value || 3)
          }
        }
      };
      const data = await apiJson("/api/project-info", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      state.projectInfo = data.project_info || {};
      state.engineeringProjects = data.engineering_projects || state.engineeringProjects;
      state.activeEngineeringProjectId = data.active_engineering_project_id || state.activeEngineeringProjectId;
      const settingsData = await apiJson("/api/engineering-settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ settings: settingsPayload })
      });
      state.engineeringSettings = settingsData.settings || state.engineeringSettings;
      renderProjectInfo();
      await refreshAll();
      renderTree();
      renderOverview();
      closeProjectInfoModal();
      const renumberedPhotos = Number(settingsData.renumbered?.photos || 0);
      showNotice(renumberedPhotos > 0
        ? `工程设置已保存，已有 ${renumberedPhotos} 张照片按新规则重新编号。`
        : "工程设置已保存，当前照片编号已按新规则检查。");
    }

    async function deleteCurrentEngineeringProject() {
      const current = currentEngineeringProject();
      if (!current) return;
      if (!(await ensureAuthenticated("删除本工程"))) return;
      if (!confirm(`确认删除工程“${current.project_name || current.id}”？该工程下的项目划分和照片会移动到备份目录。`)) return;
      const deletePassword = prompt("请输入本工程删除密码");
      if (!deletePassword) {
        showNotice("请输入本工程删除密码。", true);
        return;
      }
      const data = await apiJson(`/api/engineering-projects/${encodeURIComponent(current.id)}`, {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ delete_password: deletePassword })
      });
      state.projectInfo = data.project_info || {};
      state.engineeringProjects = data.engineering_projects || [];
      state.activeEngineeringProjectId = data.active_engineering_project_id || "";
      state.selectedProject = null;
      state.selectedCode = "";
      closeProjectInfoModal();
      await refreshAll();
      const cloudMessage = data.cloud_unbind?.ok === false ? "；小程序项目名额将在联网解除绑定后释放" : "；小程序项目名额已释放";
      showNotice(`工程已删除，${data.deleted || 0} 个单元已移入备份${cloudMessage}。`);
    }

    async function importEngineeringPackage(file) {
      if (!(await ensureAuthenticated("导入工程资料包"))) return;
      if (!file) {
        showNotice("请选择要导入的工程资料包。", true);
        return;
      }
      const form = new FormData();
      form.append("file", file);
      const data = await apiJson("/api/engineering-package/import", { method: "POST", body: form });
      await refreshAll();
      $("#packageFile").value = "";
      $("#packageFileLabel").textContent = "导入资料包";
      const result = data.result || {};
      showNotice(`${data.message || "资料包导入完成"}：${result.imported_projects || 0} 个单元，${result.imported_photos || 0} 张照片。`);
    }

    function renderAuth() {
      const user = state.auth.user;
      document.body.classList.toggle("is-authed", Boolean(user));
      document.body.classList.toggle("is-project-staff", user?.role === "project_staff");
      $("#authStatus").textContent = user ? `当前：${user.username}` : "未填写姓名";
      $("#logoutBtn").style.display = user ? "" : "none";
    }

    async function loadAuth() {
      const data = await apiJson("/api/auth/me");
      state.auth.user = data.user || null;
      renderAuth();
    }

    function formatUpdateBytes(value) {
      const bytes = Math.max(0, Number(value || 0));
      if (bytes < 1024) return `${Math.round(bytes)} B`;
      if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(bytes < 10240 ? 1 : 0)} KB`;
      return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
    }

    function setUpdateAvailable(hasUpdate) {
      const button = $("#checkUpdateBtn");
      const dot = $("#updateNoticeDot");
      const versionBadge = $("#appVersionBadge");
      if (dot) dot.hidden = !hasUpdate;
      button?.classList.toggle("update-available", Boolean(hasUpdate));
      versionBadge?.classList.toggle("update-available", Boolean(hasUpdate));
      button?.setAttribute("title", hasUpdate ? "发现新版本，点击下载安装包" : "检查软件新版本");
      versionBadge?.setAttribute("title", hasUpdate ? "发现新版本，请尽快更新" : "当前软件版本");
    }

    function openUpdateOverlay(mode = "mandatory") {
      const overlay = $("#updateOverlay");
      if (!overlay) return;
      const wasOpen = overlay.classList.contains("open");
      overlay.classList.add("open");
      overlay.dataset.mode = mode;
      overlay.setAttribute("aria-hidden", "false");
      document.body.classList.toggle("update-required", mode === "mandatory");
      Array.from(document.body.children).forEach((node) => {
        if (node !== overlay && node.tagName !== "SCRIPT") node.inert = true;
      });
      if (!wasOpen) overlay.querySelector(".update-panel")?.focus({ preventScroll: true });
    }

    function closeManualUpdate() {
      const overlay = $("#updateOverlay");
      if (!overlay || overlay.dataset.mode !== "manual") return;
      overlay.classList.remove("open");
      overlay.setAttribute("aria-hidden", "true");
      document.body.classList.remove("update-required");
      Array.from(document.body.children).forEach((node) => {
        if (node !== overlay && node.tagName !== "SCRIPT") node.inert = false;
      });
    }

    function renderManualUpdate(manifest) {
      state.update.manifest = manifest;
      openUpdateOverlay("manual");
      const overlay = $("#updateOverlay");
      overlay.dataset.state = "available";
      $("#updateRequiredLabel").textContent = "重要更新";
      $("#updateTitle").textContent = "发现新版本，建议立即更新";
      $("#updateVersion").textContent = `${manifest.current_version || $("#appVersionBadge")?.textContent || "当前版本"} → ${manifest.latest_version}`;
      $("#updateMessage").textContent = "请下载安装包，关闭软件后双击安装即可覆盖升级。";
      $("#updateProgress").hidden = true;
      $("#updateProgressMeta").hidden = true;
      $("#updateStages").hidden = true;
      $("#updateError").hidden = true;
      $("#updateDownloadActions").hidden = false;
      $("#downloadUpdateLink").href = manifest.manual_download_url || "/api/cloud/download-update";
      $("#updateFootnote").textContent = "安装前先关闭工程影像管理平台；工程资料不会被覆盖或删除。";
    }

    function renderUpdateStatus(status = {}) {
      const manifest = state.update.manifest || {};
      const overlay = $("#updateOverlay");
      if (!overlay) return;
      const updateState = String(status.state || "checking");
      if (updateState === "installing" && !state.update.installingSince) {
        state.update.installingSince = Date.now();
      } else if (updateState !== "installing") {
        state.update.installingSince = 0;
      }
      if (["checking", "downloading", "verifying", "installing", "installed"].includes(updateState)) {
        state.update.lastActiveState = updateState;
      }
      overlay.dataset.state = updateState;
      openUpdateOverlay("mandatory");
      $("#updateRequiredLabel").textContent = "必须更新";
      const currentVersion = status.current_version || manifest.current_version || $("#appVersionBadge")?.textContent || "当前版本";
      const latestVersion = status.latest_version || manifest.latest_version || "新版本";
      $("#updateVersion").textContent = `${currentVersion} → ${latestVersion}`;

      const titles = {
        checking: "正在准备新版本",
        downloading: "正在下载更新",
        verifying: "正在校验安装包",
        installing: "正在安装新版本",
        installed: "更新完成",
        failed: "更新没有完成"
      };
      $("#updateTitle").textContent = titles[updateState] || "正在更新";
      $("#updateMessage").textContent = status.message || (updateState === "installing"
        ? "正在关闭旧版本并安装，软件随后会自动重启。"
        : "更新会自动完成，请保持软件开启。");

      const total = Math.max(0, Number(status.total_bytes || manifest.size || 0));
      const done = Math.max(0, Math.min(total || Number.MAX_SAFE_INTEGER, Number(status.downloaded_bytes || 0)));
      const percent = total ? Math.max(0, Math.min(100, Math.floor(done * 100 / total))) : Math.max(0, Math.min(100, Number(status.percent || 0)));
      $("#updateProgressFill").style.transform = `scaleX(${percent / 100})`;
      $("#updateProgress").setAttribute("aria-valuenow", String(percent));
      $("#updatePercent").textContent = `${percent}%`;
      $("#updateBytes").textContent = total ? `${formatUpdateBytes(done)} / ${formatUpdateBytes(total)}` : (done ? formatUpdateBytes(done) : "等待下载");

      const visibleStage = updateState === "failed" ? state.update.lastActiveState : updateState;
      const stageRanks = { checking: 0, downloading: 1, verifying: 2, installing: 3, installed: 4 };
      const activeRank = stageRanks[visibleStage] || 0;
      document.querySelectorAll("[data-update-stage]").forEach((node, index) => {
        const rank = index + 1;
        node.classList.toggle("complete", activeRank > rank);
        node.classList.toggle("active", activeRank === rank || updateState === "installed");
      });

      const errorBox = $("#updateError");
      const errorMessage = String(status.error || "");
      errorBox.hidden = !errorMessage;
      errorBox.textContent = errorMessage;
      $("#updateRetryActions").hidden = !(updateState === "failed" && status.retryable !== false);
      $("#updateDevActions").hidden = true;
      $("#updateFootnote").textContent = updateState === "failed"
        ? "工程资料未受影响。请检查网络后重新下载。"
        : "下载完成后软件会自动重启，工程资料不会受影响。";

      if (updateState === "installed" && !state.update.reloadScheduled) {
        state.update.reloadScheduled = true;
        window.setTimeout(() => window.location.reload(), 1200);
      }
    }

    function stopUpdatePolling() {
      if (state.update.pollTimer) window.clearTimeout(state.update.pollTimer);
      state.update.pollTimer = null;
    }

    async function pollUpdateStatus() {
      stopUpdatePolling();
      try {
        const status = await apiJson("/api/cloud/update-status");
        state.update.pollFailures = 0;
        renderUpdateStatus(status);
        if (String(status.state || "") === "installing") {
          const installWait = Date.now() - Number(state.update.installingSince || Date.now());
          if (installWait >= UPDATE_INSTALL_WATCHDOG_MS) {
            renderUpdateStatus({
              state: "failed",
              latest_version: state.update.manifest?.latest_version || "",
              error: "安装等待超时。软件没有完成重启，请重新下载。",
              message: "新版本未能自动启动",
              retryable: true
            });
            return;
          }
        }
        if (["failed", "installed", "idle"].includes(String(status.state || ""))) return;
        state.update.pollTimer = window.setTimeout(pollUpdateStatus, 700);
      } catch (_error) {
        state.update.pollFailures += 1;
        const installing = $("#updateOverlay")?.dataset.state === "installing";
        if (installing) {
          const installWait = Date.now() - Number(state.update.installingSince || Date.now());
          if (installWait >= UPDATE_INSTALL_WATCHDOG_MS) {
            renderUpdateStatus({
              state: "failed",
              latest_version: state.update.manifest?.latest_version || "",
              error: "安装等待超时。请先手动打开软件；若仍是旧版本，请重新下载。",
              message: "新版本未能自动启动",
              retryable: true
            });
            return;
          }
          $("#updateMessage").textContent = "安装正在继续，等待新版本启动…";
          state.update.pollTimer = window.setTimeout(pollUpdateStatus, 1500);
          return;
        }
        if (state.update.pollFailures < 4) {
          state.update.pollTimer = window.setTimeout(pollUpdateStatus, 1000);
          return;
        }
        renderUpdateStatus({
          state: "failed",
          latest_version: state.update.manifest?.latest_version || "",
          error: "暂时无法读取更新进度，请检查网络后重新下载。",
          message: "更新进度读取失败",
          retryable: true
        });
      }
    }

    async function startMandatoryUpdate() {
      stopUpdatePolling();
      state.update.pollFailures = 0;
      renderUpdateStatus({
        state: "checking",
        current_version: state.update.manifest?.current_version || "",
        latest_version: state.update.manifest?.latest_version || "",
        total_bytes: state.update.manifest?.size || 0,
        message: "正在读取更新信息…"
      });
      try {
        const accepted = await apiJson("/api/cloud/apply-update", { method: "POST" });
        renderUpdateStatus(accepted);
        state.update.pollTimer = window.setTimeout(pollUpdateStatus, 250);
      } catch (error) {
        renderUpdateStatus({
          state: "failed",
          latest_version: state.update.manifest?.latest_version || "",
          total_bytes: state.update.manifest?.size || 0,
          error: error.message || "无法开始更新，请重新下载。",
          message: "更新启动失败",
          retryable: true
        });
      }
    }

    async function checkForUpdate(manual = false) {
      if (state.update.checkPromise) return state.update.checkPromise;
      state.update.checkPromise = (async () => {
        const data = await apiJson("/api/cloud/check-update");
        if (!data.has_update || !data.latest_version) {
          setUpdateAvailable(false);
          if (manual) showNotice("当前已是最新版本。");
          return;
        }
        state.update.manifest = data;
        setUpdateAvailable(true);
        // 新版本对登录前后都必须明显可见；用户仍可选择“稍后提醒我”继续使用。
        renderManualUpdate(data);
        return data;
      })();
      try {
        await state.update.checkPromise;
      } finally {
        state.update.checkPromise = null;
      }
    }

    async function ensureAuthenticated(actionText = "操作") {
      const data = await apiJson("/api/auth/me");
      state.auth.user = data.user || null;
      renderAuth();
      if (!state.auth.user) {
        showNotice(`请先登录账号再${actionText}。`, true);
        return false;
      }
      return true;
    }

    function saveLoginCredentials(username, password) {
      try {
        localStorage.setItem("album-login-account", String(username || "").trim());
        if (password) localStorage.setItem("album-login-password", password);
      } catch (e) {}
    }
    function restoreLoginCredentials() {
      try {
        const savedAccount = localStorage.getItem("album-login-account");
        const savedPassword = localStorage.getItem("album-login-password");
        if (savedAccount && $("#gateUsername") && !$("#gateUsername").value) $("#gateUsername").value = savedAccount;
        if (savedPassword && $("#gatePassword") && !$("#gatePassword").value) $("#gatePassword").value = savedPassword;
      } catch (e) {}
    }

    async function submitAuth(url) {
      const usernameInput = $("#gateUsername");
      const passwordInput = $("#gatePassword");
      const username = usernameInput.value.trim();
      const password = passwordInput.value;
      if (!username || !password) {
        showNotice("请填写账号和密码", true);
        return;
      }
      // 登录前先记住，失败也保留账号
      saveLoginCredentials(username, password);
      const button = $("#gateLoginBtn");
      if (button) button.disabled = true;
      try {
      const data = await apiJson(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password, remember: true })
      });
      state.auth.user = data.user || null;
      passwordInput.value = "";
      renderAuth();
      showNotice("已进入软件");
      // 登录成功后重新加载工作台数据并显示加载进度
      await loadBootstrap().catch((error) => showNotice(error.message, true));
      } finally {
        if (button) button.disabled = false;
      }
    }

    async function submitProjectStaffEntry() {
      const nameInput = $("#gateStaffName");
      const phoneInput = $("#gateStaffPhone");
      const display_name = nameInput.value.trim();
      const phone = phoneInput.value.trim();
      if (!display_name || !/^1[3-9]\d{9}$/.test(phone)) {
        showNotice("请输入小程序审批时填写的真实姓名和11位手机号。", true);
        return;
      }
      const button = $("#gateStaffEnterBtn");
      button.disabled = true;
      try {
        const data = await apiJson("/api/cloud/project-staff-entry", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ display_name, phone })
        });
        state.auth.user = data.user || null;
        renderAuth();
        showNotice(`已进入项目：${data.project?.project_name || "当前项目"}`);
        await loadBootstrap().catch((error) => showNotice(error.message, true));
      } finally {
        button.disabled = false;
      }
    }

    function norm(text) {
      return String(text || "").replace(/\s+/g, "").replace(/[：:]/g, "").toLowerCase();
    }

    function fieldValue(fields, group, fallback = "") {
      fields = fields || {};
      const wanted = aliases[group] || [];
      for (const key of wanted) {
        if (fields[key]) return fields[key];
      }
      const wantedNorm = wanted.map(norm);
      for (const [key, value] of Object.entries(fields)) {
        if (!value) continue;
        const nk = norm(key);
        if (wantedNorm.some((item) => item && (nk.includes(item) || item.includes(nk)))) return value;
      }
      return fallback;
    }

    function splitNameCode(text) {
      const raw = String(text || "").trim();
      if (!raw) return { name: "", code: "" };
      const parts = raw.split(/\r?\n| {2,}|	/).map((item) => item.trim()).filter(Boolean);
      if (parts.length >= 2) return { name: parts[0], code: parts[1] };
      const match = raw.match(/^(.+?)[（(]?([A-Za-z0-9_.-]{2,})[）)]?$/);
      if (match && /[\u4e00-\u9fa5]/.test(match[1])) return { name: match[1].trim(), code: match[2].trim() };
      return { name: raw, code: "" };
    }

    function projectCode(project) { return String(project?.project_code || "").trim(); }
    function projectDisplayCode(project) { return String(project?.display_project_code || project?.source_fields?.["单元工程编码"] || project?.project_code || "").trim(); }
    function projectOrder(project) {
      const direct = Number(project?.project_order);
      if (Number.isFinite(direct) && direct > 0) return direct;
      const fields = project?.source_fields || {};
      const fromFields = Number(fields["项目划分顺序"] || fields["导入顺序"] || fields["import_order"]);
      return Number.isFinite(fromFields) && fromFields > 0 ? fromFields : Number.MAX_SAFE_INTEGER;
    }

    function projectName(project) {
      const fields = project?.source_fields || {};
      return fieldValue(fields, "unitName", project?.project_name || projectCode(project) || "未命名单元工程");
    }

    function getHierarchy(project) {
      const fields = project.source_fields || {};
      const unitCombined = splitNameCode(fieldValue(fields, "unitProjectCombined"));
      const partCombined = splitNameCode(fieldValue(fields, "partCombined"));
      return {
        contractName: fieldValue(fields, "contractName", ""),
        unitProjectName: fieldValue(fields, "unitProjectName", unitCombined.name || ""),
        unitProjectCode: fieldValue(fields, "unitProjectCode", unitCombined.code || ""),
        partName: fieldValue(fields, "partName", partCombined.name || ""),
        partCode: fieldValue(fields, "partCode", partCombined.code || ""),
        unitName: projectName(project),
        unitCode: fieldValue(fields, "unitCode", projectDisplayCode(project))
      };
    }

    function makeNode(type, name, code, parent) {
      const key = `${type}:${parent ? parent.key : ""}:${name}:${code || ""}`;
      return { type, key, name, code, parent, children: [], childMap: new Map(), projects: [], order: Number.MAX_SAFE_INTEGER, unitCount: 0, photoTotal: 0, constructionTotal: 0, supervisionTotal: 0, partKey: "" };
    }

    function child(parent, type, name, code) {
      const local = `${type}:${name}:${code || ""}`;
      if (!parent.childMap.has(local)) {
        const node = makeNode(type, name, code, parent);
        parent.childMap.set(local, node);
        parent.children.push(node);
      }
      return parent.childMap.get(local);
    }

    function buildTree(projects) {
      const root = makeNode("root", "全部项目", "", null);
      for (const project of projects) {
        const h = getHierarchy(project);
        if (!h.contractName || !h.unitProjectName || !h.partName) continue;
        const contract = child(root, "contract", h.contractName, "");
        const unit = child(contract, "unitProject", h.unitProjectName, h.unitProjectCode);
        const part = child(unit, "part", h.partName, h.partCode);
        const order = projectOrder(project);
        contract.order = Math.min(contract.order, order);
        unit.order = Math.min(unit.order, order);
        part.order = Math.min(part.order, order);
        part.partKey = project.part_key || part.partKey || "";
        part.projects.push(project);
      }
      sortTree(root);
      return root;
    }

    function buildTreeFromHierarchy(hierarchy) {
      const root = makeNode("root", "全部项目", "", null);
      (hierarchy || []).forEach((contractData) => {
        const contract = child(root, "contract", contractData.name || "未命名合同", "");
        contract.unitCount = Number(contractData.unit_count || 0);
        contract.photoTotal = Number(contractData.photo_count || 0);
        contract.constructionTotal = Number(contractData.construction_photo_count || 0);
        contract.supervisionTotal = Number(contractData.supervision_photo_count || 0);
        (contractData.units || []).forEach((unitData) => {
          const unit = child(contract, "unitProject", unitData.name || "未命名单位工程", unitData.code || "");
          unit.unitCount = Number(unitData.unit_count || 0);
          unit.photoTotal = Number(unitData.photo_count || 0);
          unit.constructionTotal = Number(unitData.construction_photo_count || 0);
          unit.supervisionTotal = Number(unitData.supervision_photo_count || 0);
          (unitData.parts || []).forEach((partData) => {
            const part = child(unit, "part", partData.name || "未命名分部工程", partData.code || "");
            part.partKey = partData.part_key || "";
            part.unitCount = Number(partData.unit_count || 0);
            part.photoTotal = Number(partData.photo_count || 0);
            part.constructionTotal = Number(partData.construction_photo_count || 0);
            part.supervisionTotal = Number(partData.supervision_photo_count || 0);
          });
        });
      });
      return root;
    }

    function compareNatural(a, b) {
      return String(a || "").localeCompare(String(b || ""), "zh-CN", {
        numeric: true,
        sensitivity: "base"
      });
    }

    function nodeSortValue(node) {
      return node.code || node.name || "";
    }

    function sortTree(node) {
      node.children.sort((a, b) => (a.order - b.order) || compareNatural(nodeSortValue(a), nodeSortValue(b)) || compareNatural(a.name, b.name));
      node.projects.sort((a, b) => (projectOrder(a) - projectOrder(b)) || compareNatural(projectCode(a), projectCode(b)));
      node.children.forEach(sortTree);
    }

    function countParts(node) {
      if (!node) return 0;
      return (node.type === "part" ? 1 : 0) + node.children.reduce((sum, item) => sum + countParts(item), 0);
    }

    function projectCount(node) {
      if (!node) return 0;
      if (node.type === "part") return Number(node.unitCount || node.projects.length || 0);
      if (node.unitCount) return Number(node.unitCount);
      return node.children.reduce((sum, item) => sum + projectCount(item), 0);
    }

    function photoCount(node) {
      if (!node) return 0;
      if (Number.isFinite(Number(node.photoTotal)) && Number(node.photoTotal) > 0) return Number(node.photoTotal);
      if (node.type === "part") {
        return node.projects.reduce((sum, project) => sum + Number(project.photo_count || 0), 0);
      }
      return node.children.reduce((sum, item) => sum + photoCount(item), 0);
    }

    function categoryPhotoCount(node, category) {
      if (!node) return 0;
      const aggregate = category === "supervision" ? node.supervisionTotal : node.constructionTotal;
      if (Number.isFinite(Number(aggregate)) && Number(aggregate) > 0) return Number(aggregate);
      const field = category === "supervision" ? "supervision_photo_count" : "construction_photo_count";
      if (node.type === "part") {
        return node.projects.reduce((sum, project) => sum + Number(project[field] || 0), 0);
      }
      return node.children.reduce((sum, item) => sum + categoryPhotoCount(item, category), 0);
    }

    function photoMetricBadges(node) {
      return [
        metricBadge(categoryPhotoCount(node, "construction"), "施工", { hideZero: true }),
        metricBadge(categoryPhotoCount(node, "supervision"), "监理", { hideZero: true })
      ].join("");
    }

    function treeNodeCount(node) {
      if (!node) return 0;
      return photoCount(node);
    }

    function metricBadge(value, label, options = {}) {
      const count = Number(value || 0);
      if (options.hideZero && count === 0) return "";
      return `<span class="blueprint-metric">${count} ${label}</span>`;
    }

    async function deleteHierarchyNode(type, name, code = "") {
      if (!(await ensureAuthenticated("删除工程层级"))) return;
      const current = currentEngineeringProject();
      const label = type === "contract" ? "合同工程" : type === "unitProject" ? "单位工程" : "分部工程";
      if (!confirm(`确认删除当前工程中的${label}“${name}”吗？相关单元和照片会移入备份目录。`)) return;
      const safetyPassword = prompt("请输入当前工程删除密码");
      if (!safetyPassword) {
        showNotice("请输入当前工程删除密码。", true);
        return;
      }
      const data = await apiJson("/api/delete-node", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ type, name, code, safety_password: safetyPassword, project_id: current?.id || "" })
      });
      if (!data.deleted) {
        showNotice(`没有删除任何内容：${label}“${name}”的名称或编码与当前划分不一致，请先刷新确认后再试。`, true);
        return;
      }
      state.projects = data.projects || [];
      state.treeRoot = buildTree(state.projects);
      expandAdaptiveTree();
      if (state.selectedPart && !findNode(state.treeRoot, state.selectedPart.key)) {
        state.selectedPart = null;
        if (state.viewMode === "part") setView("overview");
      }
      renderTree();
      renderOverview();
      try {
        await refreshAll();
      } catch (error) {
        // 已用删除接口返回的最新数据刷新过，二次刷新失败不再影响显示
      }
      showNotice(`${label}“${name}”已删除：${data.deleted} 个单元已移入备份。`);
    }

    function findPartNode(name, code) {
      let found = null;
      (function walk(node) {
        if (found || !node) return;
        if (node.type === "part" && String(node.name) === String(name) && String(node.code || "") === String(code || "")) {
          found = node;
          return;
        }
        node.children.forEach(walk);
      })(state.treeRoot);
      return found;
    }

    async function deleteUnit() {
      const project = state.selectedProject;
      if (!project) return;
      if (!(await ensureAuthenticated("删除单元"))) return;
      const code = projectCode(project);
      const h = getHierarchy(project);
      if (!confirm(`确认删除单元工程“${projectName(project)}”（${projectCode(project)}）吗？\n该单元的照片会移入备份目录，剩余单元按编号自动重新排序。`)) return;
      const safetyPassword = prompt("请输入当前工程删除密码");
      if (!safetyPassword) {
        showNotice("请输入当前工程删除密码。", true);
        return;
      }
      const data = await apiJson(`/api/delete-unit/${encodeURIComponent(code)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ safety_password: safetyPassword })
      });
      if (!data.ok) {
        showNotice(String(data.error || "删除单元失败。"), true);
        return;
      }
      state.projects = data.projects || [];
      state.treeRoot = buildTree(state.projects);
      expandAdaptiveTree();
      state.selectedProject = null;
      state.selectedCode = "";
      state.photos = [];
      state.selectedPrintPhotos = {};
      state.photoSelectMode = {};
      setRouteUnitCode("");
      const partNode = state.selectedPart && findNode(state.treeRoot, state.selectedPart.key)
        ? findNode(state.treeRoot, state.selectedPart.key)
        : findPartNode(h.partName, h.partCode);
      if (partNode) {
        openPart(partNode);
      } else {
        openOverview();
      }
      renderOtherImagesTree();
      showNotice(`单元“${projectName(project)}”已删除，照片已移入备份目录，剩余单元已按编号重新排序。`);
    }

    function flattenParts(node, list = []) {
      if (!node) return list;
      if (node.type === "part") list.push(node);
      node.children.forEach((item) => flattenParts(item, list));
      return list;
    }

    function densityClass(unitCount, partCountValue = 0) {
      if (unitCount <= 20 && partCountValue <= 12) return "is-sparse";
      if (unitCount > 120 || partCountValue > 45) return "is-dense";
      return "is-balanced";
    }

    function expandAdaptiveTree() {
      // 项目划分树固定全部展开（合同→单位→分部），始终可见
      if (!state.treeRoot) return;
      state.expanded.clear();
      const walk = (node) => {
        if (!node.children.length) return;
        state.expanded.add(node.key);
        node.children.forEach(walk);
      };
      state.treeRoot.children.forEach(walk);
    }

    function renderTree() {
      syncSideTreeScope();
      renderTreeLevelButtons();
      const tree = $("#tree");
      const unitImagesButton = $("#unitImagesTreeBtn");
      if (unitImagesButton) {
        unitImagesButton.classList.toggle("active", state.viewMode === "unitImages");
      }
      if (!state.treeRoot || !state.treeRoot.children.length) {
        tree.innerHTML = `<div class="empty-side">暂无项目划分。请先导入项目划分表，或手动补录单元工程。</div>`;
        return;
      }
      if (state.treeLevelFilter !== "all") {
        renderFilteredTree(tree);
        return;
      }
      const html = [];
      for (const node of state.treeRoot.children) renderNode(node, 0, html);
      tree.innerHTML = html.join("");
      tree.onclick = (event) => {
        const row = event.target.closest(".tree-row[data-key]");
        if (!row) return;
        const key = row.dataset.key;
        const node = findNode(state.treeRoot, key);
        if (!node) return;
        if (node.type === "contract") {
          openOverview("construction");
        } else if (node.type === "part") {
          openPart(node);
        }
        // 项目划分树固定展开，点击不折叠
      };
    }

    function renderFilteredTree(tree) {
      if (state.treeLevelFilter === "unit" && !state.allProjectsLoaded) {
        tree.innerHTML = `<div class="empty-side">正在按需加载单元工程…</div>`;
        ensureAllProjectsLoaded().then(() => renderFilteredTree(tree)).catch((error) => {
          tree.innerHTML = `<div class="empty-side">加载失败：${escapeHtml(error.message || "请重试")}</div>`;
        });
        return;
      }
      let rows = [];
      if (state.treeLevelFilter === "unitProject") {
        state.treeRoot.children.forEach((contract) => contract.children.forEach((unit) => rows.push({ node: unit, label: unit.name, sub: displayContractName(contract.name), count: photoCount(unit), type: "unitProject" })));
      } else if (state.treeLevelFilter === "part") {
        state.treeRoot.children.forEach((contract) => contract.children.forEach((unit) => unit.children.forEach((part) => rows.push({ node: part, label: part.name, sub: unit.name, count: photoCount(part), type: "part" }))));
      } else if (state.treeLevelFilter === "unit") {
        flattenParts(state.treeRoot).forEach((part) => part.projects.forEach((project) => rows.push({ project, label: projectName(project), sub: part.name, count: Number(project.photo_count || 0), type: "unit" })));
      }
      tree.innerHTML = rows.length ? rows.map((row) => `
        <button class="tree-row" data-filter-key="${escapeHtml(row.type === "unit" ? projectCode(row.project) : row.node.key)}" data-filter-type="${escapeHtml(row.type)}">
          <span class="caret">•</span>
          <span class="name" title="${escapeHtml(row.label)}">${escapeHtml(row.label)}</span>
          <span class="count">${row.count}</span>
        </button>
      `).join("") : `<div class="empty-side">当前层级暂无数据。</div>`;
      tree.querySelectorAll("[data-filter-key]").forEach((row) => {
        row.addEventListener("click", () => {
          if (row.dataset.filterType === "unit") {
            loadProject(row.dataset.filterKey, "detail").catch((error) => showNotice(error.message, true));
            return;
          }
          const node = findNode(state.treeRoot, row.dataset.filterKey);
          if (node?.type === "part") openPart(node);
          if (node?.type === "unitProject") {
            state.expanded.add(node.parent.key);
            state.expanded.add(node.key);
            state.treeLevelFilter = "all";
            $("#treeLevelFilter").value = "all";
            renderTreeLevelButtons();
            renderTree();
          }
        });
      });
    }

    function renderTreeLevelButtons() {
      const select = $("#treeLevelFilter");
      if (select) select.value = state.treeLevelFilter;
      document.querySelectorAll("[data-tree-level]").forEach((button) => {
        button.classList.toggle("active", button.dataset.treeLevel === state.treeLevelFilter);
      });
      document.querySelectorAll("[data-top-tree-level]").forEach((button) => {
        button.classList.toggle("active", button.dataset.topTreeLevel === state.treeLevelFilter);
      });
    }

    function treeTypeClass(node) {
      // 按节点层级类型加 class，便于用颜色/粗细区分：contract/unitProject/part
      if (node.type === "contract") return " is-contract";
      if (node.type === "unitProject") return " is-unit";
      if (node.type === "part") return " is-part";
      return "";
    }

    function renderNode(node, depth, html) {
      const hasChildren = node.children.length > 0;
      const open = state.expanded.has(node.key);
      const count = treeNodeCount(node);
      const active = state.selectedPart?.key === node.key ? " active" : "";
      const typeClass = treeTypeClass(node);
      const caretMark = hasChildren ? (open ? "▾" : "▸") : "•";
      html.push(`
        <button class="tree-row${typeClass}${active}" data-key="${escapeHtml(node.key)}" data-depth="${depth}" style="padding-left:${9 + depth * 16}px">
          <span class="caret">${caretMark}</span>
          <span class="name" title="${escapeHtml(displayTreeNodeName(node))}">${escapeHtml(displayTreeNodeName(node))}</span>
          <span class="count">${count}</span>
        </button>
      `);
      if (open) node.children.forEach((childNode) => renderNode(childNode, depth + 1, html));
    }

    function findNode(node, key) {
      if (!node) return null;
      if (node.key === key) return node;
      for (const childNode of node.children) {
        const found = findNode(childNode, key);
        if (found) return found;
      }
      return null;
    }

    function walkOtherNodes(nodes, list = []) {
      (nodes || []).forEach((node) => {
        list.push(node);
        walkOtherNodes(node.children || [], list);
      });
      return list;
    }

    function findOtherNode(code) {
      return walkOtherNodes(state.otherImages.nodes || []).find((node) => String(node.code || "") === String(code || "")) || null;
    }

    function countOtherNodes(nodes = []) {
      return (nodes || []).reduce((sum, node) => sum + 1 + countOtherNodes(node.children || []), 0);
    }

    function setSideTreeScope(scope) {
      const isOther = scope === "other";
      $("#sideConstructionBtn").classList.toggle("active", !isOther);
      $("#sideOtherBtn").classList.toggle("active", isOther);
      $("#topConstructionBtn")?.classList.toggle("active", !isOther);
      $("#topOtherBtn")?.classList.toggle("active", isOther);
      // 其它影像不需要左侧树状结构，整体隐藏让主界面占满
      const treeWrap = $(".tree-wrap");
      if (treeWrap) treeWrap.style.display = isOther ? "none" : "";
      const layout = $(".layout");
      if (layout) layout.classList.toggle("is-other", isOther);
      $("#constructionSidePanel").style.display = isOther ? "none" : "";
      $("#otherSidePanel").style.display = isOther ? "" : "none";
    }

    function syncSideTreeScope() {
      setSideTreeScope(state.overviewScope === "other" || state.selectedOtherCode ? "other" : "construction");
    }

    function renderOtherImagesTree() {
      syncSideTreeScope();
      const tree = $("#otherImagesTree");
      const nodes = state.otherImages.nodes || [];
      if (!nodes.length) {
        tree.innerHTML = `<div class="empty-side">暂无其它影像。点击“新增”手动添加子项目。</div>`;
        return;
      }
      const html = [];
      nodes.forEach((node) => renderOtherNode(node, 0, html));
      tree.innerHTML = html.join("");
      tree.querySelectorAll("[data-other-open-code]").forEach((row) => {
        row.addEventListener("click", () => {
          const node = findOtherNode(row.dataset.otherOpenCode);
          if (!node) return;
          if ((node.children || []).length) {
            state.otherExpanded.has(node.code) ? state.otherExpanded.delete(node.code) : state.otherExpanded.add(node.code);
          }
          state.selectedOtherCode = node.code;
          loadProject(node.code, "detail").catch((error) => showNotice(error.message, true));
          renderOtherImagesTree();
        });
      });
      tree.querySelectorAll("[data-other-add-child]").forEach((button) => {
        button.addEventListener("click", (event) => {
          event.stopPropagation();
          openOtherImageModal(button.dataset.otherAddChild);
        });
      });
      tree.querySelectorAll("[data-other-delete]").forEach((button) => {
        button.addEventListener("click", (event) => {
          event.stopPropagation();
          deleteOtherImageNode(button.dataset.otherDelete).catch((error) => showNotice(error.message, true));
        });
      });
    }

    function renderOtherNode(node, depth, html) {
      const children = node.children || [];
      const open = state.otherExpanded.has(node.code);
      const active = state.selectedOtherCode === node.code ? " active" : "";
      html.push(`
        <div class="tree-row other-tree-row${active}" style="padding-left:${9 + depth * 16}px">
          <span class="caret">${children.length ? (open ? "▾" : "▸") : "•"}</span>
          <button class="other-node-open" type="button" data-other-open-code="${escapeHtml(node.code || "")}">
            <span class="name" title="${escapeHtml(node.name || node.code || "")}">${escapeHtml(node.name || node.code || "未命名")}</span>
          </button>
          <span class="count">${Number(node.photo_count_total || node.photo_count || 0)}</span>
          <button class="other-node-action" type="button" data-other-add-child="${escapeHtml(node.code || "")}" title="新增子目录">+</button>
          <button class="other-node-action other-node-delete" type="button" data-other-delete="${escapeHtml(node.code || "")}" title="删除目录">×</button>
        </div>
      `);
      if (open) children.forEach((childNode) => renderOtherNode(childNode, depth + 1, html));
    }

    function dashboardFromProjects(projects) {
      const items = projects || [];
      return {
        project_count: items.length,
        photo_count: items.reduce((sum, project) => sum + Number(project.photo_count || 0), 0),
        construction_photo_count: items.reduce((sum, project) => sum + Number(project.construction_photo_count || 0), 0),
        supervision_photo_count: items.reduce((sum, project) => sum + Number(project.supervision_photo_count || 0), 0),
        latest_upload: items.reduce((latest, project) => {
          const value = String(project.latest_upload || "");
          return value > latest ? value : latest;
        }, "")
      };
    }

    function openOtherImageModal(parentCode = "") {
      const parent = parentCode ? findOtherNode(parentCode) : null;
      state.otherImageParentCode = parent?.code || "";
      $("#otherImageTitle").textContent = parent ? "新增其它影像子项目" : "新增其它影像根项目";
      $("#otherImageParentText").textContent = parent
        ? `上级：${parent.name || parent.code}（${parent.code}）`
        : "作为根项目添加。";
      $("#otherImageCodeInput").value = "";
      $("#otherImageNameInput").value = "";
      $("#otherImageModal").classList.add("open");
      $("#otherImageModal").setAttribute("aria-hidden", "false");
      setTimeout(() => $("#otherImageCodeInput").focus(), 0);
    }

    function closeOtherImageModal() {
      $("#otherImageModal").classList.remove("open");
      $("#otherImageModal").setAttribute("aria-hidden", "true");
      state.otherImageParentCode = "";
      $("#otherImageForm").reset();
    }

    async function submitOtherImage(event) {
      event.preventDefault();
      if (!(await ensureAuthenticated("新增其它影像"))) return;
      const code = $("#otherImageCodeInput").value.trim();
      const name = $("#otherImageNameInput").value.trim();
      if (!code || !name) {
        showNotice("请填写其它影像编号和名称。", true);
        return;
      }
      const data = await apiJson("/api/other-images/nodes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ parent_code: state.otherImageParentCode, code, name })
      });
      state.otherImages = data.tree || { nodes: [], photo_count: 0 };
      if (state.otherImageParentCode) state.otherExpanded.add(state.otherImageParentCode);
      closeOtherImageModal();
      renderOtherImagesTree();
      await refreshAll();
      showNotice("其它影像子项目已新增。");
    }

    async function deleteOtherImageNode(code) {
      const node = findOtherNode(code);
      if (!node) return;
      if (!(await ensureAuthenticated("删除其它影像目录"))) return;
      const childCount = countOtherNodes(node.children || []);
      const photoCountValue = Number(node.photo_count_total || node.photo_count || 0);
      const message = childCount || photoCountValue
        ? `确定删除“${node.name || node.code}”及其 ${childCount} 个子目录、${photoCountValue} 张照片吗？`
        : `确定删除“${node.name || node.code}”吗？`;
      if (!window.confirm(message)) return;
      const data = await apiJson(`/api/other-images/nodes/${encodeURIComponent(code)}`, { method: "DELETE" });
      state.otherImages = data.tree || { nodes: [], photo_count: 0 };
      if (state.selectedOtherCode === code || !findOtherNode(state.selectedOtherCode)) {
        state.selectedOtherCode = "";
        setView("overview");
      }
      renderOtherImagesTree();
      await refreshAll();
      showNotice("其它影像目录已删除。");
    }

    function renderOverview() {
      $("#constructionOverviewCount").textContent = projectCount(state.treeRoot);
      $("#constructionOverviewPhotos").textContent = state.dashboard.construction_photo_count || 0;
      $("#supervisionOverviewPhotos").textContent = state.dashboard.supervision_photo_count || 0;
      $("#otherOverviewCount").textContent = countOtherNodes(state.otherImages.nodes || []);
      $("#otherOverviewPhotos").textContent = state.otherImages.photo_count || 0;
      $("#constructionOverviewBtn").classList.toggle("active", state.overviewScope === "construction");
      $("#otherOverviewBtn").classList.toggle("active", state.overviewScope === "other");
      const isOther = state.overviewScope === "other";
      $("#overviewTitle").textContent = isOther ? "工程其它影像" : "工程影像总览";
      $("#overviewSub").textContent = isOther ? "其它影像分类，点击进入详情。" : "施工影像项目结构，点击进入详情。";
      const conPanel = $("#constructionModuleGrid")?.closest(".panel");
      const otherPanel = $("#otherModuleGrid")?.closest(".panel");
      const recentPanel = $("#recentUploadsList")?.closest(".panel");
      if (conPanel) conPanel.style.display = isOther ? "none" : "";
      if (otherPanel) otherPanel.style.display = isOther ? "" : "none";
      if (recentPanel) recentPanel.style.display = "";
      renderConstructionOverview();
      renderOtherOverview();
      loadRecentUploads(isOther ? "other" : "construction");
    }

    let recentUploadsLoading = false;
    async function loadRecentUploads(scope = "construction") {
      if (recentUploadsLoading) return;
      recentUploadsLoading = true;
      try {
        const data = await apiJson(`/api/recent-uploads?limit=20&scope=${scope}`);
        const records = data.records || [];
        const list = $("#recentUploadsList");
        const count = $("#recentUploadsCount");
        if (count) count.textContent = `${records.length} 条`;
        if (!list) return;
        if (!records.length) {
          list.innerHTML = `<div class="empty">暂无最近上传记录。</div>`;
          return;
        }
        list.innerHTML = records.map((rec) => `
          <div class="recent-upload-item" data-code="${escapeHtml(rec.project_code)}" role="button" tabindex="0">
            <span class="recent-upload-thumb${rec.thumb_url ? "" : " is-fallback"}" aria-hidden="true">
              ${rec.thumb_url ? `<img src="${escapeHtml(rec.thumb_url)}" alt="" loading="lazy" decoding="async">` : ""}
            </span>
            <div class="recent-upload-main">
              <strong class="recent-upload-title" title="${escapeHtml(rec.title)}">${escapeHtml(rec.title || "未命名照片")}</strong>
              <span class="recent-upload-meta">
                ${rec.unit ? `<span class="recent-upload-unit" title="${escapeHtml(rec.unit)}">${escapeHtml(rec.unit)}</span>` : ""}
                ${rec.part ? `<span class="recent-upload-part">${escapeHtml(rec.part)}</span>` : ""}
              </span>
            </div>
            <span class="recent-upload-info">
              <span class="recent-upload-who">${escapeHtml(rec.uploaded_by || "—")}</span>
              <span class="recent-upload-when">${escapeHtml(rec.photo_date || rec.upload_time || "")}</span>
            </span>
          </div>
        `).join("");
        list.querySelectorAll(".recent-upload-thumb img").forEach((image) => {
          const showFallback = () => {
            const thumbnail = image.closest(".recent-upload-thumb");
            image.remove();
            thumbnail?.classList.add("is-fallback");
          };
          if (image.complete && !image.naturalWidth) showFallback();
          else image.addEventListener("error", showFallback, { once: true });
        });
        list.querySelectorAll("[data-code]").forEach((row) => {
          row.addEventListener("click", () => loadProject(row.dataset.code, "detail").catch((error) => showNotice(error.message, true)));
          row.addEventListener("keydown", (event) => {
            if (event.key !== "Enter" && event.key !== " ") return;
            event.preventDefault();
            row.click();
          });
        });
      } catch (error) {
        // 静默失败，不阻塞主界面
      } finally {
        recentUploadsLoading = false;
      }
    }

    function renderConstructionOverview() {
      const contracts = state.treeRoot?.children || [];
      const overviewDensity = densityClass(Number(state.dashboard.project_count || 0), countParts(state.treeRoot));
      // 主界面项目结构树固定展开所有单位工程（含其分部）
      if (state.treeRoot?.children?.length) {
        contracts.forEach((contract) => contract.children.forEach((unit) => state.overviewExpandedUnits.add(unit.key)));
      }
      $("#constructionModuleGrid").innerHTML = contracts.length ? `
        <div class="blueprint-tree ${overviewDensity}">
          ${contracts.map((contract) => `
            <section class="blueprint-contract">
              <div class="blueprint-contract-head">
                <div>
                  <strong>${escapeHtml(displayContractName(contract.name))}</strong>
                  <span>合同段</span>
                </div>
                <div class="blueprint-metrics">
                  ${metricBadge(projectCount(contract), "单元")}
                  ${metricBadge(countParts(contract), "分部")}
                  ${photoMetricBadges(contract)}
                  <button class="secondary mini" type="button" data-delete-hierarchy="contract" data-name="${escapeHtml(contract.name)}" data-code="">×</button>
                </div>
              </div>
              <div class="blueprint-units">
                ${contract.children.map((unit) => `
                  <section class="blueprint-unit">
                    <button class="blueprint-unit-head" type="button" data-overview-unit="${escapeHtml(unit.key)}">
                      <div>
                        <strong>${escapeHtml(unit.name)}</strong>
                        <span>${escapeHtml(unit.code || "未填写编码")}</span>
                      </div>
                      <div class="blueprint-unit-actions">
                        <div class="blueprint-metrics">
                          ${metricBadge(projectCount(unit), "单元")}
                          ${photoMetricBadges(unit)}
                        </div>
                        <span class="picker-caret">${state.overviewExpandedUnits.has(unit.key) ? "▾" : "▸"}</span>
                      </div>
                    </button>
                    ${state.overviewExpandedUnits.has(unit.key) ? `<div class="blueprint-parts">
                      ${unit.children.map((part) => `
                        <div class="blueprint-part">
                          <button class="blueprint-part-main" type="button" data-part="${escapeHtml(part.key)}">
                            <span>
                              <strong class="blueprint-part-name">${escapeHtml(part.name)}</strong>
                              <span class="blueprint-part-code">${escapeHtml(part.code || "未填写编码")}</span>
                              <span class="blueprint-part-inline-metrics">${photoMetricBadges(part)}</span>
                            </span>
                          </button>
                        </div>
                      `).join("") || `<div class="empty">暂无分部工程</div>`}
                    </div>` : ""}
                  </section>
                `).join("") || `<div class="empty">暂无单位工程</div>`}
              </div>
            </section>
          `).join("")}
        </div>
      ` : `<div class="empty">暂无施工影像一览，请导入项目划分表。</div>`;

      $("#constructionModuleGrid").querySelectorAll("[data-delete-hierarchy]").forEach((button) => {
        button.addEventListener("click", (event) => {
          event.stopPropagation();
          deleteHierarchyNode(button.dataset.deleteHierarchy, button.dataset.name || "", button.dataset.code || "").catch((error) => showNotice(error.message, true));
        });
      });
      $("#constructionModuleGrid").querySelectorAll("[data-part]").forEach((button) => {
        button.addEventListener("click", () => {
          const node = findNode(state.treeRoot, button.dataset.part);
          if (node) openPart(node);
        });
      });
      $("#constructionModuleGrid").querySelectorAll("[data-overview-unit]").forEach((button) => {
        button.addEventListener("click", (event) => {
          if (event.target.closest("[data-delete-hierarchy]")) return;
          // 主界面项目结构树固定展开，点击不折叠
        });
      });
    }

    function renderOtherOverview() {
      const nodes = state.otherImages.nodes || [];
      $("#otherModuleGrid").innerHTML = nodes.length ? `
        <div class="blueprint-tree other-blueprint-tree ${densityClass(nodes.length, countOtherNodes(nodes))}">
          ${nodes.map((node) => `
            <section class="blueprint-contract other-blueprint-card">
              <button class="blueprint-contract-head" type="button" data-other-open="${escapeHtml(node.code || "")}">
                <div>
                  <strong>${escapeHtml(node.name || node.code || "未命名")}</strong>
                  <span>${escapeHtml(node.code || String(node.folder_name || "").match(/^\d+/)?.[0] || "其它影像分类")}</span>
                </div>
                <div class="blueprint-metrics">
                  ${metricBadge((node.children || []).length, "子项")}
                  ${metricBadge(node.photo_count_total || node.photo_count || 0, "照片", { hideZero: true })}
                </div>
              </button>
            </section>
          `).join("")}
        </div>
      ` : `<div class="empty">暂无工程其它影像。请确认本机目录存在，或点击左侧“新增”手动添加。</div>`;

      $("#otherModuleGrid").querySelectorAll("[data-other-open]").forEach((item) => {
        item.addEventListener("click", (event) => {
          event.stopPropagation();
          const code = item.dataset.otherOpen;
          const node = findOtherNode(code);
          if (!node) return;
          state.selectedOtherCode = code;
          loadProject(code, "detail").catch((error) => showNotice(error.message, true));
        });
      });
    }

    let unitLoadSequence = 0;
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
      state.viewMode = mode;
      document.body.classList.toggle("is-unit-view", mode === "unit");
      $("#overviewView").style.display = mode === "overview" ? "" : "none";
      $("#partView").style.display = mode === "part" ? "" : "none";
      $("#unitView").style.display = mode === "unit" ? "" : "none";
    }

    function routeUnitCode() {
      // 单元属于具体工程，不能跨工程或跨启动复用上次单元编号。
      return new URLSearchParams(window.location.search).get("unit") || "";
    }

    function setRouteUnitCode(code) {
      const url = new URL(window.location.href);
      if (code) {
        url.searchParams.set("unit", code);
      } else {
        url.searchParams.delete("unit");
      }
      window.history.replaceState({}, "", url);
    }

    function openOverview(scope = state.overviewScope || "construction") {
      state.overviewScope = scope;
      state.selectedPart = null;
      state.selectedOtherCode = "";
      state.selectedCode = "";
      setRouteUnitCode("");
      setView("overview");
      renderTree();
      renderOtherImagesTree();
      renderOverview();
    }

    async function openPart(part) {
      state.selectedPart = part;
      state.selectedOtherCode = "";
      state.unitPage = 1;
      state.expanded.add(part.parent?.parent?.key || "");
      state.expanded.add(part.parent?.key || "");
      renderTree();
      renderOtherImagesTree();
      const cached = part.loadedContext === navigationContext() && part.loadedRevision === state.revision;
      if (!cached) part.projects = [];
      part.loading = !cached;
      renderPart();
      setView("part");
      try {
        if (!cached) await loadPartPage(part, 1);
        else await revalidatePart(part);
      } catch (error) {
        part.loading = false;
        part.loadError = error.message || "分部单元加载失败";
        renderPart();
      }
      if (window.matchMedia("(pointer: coarse), (max-width: 900px)").matches) {
        setTimeout(() => $("#partView").scrollIntoView({ block: "start", behavior: "smooth" }), 0);
      }
    }

    async function revalidatePart(part) {
      const context = navigationContext();
      const revision = await apiJson("/api/revision");
      if (!revision.authenticated || state.selectedPart !== part || state.viewMode !== "part" || navigationContext() !== context) return;
      if (Number(revision.revision || 0) !== Number(part.loadedRevision || 0)) {
        state.revision = Number(revision.revision || 0);
        await loadPartPage(part, 1, { silent: true });
        scheduleSummaryRefresh();
      }
    }

    async function loadPartPage(part, page = 1, options = {}) {
      if (!part?.partKey) { renderPart(); return; }
      const context = navigationContext();
      const revision = state.revision;
      const requestKey = `${context}::${revision}`;
      if (part.pendingKey === requestKey && part.pendingLoad) return part.pendingLoad;
      part.loading = !(options.silent && part.projects?.length);
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
    }

    function renderPart() {
      const part = state.selectedPart;
      if (!part) return;
      const parentName = part.parent?.name || "";
      $("#partTitle").textContent = part.name;
      $("#partSub").textContent = `${parentName}${part.code ? " / " + part.code : ""} · 四列显示，点击单元进入详情`;
      $("#partCount").textContent = `${Number(part.unitCount || part.projects.length)} 条`;

      const unitQuery = String(state.unitListQuery || "").trim().toLowerCase();
      const uploadFilter = state.unitUploadFilter || "all";
      const rows = part.projects.filter((project) => {
        const total = Number(project.photo_count || 0);
        if (uploadFilter === "uploaded" && total <= 0) return false;
        if (uploadFilter === "empty" && total > 0) return false;
        if (!unitQuery) return true;
        const haystack = `${projectDisplayCode(project)} ${projectCode(project)} ${projectName(project)}`.toLowerCase();
        return haystack.includes(unitQuery);
      });
      $("#partCount").textContent = rows.length === part.projects.length
        ? `${rows.length} 条`
        : `${rows.length} / ${part.projects.length} 条`;
      const unitRows = $("#unitRows");
      unitRows.className = "unit-card-grid";
      $("#partSub").textContent = `${parentName}${part.code ? " / " + part.code : ""} · 统一卡片显示，点击单元进入详情`;
      if (part.loading) {
        unitRows.innerHTML = `<div class="first-load-skeleton"><span></span><span></span><span></span><span></span></div>`;
        return;
      }
      if (part.loadError) {
        unitRows.innerHTML = `<div class="empty">加载失败：${escapeHtml(part.loadError)} <button class="secondary mini" type="button" data-retry-part>重新加载</button></div>`;
        unitRows.querySelector("[data-retry-part]")?.addEventListener("click", () => loadPartPage(part, part.currentPage || 1));
        return;
      }
      unitRows.innerHTML = rows.length ? rows.map((project) => `
        <button class="unit-card" type="button" data-unit-code="${escapeHtml(projectCode(project))}">
          <span class="code">${escapeHtml(projectDisplayCode(project))}</span>
          <span class="unit-card-main">
            <strong>${escapeHtml(projectName(project))}</strong>
            <span class="unit-card-photo-counts" aria-label="施工和监理照片数量">
              <span><small>施工</small><b class="${Number(project.construction_photo_count || 0) > 0 ? "has-photos" : ""}">${Number(project.construction_photo_count || 0)}</b></span>
              <span><small>监理</small><b class="${Number(project.supervision_photo_count || 0) > 0 ? "has-photos" : ""}">${Number(project.supervision_photo_count || 0)}</b></span>
            </span>
          </span>
          <span class="unit-card-meta">
            <span class="unit-photo-total">${Number(project.photo_count || 0)} 张照片</span>
            <span>${escapeHtml(project.latest_upload || "-")}</span>
          </span>
        </button>
      `).join("") : `<div class="empty">该分部工程下暂无单元工程。</div>`;
      unitRows.querySelectorAll("[data-unit-code]").forEach((button) => {
        button.addEventListener("click", () => loadProject(button.dataset.unitCode, "detail"));
      });
    }

    function setUnitLoadingState(busy) {
      $("#unitView")?.setAttribute("aria-busy", busy ? "true" : "false");
      ["#galleryUploadBtn", "#unitPrintCurrentBtn", "#addProcessBtn", "#unitMoreMenuBtn", "#unitCategoryConstructionBtn", "#unitCategorySupervisionBtn"].forEach((selector) => { if ($(selector)) $(selector).disabled = busy; });
      if ($("#gallerySelectBtn")) $("#gallerySelectBtn").disabled = busy || !activeGalleryPhotos().length;
      if (busy) { $("#unitMoreMenu")?.classList.remove("open"); $("#unitMoreMenuBtn")?.setAttribute("aria-expanded", "false"); }
    }

    async function loadProject(code, tab = "detail") {
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
      setUnitLoadingState(true);
      try {
        const data = await apiJson(`/api/photos/${encodeURIComponent(code)}`, { signal: controller.signal });
        if (ticket !== unitLoadSequence || navigationContext() !== context || state.viewMode !== "unit") return;
      state.selectedProject = data.project;
      state.selectedCode = projectCode(data.project);
      setRouteUnitCode(state.selectedCode);
      if (!findOtherNode(state.selectedCode)) state.selectedOtherCode = "";
      state.photos = data.photos || [];
      state.photoPage = { construction: 1, supervision: 1 };
      state.selectedPrintPhotos = {};
      state.activePhotoCategory = findOtherNode(state.selectedCode) ? "construction" : normalizePhotoCategory(state.pendingUploadCategory || "construction");
      state.activeProcessName = "";
      state.photoSelectionMode = false;
      state.photoSelectionAnchor = -1;
      setUnitLoadingState(false);
      renderUnit();
      setView("unit");
      renderOtherImagesTree();
      if (window.matchMedia("(pointer: coarse), (max-width: 900px)").matches) {
        setTimeout(() => {
          const unitView = $("#unitView");
          const topbarHeight = $(".topbar")?.getBoundingClientRect().height || 0;
          const top = unitView.getBoundingClientRect().top + window.scrollY - topbarHeight - 8;
          window.scrollTo({ top: Math.max(0, top), behavior: "smooth" });
        }, 0);
      }
      if (tab === "upload") openUploadChoiceModal(state.activePhotoCategory, state.activeProcessName, true);
      if (tab !== "upload" && state.pendingUploadCategory) {
        const category = state.pendingUploadCategory;
        state.pendingUploadCategory = "";
        focusUploadCategory(category);
      }
      } catch (error) {
        if (error.name === "AbortError" || ticket !== unitLoadSequence || navigationContext() !== context) return;
        $("#photoSectionsHost").innerHTML = `<div class="empty">加载失败：${escapeHtml(error.message)} <button type="button" class="secondary mini" data-retry-unit>重新加载</button></div>`;
        $("[data-retry-unit]")?.addEventListener("click", () => loadProject(code, tab));
        showNotice(error.message, true);
      } finally {
        if (ticket === unitLoadSequence) unitLoadController = null;
      }
    }

    function renderUnit() {
      const project = state.selectedProject;
      if (!project) return;
      const hierarchy = getHierarchy(project);
      $("#unitTitle").textContent = projectName(project);
      $("#unitSub").textContent = `${projectCode(project)} · ${state.projectInfo?.industry || "工程影像"}`;
      $("#unitBreadcrumbs").textContent = [hierarchy.contractName, hierarchy.unitProjectName, hierarchy.partName, projectName(project)].filter(Boolean).join(" / ") || "工程影像 / 单元工程";
      renderPhotos();
    }

    function openAddProcessModal() {
      if (!state.selectedCode) return;
      $("#addProcessForm").reset();
      $("#addProcessModal").classList.add("open");
      $("#addProcessModal").setAttribute("aria-hidden", "false");
      setTimeout(() => $("#addProcessNameInput")?.focus(), 0);
    }

    function closeAddProcessModal() {
      $("#addProcessModal").classList.remove("open");
      $("#addProcessModal").setAttribute("aria-hidden", "true");
    }


    async function renameProcess(processName) {
      if (!state.selectedCode || !processName) return;
      if (!(await ensureAuthenticated("重命名工序"))) return;
      const value = window.prompt("请输入新的工序名称", processName);
      if (value === null) return;
      const nextName = value.trim();
      if (!nextName) return showNotice("工序名称不能为空。", true);
      if (nextName === processName) return;
      const currentCode = state.selectedCode;
      const context = navigationContext();
      const data = await apiJson(`/api/photos/${encodeURIComponent(currentCode)}/processes/${encodeURIComponent(processName)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: nextName })
      });
      if (state.selectedCode !== currentCode || navigationContext() !== context) return;
      state.selectedProject.processes = data.processes || [];
      if (state.activeProcessName === processName) state.activeProcessName = nextName;
      applyPhotoEditResponse(data);
      renderPhotos();
      scheduleSummaryRefresh();
      showNotice(`工序已重命名为“${nextName}”。`);
    }

    async function deleteProcess(processName) {
      if (!state.selectedCode || !processName) return;
      if (!(await ensureAuthenticated("删除工序"))) return;
      const count = photosForSection(state.activePhotoCategory, processName).length;
      const hint = count > 0
        ? `“${processName}”下当前可见有 ${count} 张照片。删除工序只允许空工序，请先把照片移动到其它工序或单元。`
        : `确定删除空工序“${processName}”吗？`;
      if (!window.confirm(hint)) return;
      const currentCode = state.selectedCode;
      const context = navigationContext();
      const data = await apiJson(`/api/photos/${encodeURIComponent(currentCode)}/processes/${encodeURIComponent(processName)}`, { method: "DELETE" });
      if (state.selectedCode !== currentCode || navigationContext() !== context) return;
      state.selectedProject.processes = data.processes || [];
      if (state.activeProcessName === processName) state.activeProcessName = "";
      applyPhotoEditResponse(data);
      renderPhotos();
      scheduleSummaryRefresh();
      showNotice(`工序“${processName}”已删除。`);
    }

    async function addProcess(event) {
      event?.preventDefault();
      if (!state.selectedCode) return;
      const name = ($("#addProcessNameInput")?.value || "").trim();
      if (!name) return showNotice("请输入工序名称。", true);
      if (!(await ensureAuthenticated("添加工序"))) return;
      const data = await apiJson(`/api/photos/${encodeURIComponent(state.selectedCode)}/processes`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name })
      });
      if (state.selectedProject) state.selectedProject.processes = data.processes || [];
      state.photos = data.photos || [];
      state.activeProcessName = name;
      clearPhotoSelection(false);
      closeAddProcessModal();
      renderPhotos();
      scheduleSummaryRefresh();
      showNotice(`工序「${name}」已添加，照片编号已按两级规则更新。`);
    }

    // 列表缩略图占位：缩略图未生成时显示灰色占位，绝不回退加载原图
    const THUMB_PLACEHOLDER = "data:image/svg+xml;charset=utf-8," + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="480" height="300"><rect width="100%" height="100%" fill="#eef2f1"/><text x="50%" y="50%" fill="#9aa5a1" font-size="16" text-anchor="middle" dominant-baseline="middle">图片加载中</text></svg>');

    // Only DOM is batched. Complete photo metadata remains available to selection/printing.
    const PHOTOS_BATCH = 24;
    let photoLazyObserver = null;
    let photoLazyFrame = 0;
    function scheduleLazyPhotoLoad() {
      if (!photoLazyFrame) photoLazyFrame = requestAnimationFrame(() => { photoLazyFrame = 0; setupLazyPhotoLoad(); });
    }

    function photoCardHTML(photo, key, sectionKey, isSelectMode, index = 0) {
      const orientation = normalizePhotoOrientation(photo.orientation);
      const photoId = String(photo.id || "");
      const isPrintSelected = Boolean(state.selectedPrintPhotos[printSelectionKey(key, photoId)]);
      const title = String(photo.title || photo.original_name || photo.filename || photoId || "未命名照片").trim();
      const date = displayPhotoDate(photo) || "日期未记录";
      const photographer = String(photo.photographer || "").trim();
      const uploader = String(photo.uploaded_by || "").trim();
      const person = photographer
        ? `拍摄者 ${photographer}`
        : (uploader ? `上传者 ${uploader}` : "拍摄者未记录");
      const idLabel = photoIdTail(photo) || photoId;
      return `
        <article class="photo is-${orientation}${isPrintSelected ? " is-selected" : ""}${isSelectMode ? " is-select-mode" : ""}" draggable="${isSelectMode ? "false" : "true"}" data-photo-id="${escapeHtml(photoId)}" data-photo-index="${index}" data-category="${key}" data-section-key="${escapeHtml(sectionKey)}"${isSelectMode ? ` role="button" tabindex="0" aria-pressed="${isPrintSelected ? "true" : "false"}" aria-label="${isPrintSelected ? "取消选择" : "选择"}${escapeHtml(title)}"` : ""}>
          ${isSelectMode ? `<span class="photo-selection-state" aria-hidden="true">✓ 已选择</span>` : ""}
          <button class="photo-preview-trigger" type="button" data-preview-src="${escapeHtml(photo.url || "")}" data-preview-title="${escapeHtml(title)}">
            <img src="${escapeHtml(photo.thumb_url || THUMB_PLACEHOLDER)}" loading="lazy" decoding="async" alt="${escapeHtml(title)}">
          </button>
          <div class="photo-meta archive-info">
            <div class="photo-card-line">
              <button class="photo-title-button" type="button" data-edit-photo="${escapeHtml(photo.id || "")}" data-category="${key}" title="点击修改照片信息">
                <strong class="photo-card-title" title="${escapeHtml(title)}">${escapeHtml(title)}</strong>
                <span class="photo-card-details" title="${escapeHtml(`${idLabel} · ${date} · ${person}`)}">
                  <span class="photo-card-id">${escapeHtml(idLabel)}</span>
                  <span>${escapeHtml(date)}</span>
                  <span>${escapeHtml(person)}</span>
                </span>
              </button>
            </div>
          </div>
        </article>
      `;
    }

    function photosForSection(key, groupName) {
      const processMatches = (photo) => {
        const pn = String(photo.process_name || "").trim();
        return groupName ? pn === groupName : pn === "";
      };
      return categoryPhotos(key).filter(processMatches);
    }

    function loadMorePhotos(sectionEl) {
      const listEl = sectionEl.querySelector(".photos");
      if (!listEl) return;
      const key = sectionEl.dataset.category;
      const groupName = sectionEl.dataset.processName || "";
      const sectionKey = sectionEl.dataset.photoSection;
      const photos = photosForSection(key, groupName);
      const rendered = parseInt(listEl.dataset.rendered || "0", 10);
      if (rendered >= photos.length) return;
      const isSelectMode = Boolean(state.photoSelectionMode);
      const next = photos.slice(rendered, rendered + PHOTOS_BATCH);
      listEl.insertAdjacentHTML("beforeend", next.map((photo, index) => photoCardHTML(photo, key, sectionKey, isSelectMode, rendered + index)).join(""));
      listEl.dataset.rendered = String(rendered + next.length);
      bindPhotoGalleryEvents(listEl);
      scheduleLazyPhotoLoad();
    }

    function setupLazyPhotoLoad() {
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
    }

    function clearPhotoSelection(shouldRender = true) {
      state.selectedPrintPhotos = {};
      state.photoSelectionMode = false;
      state.photoSelectionAnchor = -1;
      if (shouldRender) renderPhotos();
    }

    function activeGalleryPhotos() {
      return photosForSection(state.activePhotoCategory, state.activeProcessName);
    }

    function updatePhotoSelectionBar() {
      const current = activeGalleryPhotos();
      const selected = current.filter((photo) => state.selectedPrintPhotos[printSelectionKey(state.activePhotoCategory, photo.id)]);
      const bar = $("#photoSelectionBar");
      if (bar) bar.hidden = !state.photoSelectionMode;
      if ($("#photoSelectionCount")) $("#photoSelectionCount").textContent = `已选 ${selected.length} 张`;
      if ($("#selectAllCurrentPhotosBtn")) $("#selectAllCurrentPhotosBtn").textContent = current.length > 0 && selected.length === current.length ? "取消全选" : "全选当前";
      if ($("#printSelectedPhotosBtn")) $("#printSelectedPhotosBtn").disabled = !selected.length;
      if ($("#deleteSelectedCurrentPhotosBtn")) $("#deleteSelectedCurrentPhotosBtn").disabled = !selected.length;
      if ($("#gallerySelectBtn")) {
        $("#gallerySelectBtn").textContent = state.photoSelectionMode ? "取消选择" : "选择";
        $("#gallerySelectBtn").disabled = !current.length;
      }
    }

    function selectGalleryScope(category, processName = "") {
      const nextCategory = normalizePhotoCategory(category);
      const nextProcess = String(processName || "").trim();
      if (nextCategory === state.activePhotoCategory && nextProcess === state.activeProcessName) return;
      clearPhotoSelection(false);
      state.activePhotoCategory = nextCategory;
      state.activeProcessName = nextProcess;
      renderPhotos();
    }

    function bindPhotoGalleryEvents(root) {
      root.querySelectorAll("button[data-edit-photo]").forEach((button) => {
        button.onclick = (event) => {
          event.stopPropagation();
          const card = button.closest(".photo");
          if (state.photoSelectionMode && card) return togglePhotoSelection(card, event.shiftKey);
          openPhotoEdit(button.dataset.category, button.dataset.editPhoto).catch((error) => showNotice(error.message, true));
        };
      });
      root.querySelectorAll(".photo[data-photo-id]").forEach((card) => {
        card.onclick = (event) => {
          if (!state.photoSelectionMode) return;
          event.preventDefault();
          togglePhotoSelection(card, event.shiftKey);
        };
        card.onkeydown = (event) => {
          if (!state.photoSelectionMode || (event.key !== "Enter" && event.key !== " ")) return;
          event.preventDefault();
          togglePhotoSelection(card, event.shiftKey);
        };
      });
      root.querySelectorAll("[data-preview-src]").forEach((button) => {
        button.onclick = (event) => {
          const card = button.closest(".photo");
          if (state.photoSelectionMode && card) {
            event.preventDefault();
            event.stopPropagation();
            togglePhotoSelection(card, event.shiftKey);
            return;
          }
          openPhotoPreview(button.dataset.previewSrc, button.dataset.previewTitle);
        };
      });
    }

    function renderPhotos() {
      const host = $("#photoSectionsHost");
      if (!host || !state.selectedProject) return;
      const isOtherUnit = Boolean(findOtherNode(state.selectedCode));
      if (isOtherUnit) state.activePhotoCategory = "construction";
      const processList = isProcessProject() ? selectedProcesses() : [];
      if (state.activeProcessName && !processList.includes(state.activeProcessName)) state.activeProcessName = "";
      const category = normalizePhotoCategory(state.activePhotoCategory);
      const processName = state.activeProcessName || "";
      const sectionKey = photoSectionKey(category, processName);
      const photos = photosForSection(category, processName);
      const renderScope = `${navigationContext()}::${state.selectedCode}::${sectionKey}`;
      const oldRendered = host.dataset.renderScope === renderScope ? Number(host.querySelector(".photos")?.dataset.rendered || 0) : 0;
      const renderLimit = Math.min(photos.length, Math.max(PHOTOS_BATCH, oldRendered));
      host.dataset.renderScope = renderScope;
      const categoryLabel = category === "supervision" ? "监理" : "施工";
      const scopeLabel = processName || "单元照片";

      $("#unitCategoryConstructionBtn")?.classList.toggle("active", category === "construction");
      $("#unitCategorySupervisionBtn")?.classList.toggle("active", category === "supervision");
      if ($("#unitCategorySupervisionBtn")) $("#unitCategorySupervisionBtn").hidden = isOtherUnit;
      if ($("#unitConstructionCount")) $("#unitConstructionCount").textContent = String(categoryPhotos("construction").length);
      if ($("#unitSupervisionCount")) $("#unitSupervisionCount").textContent = String(categoryPhotos("supervision").length);
      if ($("#unitGalleryCount")) $("#unitGalleryCount").textContent = `${photos.length} 张`;

      const processTabs = $("#unitProcessTabs");
      processTabs.innerHTML = [{ name: "", label: "单元照片" }, ...processList.map((name) => ({ name, label: name }))].map((item) => {
        const count = photosForSection(category, item.name).length;
        const manage = item.name
          ? `<span class="process-manage-actions"><button type="button" class="process-manage-btn" data-process-rename="${escapeHtml(item.name)}" title="重命名工序" aria-label="重命名工序">改</button><button type="button" class="process-manage-btn danger" data-process-delete="${escapeHtml(item.name)}" title="删除空工序" aria-label="删除空工序">删</button></span>`
          : "";
        return `<span class="process-tab-item"><button type="button" class="${item.name === processName ? "active" : ""}" data-gallery-process="${escapeHtml(item.name)}" title="${escapeHtml(item.label)}">${escapeHtml(item.label)} <span>${count}</span></button>${manage}</span>`;
      }).join("");
      processTabs.querySelectorAll("[data-gallery-process]").forEach((button) => {
        button.onclick = () => selectGalleryScope(category, button.dataset.galleryProcess || "");
      });
      processTabs.querySelectorAll("[data-process-rename]").forEach((button) => {
        button.onclick = (event) => {
          event.stopPropagation();
          renameProcess(button.dataset.processRename || "").catch((error) => showNotice(error.message, true));
        };
      });
      processTabs.querySelectorAll("[data-process-delete]").forEach((button) => {
        button.onclick = (event) => {
          event.stopPropagation();
          deleteProcess(button.dataset.processDelete || "").catch((error) => showNotice(error.message, true));
        };
      });

      host.className = "photo-side photo-sections is-single-gallery";
      host.innerHTML = `
        <section class="photo-section active-photo-section${photos.length ? "" : " is-empty"}" data-photo-section="${escapeHtml(sectionKey)}" data-category="${category}" data-process-name="${escapeHtml(processName)}">
          <div class="photo-section-head">
            <div><h3 class="photo-section-title">${escapeHtml(categoryLabel)} · ${escapeHtml(scopeLabel)}</h3><p>当前只显示这一组照片，切换上方标签可查看其它分类。</p></div>
            ${category === "supervision" ? `<button class="secondary" type="button" data-use-construction data-process-name="${escapeHtml(processName)}">复制同组施工照片</button>` : ""}
          </div>
          <div class="photos" data-rendered="${renderLimit}">
            ${photos.length ? photos.slice(0, renderLimit).map((photo, index) => photoCardHTML(photo, category, sectionKey, state.photoSelectionMode, index)).join("") : `<div class="empty gallery-empty"><strong>这里还没有照片</strong><span>点击“上传到当前”即可直接归档到 ${escapeHtml(categoryLabel)} / ${escapeHtml(scopeLabel)}。</span></div>`}
          </div>
        </section>`;

      const copyButton = host.querySelector("[data-use-construction]");
      if (copyButton) copyButton.onclick = async () => {
        if (!window.confirm("将同组尚未复制的施工照片复制到监理影像，并自动生成监理编号吗？已复制照片会自动跳过。")) return;
        try {
          if (!(await ensureAuthenticated("使用施工照片"))) return;
          const data = await apiJson(`/api/photos/${encodeURIComponent(state.selectedCode)}/copy-construction-to-supervision`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ process_name: processName })
          });
          state.photos = data.photos || [];
          clearPhotoSelection(false);
          renderPhotos();
          showNotice(`已复制 ${data.added ? data.added.length : 0} 张施工照片到监理影像。`);
        } catch (error) {
          showNotice(error.message, true);
        }
      };
      bindPhotoGalleryEvents(host);
      if (!state.photoSelectionMode) initPhotoDragSort(host);
      setupLazyPhotoLoad();
      updatePhotoSelectionBar();
    }

    function openPhotoPreview(src, title) {
      if (!src) return;
      const image = $("#photoPreviewImage");
      image.src = src;
      image.alt = title || "照片预览";
      $("#photoPreviewTitle").textContent = title || "照片预览";
      $("#photoPreviewModal").classList.add("open");
      $("#photoPreviewModal").setAttribute("aria-hidden", "false");
      state.photoPreviewScale = 1;
      state.photoPreviewFitScale = 1;
      image.onload = fitPhotoPreview;
    }

    function closePhotoPreview() {
      $("#photoPreviewModal").classList.remove("open");
      $("#photoPreviewModal").setAttribute("aria-hidden", "true");
      $("#photoPreviewImage").src = "";
    }

    function clampPhotoScale(scale) {
      return Math.max(0.15, Math.min(5, scale));
    }

    function renderPhotoPreviewScale() {
      const image = $("#photoPreviewImage");
      const scale = clampPhotoScale(state.photoPreviewScale || 1);
      state.photoPreviewScale = scale;
      image.style.width = `${Math.max(1, Math.round((image.naturalWidth || 1) * scale))}px`;
      image.style.height = "auto";
      image.style.transform = "none";
      $("#photoZoomValue").textContent = `${Math.round(scale * 100)}%`;
    }

    function fitPhotoPreview() {
      const image = $("#photoPreviewImage");
      const body = $(".photo-preview-body");
      if (!image.naturalWidth || !image.naturalHeight) return;
      const fitWidth = Math.max(1, body.clientWidth - 24) / image.naturalWidth;
      const fitHeight = Math.max(1, body.clientHeight - 24) / image.naturalHeight;
      state.photoPreviewFitScale = clampPhotoScale(Math.min(fitWidth, fitHeight, 1));
      state.photoPreviewScale = state.photoPreviewFitScale;
      renderPhotoPreviewScale();
      body.scrollTo({ left: 0, top: 0 });
    }

    function zoomPhotoPreview(delta) {
      const body = $(".photo-preview-body");
      const beforeLeft = body.scrollLeft + body.clientWidth / 2;
      const beforeTop = body.scrollTop + body.clientHeight / 2;
      const oldScale = state.photoPreviewScale || 1;
      state.photoPreviewScale = clampPhotoScale(oldScale + delta);
      renderPhotoPreviewScale();
      const ratio = state.photoPreviewScale / oldScale;
      body.scrollLeft = beforeLeft * ratio - body.clientWidth / 2;
      body.scrollTop = beforeTop * ratio - body.clientHeight / 2;
    }
    function escapeHtml(value) {
      return String(value ?? "").replace(/[&<>"']/g, (char) => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;"
      }[char]));
    }

    function renderUploadProcessOptions(preferredProcess = null) {
      const select = $("#uploadProcessSelect");
      if (!select) return;
      const processes = state.selectedProject && Array.isArray(state.selectedProject.processes) ? state.selectedProject.processes : [];
      const wanted = preferredProcess === null ? select.value : String(preferredProcess || "");
      select.innerHTML = `<option value="">单元照片</option>${processes.map((name) => `<option value="${escapeHtml(name)}">工序 · ${escapeHtml(name)}</option>`).join("")}`;
      select.value = processes.includes(wanted) ? wanted : "";
    }

    function renderUploadTargetSummary() {
      const summary = $("#uploadTargetSummary");
      if (!summary) return;
      if (!state.selectedCode || !state.selectedProject) {
        summary.textContent = "尚未选择归档单元";
        summary.classList.add("is-empty");
        return;
      }
      const category = normalizePhotoCategory(state.uploadChoiceCategory) === "supervision" ? "监理" : "施工";
      const processName = $("#uploadProcessSelect")?.value || "";
      summary.classList.remove("is-empty");
      summary.innerHTML = `<strong>${escapeHtml(projectName(state.selectedProject))}</strong><span>${escapeHtml(state.selectedCode)} · ${category} · ${escapeHtml(processName || "单元照片")}</span>`;
    }

    async function openUploadChoiceModal(category = null, processName = null, lockToCurrentUnit = false) {
      const currentUnitOnly = Boolean(lockToCurrentUnit && state.selectedCode && state.selectedProject);
      const modal = $("#uploadChoiceModal");
      modal.classList.toggle("is-current-unit-upload", currentUnitOnly);
      $("#uploadChoiceSub").textContent = currentUnitOnly
        ? "当前单元已锁定，只需确认类别和工序后添加照片。"
        : "先选择归档单元，再添加照片。";
      $("#uploadProjectSearch").value = "";
      $("#uploadModalResult").style.display = "none";
      $("#uploadModalResult").classList.remove("is-warning");
      $("#uploadModalForm").reset();
      state.uploadQueuedFiles = [];
      state.uploadQueueResults = [];
      renderUploadFileQueue();
      setUploadChoiceCategory(category || state.activePhotoCategory || state.uploadChoiceCategory || "construction");
      if (!currentUnitOnly) {
        $("#uploadProjectPickerBody").innerHTML = `<div class="unit-image-empty">正在加载单元工程…</div>`;
        await ensureAllProjectsLoaded();
        syncSelectedProjectFromList();
        renderUploadProjectPicker();
      }
      renderUploadProcessOptions(processName === null ? state.activeProcessName : processName);
      renderUploadTargetSummary();
      modal.classList.add("open");
      modal.setAttribute("aria-hidden", "false");
      setTimeout(() => (currentUnitOnly ? $("#uploadModalFiles") : $("#uploadProjectSearch"))?.focus(), 0);
    }

    function openUnitUpload(category, processName = state.activeProcessName) {
      if (!state.selectedCode || !state.selectedProject) {
        showNotice("请先选择单元工程。", true);
        return;
      }
      openUploadChoiceModal(normalizePhotoCategory(category), processName, true).catch((error) => showNotice(error.message, true));
    }

    function closeUploadChoiceModal() {
      $("#uploadChoiceModal").classList.remove("open");
      $("#uploadChoiceModal").setAttribute("aria-hidden", "true");
    }

    async function focusUploadCategory(category) {
      if (!state.selectedCode) {
        showNotice("请先在项目划分中选择单元工程。", true);
        return;
      }
      if (state.viewMode !== "unit") await loadProject(state.selectedCode, "detail");
      state.activePhotoCategory = normalizePhotoCategory(category);
      state.activeProcessName = "";
      clearPhotoSelection(false);
      setView("unit");
      renderPhotos();
      await openUploadChoiceModal(state.activePhotoCategory, state.activeProcessName, true);
    }

    function normalizeImageFiles(files) {
      return Array.from(files || []).filter((file) => /\.(jpe?g|png)$/i.test(file.name || ""));
    }

    function uploadFileKey(file) {
      return `${file.name || "photo"}:${file.size || 0}:${file.lastModified || 0}`;
    }

    function renderUploadFileQueue() {
      const queue = $("#uploadFileQueue");
      const summary = $("#uploadModalFileSummary");
      if (summary) summary.textContent = state.uploadQueuedFiles.length ? `待上传 ${state.uploadQueuedFiles.length} 张，确认位置后点击“开始上传”。` : "支持 JPG、JPEG、PNG，可一次选择多张。";
      if (!queue) return;
      queue.innerHTML = state.uploadQueuedFiles.map((file, index) => {
        const result = state.uploadQueueResults[index] || { status: "queued", message: "等待上传" };
        const size = file.size >= 1024 * 1024 ? `${(file.size / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(file.size / 1024))} KB`;
        return `<div class="upload-queue-item is-${escapeHtml(result.status)}"><span class="upload-queue-index">${index + 1}</span><strong title="${escapeHtml(file.name)}">${escapeHtml(file.name)}</strong><small>${size}</small><em>${escapeHtml(result.message || "等待上传")}</em><button type="button" data-remove-upload-file="${index}" aria-label="移除 ${escapeHtml(file.name)}">×</button></div>`;
      }).join("");
      queue.querySelectorAll("[data-remove-upload-file]").forEach((button) => {
        button.onclick = () => {
          const index = Number(button.dataset.removeUploadFile);
          state.uploadQueuedFiles.splice(index, 1);
          state.uploadQueueResults.splice(index, 1);
          renderUploadFileQueue();
        };
      });
    }

    function updateUploadModalFileSummary(files, append = false) {
      const allFiles = Array.from(files || []);
      const imageFiles = normalizeImageFiles(allFiles);
      const skipped = Math.max(0, allFiles.length - imageFiles.length);
      const base = append ? state.uploadQueuedFiles : [];
      const seen = new Set(base.map(uploadFileKey));
      state.uploadQueuedFiles = [...base, ...imageFiles.filter((file) => !seen.has(uploadFileKey(file)))];
      state.uploadQueueResults = state.uploadQueuedFiles.map(() => ({ status: "queued", message: "等待上传" }));
      renderUploadFileQueue();
      if (skipped) showNotice(`已忽略 ${skipped} 个非 JPG/PNG 文件。`, true);
    }

    async function uploadFromModal(event) {
      event?.preventDefault();
      if (!state.selectedCode) {
        showNotice("请先在项目划分中选择单元工程。", true);
        return;
      }
      if (!(await ensureAuthenticated("上传照片"))) return;
      const files = [...state.uploadQueuedFiles];
      if (!files.length) {
        showNotice("请选择或拖入 JPG/PNG 照片。", true);
        return;
      }
      const uploadCode = state.selectedCode;
      const processName = $("#uploadProcessSelect")?.value || "";
      const startButton = $("#startUploadBtn");
      const autoButton = $("#autoMatchUploadBtn");
      startButton.disabled = true;
      autoButton.disabled = true;
      let latestPhotos = state.photos;
      let successCount = 0;
      const failedFiles = [];
      const failedResults = [];
      for (let index = 0; index < files.length; index += 1) {
        const file = files[index];
        state.uploadQueueResults[index] = { status: "uploading", message: "正在上传" };
        renderUploadFileQueue();
        const form = new FormData();
        form.append("category", state.uploadChoiceCategory || "construction");
        form.append("title", $("#uploadModalTitle").value.trim());
        form.append("photo_date", $("#uploadModalDate").value || parseDateFromName(file.name));
        form.append("photographer", $("#uploadModalPhotographer").value.trim());
        form.append("description", "");
        form.append("orientation", "landscape");
        form.append("process_name", processName);
        form.append("process_code", processCodeForName(processName));
        form.append("files", file);
        try {
          const data = await apiJson(`/api/upload/${encodeURIComponent(uploadCode)}`, { method: "POST", body: form });
          latestPhotos = data.photos || latestPhotos;
          successCount += 1;
          state.uploadQueueResults[index] = { status: "success", message: "上传成功" };
        } catch (error) {
          failedFiles.push(file);
          failedResults.push({ status: "failed", message: error.message || "上传失败，可重试" });
          state.uploadQueueResults[index] = { status: "failed", message: error.message || "上传失败" };
        }
        renderUploadFileQueue();
      }
      if (state.selectedCode === uploadCode) state.photos = latestPhotos;
      startButton.disabled = false;
      autoButton.disabled = false;
      await refreshAll();
      renderUploadProjectPicker();
      if (state.viewMode === "unit" && state.selectedCode === uploadCode) renderPhotos();
      const result = $("#uploadModalResult");
      result.classList.toggle("is-warning", Boolean(failedFiles.length));
      result.innerHTML = `
        <span>已成功归档 ${successCount} 张${failedFiles.length ? `，${failedFiles.length} 张失败，可直接重试` : ""}。</span>
        <button class="secondary mini" type="button" id="uploadModalDetailBtn">查看详情</button>
      `;
      result.style.display = "flex";
      $("#uploadModalDetailBtn").addEventListener("click", () => {
        closeUploadChoiceModal();
        loadProject(uploadCode, "detail").catch((error) => showNotice(error.message, true));
      });
      state.uploadQueuedFiles = failedFiles;
      state.uploadQueueResults = failedResults;
      $("#uploadModalFiles").value = "";
      renderUploadFileQueue();
      showNotice(failedFiles.length ? "部分照片上传失败，请检查后重试。" : "照片已全部上传并归档。", Boolean(failedFiles.length));
    }

    async function uploadAutoMatchFromModal() {
      if (!(await ensureAuthenticated("自动匹配上传照片"))) return;
      const files = [...state.uploadQueuedFiles];
      if (!files.length) {
        showNotice("请选择 JPG/PNG 照片后再自动匹配上传。", true);
        return;
      }
      await previewFolderImport(files, state.uploadChoiceCategory || "construction");
      closeUploadChoiceModal();
    }

    async function uploadCategoryFiles(key, files, sourceForm = null) {
      if (!state.selectedCode) {
        showNotice("请先选择单元工程。", true);
        return;
      }
      if (!(await ensureAuthenticated("上传照片"))) return;
      files = Array.from(files || []);
      if (!files.length) {
        showNotice("请选择要上传的照片。", true);
        return;
      }

      const form = new FormData();
      const getValue = (suffix) => {
        if (sourceForm) {
          const input = sourceForm.querySelector(`[id$="${suffix}"]`);
          return input ? input.value : "";
        }
        return $(`#${key}${suffix}`)?.value || "";
      };
      let photoDate = getValue("PhotoDate");
      let photoTitle = getValue("PhotoTitle").trim();
      // 文件名含日期/文字时自动识别填充
      if (!photoDate || !photoTitle) {
        const firstFile = files[0];
        if (firstFile) {
          if (!photoDate) photoDate = parseDateFromName(firstFile.name);
          if (!photoTitle) {
            const clean = String(firstFile.name || "").replace(/\.(jpe?g|png)$/i, "")
              .replace(/^(?:IMG|VID|DSC|PANO)_?/, "")
              .replace(/(20\d{2})\s*[年.\-/]\s*\d{1,2}\s*[月.\-/]\s*\d{1,2}\s*日?/, "")
              .replace(/(20\d{2})(\d{2})(\d{2})/, "")
              .replace(/^\s*\d+[号#\s]*/, "")
              .replace(/^[\s_\-—–·.]+|[\s_\-—–·.]+$/, "");
            if (clean) photoTitle = clean;
          }
        }
      }
      form.append("category", key);
      form.append("title", photoTitle);
      form.append("photo_date", photoDate || "");
      form.append("photographer", getValue("PhotoPhotographer").trim());
      form.append("description", getValue("PhotoDescription").trim());
      form.append("orientation", "landscape");
      form.append("process_name", sourceForm?.dataset.processName || "");
      form.append("process_code", processCodeForName(sourceForm?.dataset.processName || ""));
      files.forEach((file) => form.append("files", file));

      const data = await apiJson(`/api/upload/${encodeURIComponent(state.selectedCode)}`, { method: "POST", body: form });
      state.photos = data.photos || [];
      state.photoPage[key] = Math.max(1, Math.ceil(categoryPhotos(key).length / state.photoPageSize));
      if (sourceForm) sourceForm.reset();
      else $(`#${key}UploadForm`)?.reset();
      renderPhotos();
      await refreshAll();
      if (!sourceForm) showInlineUploadSuccess(`#${key}UploadResult`, `上传成功，当前页面已刷新，共上传 ${files.length} 张照片。`);
      showNotice("照片已上传，当前页面已刷新。");
    }

    function folderProjectLabel(project) {
      if (!project) return "";
      const fields = project.source_fields || {};
      const code = project.display_project_code || fields["单元工程编码"] || project.project_code || "";
      return code + "｜" + (project.project_name || fields["单元工程名称"] || code);
    }

    function resolveFolderProject(value) {
      const text = String(value || "").trim();
      return state.projects.find((project) => folderProjectLabel(project) === text)
        || state.projects.find((project) => String(project.project_code || "") === text)
        || null;
    }

    function closeFolderReview() {
      $("#folderReviewModal").classList.remove("open");
      $("#folderReviewModal").setAttribute("aria-hidden", "true");
      state.folderReviewFiles = [];
      state.folderReviewRows = [];
      $("#folderReviewRows").innerHTML = "";
    }

    function renderFolderReview() {
      const rows = state.folderReviewRows || [];
      $("#folderReviewProjects").innerHTML = state.projects
        .map((project) => '<option value="' + escapeHtml(folderProjectLabel(project)) + '"></option>')
        .join("");
      const high = rows.filter((row) => row.confidence === "high").length;
      const medium = rows.filter((row) => row.confidence === "medium").length;
      const low = rows.length - high - medium;
      $("#folderReviewSummary").textContent = "共 " + rows.length + " 张：高置信 " + high + " 张，中置信 " + medium + " 张，需重点审核 " + low + " 张。";
      $("#folderReviewRows").innerHTML = rows.map((row, index) => {
        const project = state.projects.find((item) => item.project_code === row.project_code);
        const unitValue = folderProjectLabel(project);
        const confidenceText = row.ambiguous ? "多候选 · 必须确认" : ((row.confidence_label || "低") + "置信");
        const reasons = (row.reasons || []).slice(0, 3).join("；");
        return '<tr data-review-index="' + index + '">'
          + '<td><input type="checkbox" data-review-include checked aria-label="导入此照片"></td>'
          + '<td><div class="folder-review-file">' + escapeHtml(row.relative_path || row.filename || "") + '</div>'
          + '<div class="folder-review-meta">施工区域：' + escapeHtml(row.construction_area || "未识别") + '<br>施工内容：' + escapeHtml(row.construction_content || "未识别") + '</div></td>'
          + '<td><input type="text" data-review-title value="' + escapeHtml(row.title || "") + '" placeholder="施工内容 / 照片题名">'
          + '<input type="date" data-review-date value="' + escapeHtml(String(row.photo_date || "").slice(0, 10)) + '"></td>'
          + '<td><span class="match-confidence ' + escapeHtml(row.confidence || "low") + '">' + escapeHtml(confidenceText) + '</span>'
          + '<input type="text" data-review-project list="folderReviewProjects" value="' + escapeHtml(unitValue) + '" placeholder="输入单元编码或名称"></td>'
          + '<td><div class="folder-review-meta">' + escapeHtml(reasons || "未找到匹配依据，请手动选择单元") + '</div></td>'
          + '</tr>';
      }).join("");
      $("#folderReviewModal").classList.add("open");
      $("#folderReviewModal").setAttribute("aria-hidden", "false");
    }

    async function previewFolderImport(files, category = "construction") {
      await ensureAllProjectsLoaded();
      const form = new FormData();
      const relativePaths = files.map((file) => file.webkitRelativePath || file.relativePath || file.name);
      files.forEach((file) => form.append("files", file, file.name));
      form.append("relative_paths", JSON.stringify(relativePaths));
      showNotice("正在识别水印并匹配项目划分，请稍候……");
      const data = await apiJson("/api/upload-match-preview", { method: "POST", body: form });
      state.folderReviewFiles = files;
      state.folderReviewRows = data.rows || [];
      state.folderReviewCategory = category;
      renderFolderReview();
    }

    async function commitFolderReview() {
      const tableRows = Array.from(document.querySelectorAll("#folderReviewRows tr[data-review-index]"));
      const assignments = tableRows.map((tr) => {
        const index = Number(tr.dataset.reviewIndex || 0);
        const row = state.folderReviewRows[index] || {};
        const project = resolveFolderProject(tr.querySelector("[data-review-project]").value);
        return {
          index,
          filename: row.filename || "",
          include: tr.querySelector("[data-review-include]").checked,
          project_code: project ? project.project_code : "",
          title: tr.querySelector("[data-review-title]").value.trim(),
          photo_date: tr.querySelector("[data-review-date]").value,
          watermark_text: row.watermark_text || ""
        };
      });
      const missing = assignments.find((item) => item.include && !item.project_code);
      if (missing) {
        showNotice("仍有勾选照片未选择有效单元，请先完成审核。", true);
        return;
      }
      const form = new FormData();
      state.folderReviewFiles.forEach((file) => form.append("files", file, file.name));
      form.append("category", state.folderReviewCategory || "construction");
      form.append("assignments", JSON.stringify(assignments));
      $("#confirmFolderReviewBtn").disabled = true;
      try {
        const data = await apiJson("/api/upload-match-commit", { method: "POST", body: form });
        closeFolderReview();
        await refreshAll();
        showNotice("审核导入完成：共 " + Number(data.added_count || 0) + " 张，归档到 " + Number(data.project_count || 0) + " 个单元。");
      } finally {
        $("#confirmFolderReviewBtn").disabled = false;
      }
    }

    $("#folderImportBtn").addEventListener("click", () => $("#folderImportInput").click());
    $("#folderImportInput").addEventListener("change", async (event) => {
      const files = Array.from(event.target.files || []);
      event.target.value = "";
      if (!files.length) return;
      if (!(await ensureAuthenticated("导入文件夹"))) return;
      const imageFiles = normalizeImageFiles(files);
      if (!imageFiles.length) {
        showNotice("文件夹中没有可导入的 JPG/PNG 照片。", true);
        return;
      }
      await previewFolderImport(imageFiles, "construction");
    });

    async function openPhotoEdit(category, photoId) {
      if (!state.selectedCode) {
        showNotice("请先选择单元工程。", true);
        return;
      }
      const context = navigationContext();
      const code = state.selectedCode;
      const original = state.photos.find((item) => normalizePhotoCategory(item.category) === normalizePhotoCategory(category) && String(item.id || "") === String(photoId || ""));
      if (!original || !(await ensureAuthenticated("修改照片信息"))) return;
      if (context !== navigationContext() || code !== state.selectedCode) return;
      const photo = original.photo_uuid ? state.photos.find((item) => item.photo_uuid === original.photo_uuid) : original;
      if (!photo) {
        showNotice("未找到要修改的照片。", true);
        return;
      }
      state.editingPhoto = { category: normalizePhotoCategory(category), photoId: String(photo.id || ""), photoUuid: String(photo.photo_uuid || "") };
      $("#photoEditTitleInput").value = photo.title || "";
      $("#photoEditDateInput").value = displayPhotoDate(photo) || "";
      $("#photoEditPhotographerInput").value = photo.photographer || "";
      $("#photoEditRotationInput").value = String(Number(photo.rotation || 0) || 0);
      $("#photoEditDescriptionInput").value = photo.description || "";
      const processSelect = $("#photoEditProcessInput");
      if (processSelect) {
        const processes = isProcessProject() ? selectedProcesses() : [];
        processSelect.innerHTML = `<option value="">单元照片</option>` + processes.map((name) => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`).join("");
        processSelect.value = photo.process_name || "";
      }
      $("#photoEditSub").textContent = `${photo.id || ""} · ${batchLabel(category)}`;
      $("#viewOriginalPhotoBtn").disabled = !photo.original_backup;
      $("#restoreOriginalPhotoBtn").disabled = !photo.original_backup;
      $("#photoEditModal").classList.add("open");
      $("#photoEditModal").setAttribute("aria-hidden", "false");
      setTimeout(() => $("#photoEditTitleInput").focus(), 0);
    }

    function closePhotoEdit() {
      $("#photoEditModal").classList.remove("open");
      $("#photoEditModal").setAttribute("aria-hidden", "true");
      state.editingPhoto = null;
      $("#photoEditForm").reset();
    }

    function currentEditingPhoto() {
      if (!state.editingPhoto) return null;
      return state.photos.find((item) => state.editingPhoto.photoUuid
        ? String(item.photo_uuid || "") === state.editingPhoto.photoUuid
        : (normalizePhotoCategory(item.category) === state.editingPhoto.category && String(item.id || "") === state.editingPhoto.photoId)) || null;
    }

    function viewOriginalPhoto() {
      const photo = currentEditingPhoto();
      if (!photo?.original_backup || !state.selectedCode) return;
      window.open(`/originals/${encodeURIComponent(state.selectedCode)}/${encodeURIComponent(photo.id)}`, "_blank");
    }

    async function replaceEditedPhotoFromStorage(action) {
      const photo = currentEditingPhoto();
      if (!photo || !state.selectedCode) return;
      if (action === "restore-original" && !confirm("确认恢复原图？日常使用文件会临时恢复为原始大小，可随时重新优化。")) return;
      const data = await apiJson(`/api/photos/${encodeURIComponent(state.selectedCode)}/${encodeURIComponent(photo.id)}/${action}`, { method: "POST" });
      state.photos = state.photos.map((item) => String(item.id || "") === String(photo.id) ? data.photo : item);
      renderPhotos();
      closePhotoEdit();
      showNotice(action === "restore-original" ? "已恢复原图。" : "照片已重新优化。");
    }


    function closePhotoMoveModal() {
      const modal = $("#photoMoveModal");
      if (!modal) return;
      modal.classList.remove("open");
      modal.setAttribute("aria-hidden", "true");
    }

    function filteredMoveTargets() {
      const query = String($("#photoMoveSearchInput")?.value || "").trim().toLowerCase();
      return (state.moveTargets || []).filter((project) => {
        if (!query) return true;
        return `${projectDisplayCode(project)} ${projectCode(project)} ${projectName(project)}`.toLowerCase().includes(query);
      });
    }

    let photoMoveProcessSequence = 0;
    let photoMovePending = false;
    async function refreshPhotoMoveProcesses() {
      const sequence = ++photoMoveProcessSequence;
      const targetCode = $("#photoMoveTargetSelect")?.value || "";
      const processSelect = $("#photoMoveProcessSelect");
      const summary = $("#photoMoveSummary");
      const confirm = $("#confirmPhotoMoveBtn");
      if (confirm) confirm.disabled = true;
      if (processSelect) processSelect.disabled = true;
      if (!targetCode) {
        if (processSelect) processSelect.innerHTML = '<option value="">单元照片</option>';
        if (summary) summary.textContent = "请选择目标单元。";
        return;
      }
      const data = await apiJson(`/api/photos/${encodeURIComponent(targetCode)}`);
      if (sequence !== photoMoveProcessSequence || $("#photoMoveTargetSelect")?.value !== targetCode) return;
      const project = data.project || {};
      const processes = Array.isArray(project.processes) ? project.processes : [];
      if (processSelect) {
        processSelect.innerHTML = ['<option value="">单元照片</option>', ...processes.map((name) => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`)].join("");
      }
      if (processSelect) processSelect.disabled = false;
      if (confirm) confirm.disabled = photoMovePending;
      if (summary) {
        summary.textContent = `从 ${projectDisplayCode(state.selectedProject || {}) || state.selectedCode} 移动到 ${projectDisplayCode(project) || targetCode} · ${projectName(project) || "未命名单元"}`;
      }
    }

    async function renderPhotoMoveTargets() {
      const select = $("#photoMoveTargetSelect");
      if (!select) return;
      const previous = select.value;
      const targets = filteredMoveTargets();
      select.innerHTML = targets.length
        ? targets.map((project) => `<option value="${escapeHtml(projectCode(project))}">${escapeHtml(projectDisplayCode(project))} · ${escapeHtml(projectName(project))}</option>`).join("")
        : '<option value="">未找到匹配单元</option>';
      if (previous && targets.some((project) => projectCode(project) === previous)) select.value = previous;
      await refreshPhotoMoveProcesses();
    }

    async function openPhotoMoveModal() {
      const photo = currentEditingPhoto();
      if (!photo || !state.selectedCode) return showNotice("请先打开要移动的照片。", true);
      if (!(await ensureAuthenticated("移动照片"))) return;
      const data = await apiJson("/api/projects?slim=1");
      const allTargets = (data.projects || []).filter((project) => projectCode(project));
      state.moveTargets = [
        ...allTargets.filter((project) => projectCode(project) === state.selectedCode),
        ...allTargets.filter((project) => projectCode(project) !== state.selectedCode)
      ];
      $("#photoMoveSearchInput").value = "";
      await renderPhotoMoveTargets();
      $("#photoMoveModal").classList.add("open");
      $("#photoMoveModal").setAttribute("aria-hidden", "false");
      setTimeout(() => $("#photoMoveSearchInput")?.focus(), 0);
    }

    async function confirmPhotoMove() {
      const photo = currentEditingPhoto();
      if (!photo || !state.selectedCode || photoMovePending || $("#photoMoveProcessSelect")?.disabled) return;
      if (!(await ensureAuthenticated("移动照片"))) return;
      if (photoMovePending || currentEditingPhoto() !== photo) return;
      const sourceCode = state.selectedCode;
      const targetCode = $("#photoMoveTargetSelect")?.value || "";
      const targetProcess = $("#photoMoveProcessSelect")?.value || "";
      const sourceProcess = String(photo.process_name || "").trim();
      if (!targetCode) return showNotice("请选择目标单元。", true);
      if (targetCode === sourceCode && targetProcess === sourceProcess) {
        return showNotice("照片已经在当前工序，无需移动。", true);
      }
      const targetProject = (state.moveTargets || []).find((project) => projectCode(project) === targetCode);
      const targetLabel = `${projectDisplayCode(targetProject || {}) || targetCode} · ${projectName(targetProject || {}) || "未命名单元"}`;
      if (!window.confirm(`确认把照片“${photo.id}”移动到：\n${targetLabel}${targetProcess ? `\n工序：${targetProcess}` : "\n归属：单元照片"}？`)) return;
      const context = navigationContext();
      photoMovePending = true;
      $("#confirmPhotoMoveBtn").disabled = true;
      try {
      await apiJson(`/api/photos/${encodeURIComponent(sourceCode)}/${encodeURIComponent(photo.id)}/move`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          category: normalizePhotoCategory(photo.category),
          target_project_code: targetCode,
          target_process_name: targetProcess
        })
      });
      if (state.selectedCode !== sourceCode || navigationContext() !== context) return;
      closePhotoMoveModal();
      closePhotoEdit();
      await loadProject(sourceCode, "detail");
      if (state.selectedPart) {
        state.selectedPart.loaded = false;
        await loadPartPage(state.selectedPart, 1);
      }
      showNotice(`照片已移动到 ${targetLabel}${targetProcess ? ` / ${targetProcess}` : ""}。`);
      } finally {
        photoMovePending = false;
        $("#confirmPhotoMoveBtn").disabled = Boolean($("#photoMoveProcessSelect")?.disabled);
      }
    }

    function applyPhotoEditResponse(data) {
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
    async function savePhotoEdit(event) {
      event.preventDefault();
      if (!state.editingPhoto || photoEditSavePending) return;
      const requestedEditor = state.editingPhoto;
      const requestedCode = state.selectedCode;
      const requestedEngineering = state.activeEngineeringProjectId;
      if (!(await ensureAuthenticated("修改照片信息"))) return;
      if (photoEditSavePending || state.editingPhoto !== requestedEditor || state.selectedCode !== requestedCode || state.activeEngineeringProjectId !== requestedEngineering) return;
      const title = $("#photoEditTitleInput").value.trim();
      const photoDate = $("#photoEditDateInput").value.trim();
      const photographer = $("#photoEditPhotographerInput").value.trim();
      const currentPhoto = currentEditingPhoto();
      if (!currentPhoto) return showNotice("照片已发生变化，请关闭后重新选择。", true);
      const processName = $("#photoEditProcessInput") ? $("#photoEditProcessInput").value : (currentPhoto?.process_name || "");
      const processCode = "";
      const orientation = normalizePhotoOrientation(currentPhoto?.orientation);
      const rotation = Number($("#photoEditRotationInput").value || 0);
      const description = $("#photoEditDescriptionInput").value.trim();
      if (!photoDate) {
        showNotice("请填写照片日期。", true);
        return;
      }
      if (!/^\d{4}-\d{2}-\d{2}$/.test(photoDate)) {
        showNotice("日期格式应为 YYYY-MM-DD。", true);
        return;
      }
      const sourceCode = state.selectedCode;
      const sourceEngineering = state.activeEngineeringProjectId;
      const editing = state.editingPhoto;
      const submit = $("#photoEditForm button[type='submit']");
      photoEditSavePending = true;
      if (submit) submit.disabled = true;
      try {
        const data = await apiJson(`/api/photos/${encodeURIComponent(sourceCode)}/${encodeURIComponent(editing.photoId)}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ photo_uuid: editing.photoUuid, title, photo_date: photoDate, photographer, process_name: processName, process_code: processCode, orientation, rotation, description })
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
    }

    function initPhotoForms() {
      photoCategories.forEach(({ key }) => {
        const form = $(`#${key}UploadForm`);
        if (!form) return;
        form.innerHTML = `
          <label>&#36873;&#25321;&#29031;&#29255;<input id="${key}PhotoFiles" type="file" accept=".jpg,.jpeg,.png" multiple></label>
          <label>&#39064;&#21517;<input id="${key}PhotoTitle" type="text" placeholder="文件名含日期和文字时自动识别，可留空"></label>
          <label>&#26102;&#38388;<input id="${key}PhotoDate" type="date" title="文件名含日期可自动识别，留空自动提取"></label>
          <label>&#25668;&#24433;&#32773;<input id="${key}PhotoPhotographer" type="text"></label>
          <label>&#25991;&#23383;&#35828;&#26126;<textarea id="${key}PhotoDescription"></textarea></label>
          <div class="drop-help">可点击选择照片，也可将 JPG/PNG 拖到这里上传。</div>
          <div class="actions"><button type="submit">上传</button></div>
          <div id="${key}UploadResult" class="upload-inline-result" aria-live="polite"></div>
        `;
        let dragDepth = 0;
        form.addEventListener("dragenter", (event) => {
          event.preventDefault();
          dragDepth += 1;
          form.classList.add("is-dragging");
        });
        form.addEventListener("dragover", (event) => {
          event.preventDefault();
          if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
          form.classList.add("is-dragging");
        });
        form.addEventListener("dragleave", () => {
          dragDepth = Math.max(0, dragDepth - 1);
          if (dragDepth === 0) form.classList.remove("is-dragging");
        });
        form.addEventListener("drop", (event) => {
          event.preventDefault();
          dragDepth = 0;
          form.classList.remove("is-dragging");
          uploadCategoryFiles(key, event.dataTransfer.files).catch((error) => showNotice(error.message, true));
        });
      });
    }

    function setPhotoSelected(category, photoId, selected) {
      const key = printSelectionKey(category, photoId);
      if (selected) state.selectedPrintPhotos[key] = true;
      else delete state.selectedPrintPhotos[key];
    }

    function syncPhotoCardSelection(card, selected) {
      card.classList.toggle("is-selected", selected);
      card.setAttribute("aria-pressed", selected ? "true" : "false");
      const title = card.querySelector(".photo-card-title")?.textContent?.trim() || "照片";
      card.setAttribute("aria-label", `${selected ? "取消选择" : "选择"}${title}`);
    }

    function togglePhotoSelection(card, shiftKey = false) {
      const category = card.dataset.category || state.activePhotoCategory;
      const photoId = card.dataset.photoId || "";
      if (!photoId) return;
      const next = !Boolean(state.selectedPrintPhotos[printSelectionKey(category, photoId)]);
      const currentIndex = Number(card.dataset.photoIndex || 0);
      if (shiftKey && state.photoSelectionAnchor >= 0) {
        const start = Math.min(state.photoSelectionAnchor, currentIndex);
        const end = Math.max(state.photoSelectionAnchor, currentIndex);
        activeGalleryPhotos().slice(start, end + 1).forEach((photo) => setPhotoSelected(category, photo.id, next));
        card.closest(".photos")?.querySelectorAll(".photo[data-photo-index]").forEach((item) => {
          const index = Number(item.dataset.photoIndex || 0);
          if (index >= start && index <= end) syncPhotoCardSelection(item, next);
        });
      } else {
        setPhotoSelected(category, photoId, next);
        syncPhotoCardSelection(card, next);
      }
      state.photoSelectionAnchor = currentIndex;
      updatePhotoSelectionBar();
    }

    function selectedPhotosForSection(sectionKey) {
      const [categoryRaw, ...processParts] = String(sectionKey || photoSectionKey(state.activePhotoCategory, state.activeProcessName)).split("::");
      const category = normalizePhotoCategory(categoryRaw);
      const processName = processParts.join("::");
      return photosForSection(category, processName)
        .filter((photo) => state.selectedPrintPhotos[printSelectionKey(category, photo.id)])
        .map((photo) => ({ category, photoId: String(photo.id || ""), photoUuid: String(photo.photo_uuid || "") }))
        .filter((item) => item.photoId);
    }

    let bulkDeletePending = false;
    async function deleteSelectedPhotos(sectionKey) {
      if (bulkDeletePending) return;
      const selected = selectedPhotosForSection(sectionKey);
      if (!selected.length) {
        showNotice("请先选择要删除的照片。", true);
        return;
      }
      if (!state.auth.user) {
        showNotice("请先登录后再删除照片。", true);
        return;
      }
      if (!window.confirm(`确定删除已选 ${selected.length} 张照片吗？`)) return;
      const safetyPassword = prompt("请输入删除安全密码");
      if (safetyPassword === null) return;
      if (!safetyPassword.trim()) {
        showNotice("请输入删除安全密码。", true);
        return;
      }
      const sourceCode = state.selectedCode;
      const sourceContext = navigationContext();
      let latestPhotos = state.photos;
      // Older imports may lack UUID: delete backwards to avoid renumbered IDs.
      const ordered = [...selected].reverse();
      bulkDeletePending = true;
      let completed = 0;
      const deleteButton = $("#deleteSelectedCurrentPhotosBtn");
      if (deleteButton) deleteButton.disabled = true;
      try {
      for (const item of ordered) {
        if (state.selectedCode !== sourceCode || navigationContext() !== sourceContext) throw new Error("当前工程或单元已切换，已停止剩余删除。");
        const current = item.photoUuid ? latestPhotos.find((photo) => String(photo.photo_uuid || "") === item.photoUuid) : latestPhotos.find((photo) => String(photo.id) === item.photoId && normalizePhotoCategory(photo.category) === item.category);
        if (!current) throw new Error("待删除照片已发生变化，请刷新后重新选择。");
        const data = await apiJson(`/api/delete-photo/${encodeURIComponent(sourceCode)}/${encodeURIComponent(current.id)}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ category: item.category, safety_password: safetyPassword, photo_uuid: item.photoUuid })
        });
        if (!data.deleted) throw new Error("照片未删除，请刷新后核实，避免误删其它照片。");
        latestPhotos = data.photos || latestPhotos;
        completed += 1;
      }
      if (state.selectedCode !== sourceCode || navigationContext() !== sourceContext) return;
      state.photos = latestPhotos || [];
      clearPhotoSelection(false);
      renderPhotos();
      scheduleSummaryRefresh();
      showNotice(`已删除 ${selected.length} 张照片。`);
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
    }

    async function deletePhoto(category, photoId) {
      if (!state.auth.user) {
        showNotice("请先登录后再删除照片。", true);
        return;
      }
      const safetyPassword = prompt("请输入删除安全密码");
      if (safetyPassword === null) return;
      if (!safetyPassword.trim()) {
        showNotice("请输入删除安全密码。", true);
        return;
      }
      const data = await apiJson(`/api/delete-photo/${encodeURIComponent(state.selectedCode)}/${encodeURIComponent(photoId)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ category, safety_password: safetyPassword })
      });
      state.photos = data.photos || [];
      renderPhotos();
      scheduleSummaryRefresh();
      showNotice("照片已删除，编号已自动更新。");
    }

    async function reorderPhoto(category, photoId, direction) {
      if (!state.auth.user) {
        showNotice("请先登录后再调整照片排序。", true);
        return;
      }
      const sourceCode = state.selectedCode;
      const sourceContext = navigationContext();
      const data = await apiJson(`/api/photos/${encodeURIComponent(sourceCode)}/reorder`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ category, photo_id: photoId, direction })
      });
      if (state.selectedCode === sourceCode && navigationContext() === sourceContext) {
        state.photos = data.photos || [];
        renderPhotos();
      }
      try {
        await renumberCategory(category, sourceCode, sourceContext);
      } catch (error) {
        showNotice("顺序已保存，但编号更新失败：" + error.message, true);
        return;
      }
      showNotice("照片顺序已调整，编号已自动更新。");
    }

    async function saveDraggedPhotoOrder(list, category) {
      if (!state.auth.user) {
        showNotice("请先登录后再拖拽排序。", true);
        renderPhotos();
        return;
      }
      const visibleIds = Array.from(list.querySelectorAll(".photo[data-photo-id]")).map((item) => item.dataset.photoId).filter(Boolean);
      const visible = new Set(visibleIds);
      const section = list.closest(".photo-section");
      const orderedIds = visibleIds.concat(photosForSection(category, section?.dataset.processName || "").map((photo) => String(photo.id)).filter((id) => !visible.has(id)));
      const sourceCode = state.selectedCode;
      const sourceContext = navigationContext();
      const data = await apiJson(`/api/photos/${encodeURIComponent(sourceCode)}/reorder-list`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ category, ordered_ids: orderedIds, renumber: true })
      });
      if (state.selectedCode === sourceCode && navigationContext() === sourceContext) {
        state.photos = data.photos || [];
        renderPhotos();
      }
      showNotice("拖拽排序已保存，编号已自动更新。");
    }

    async function renumberCategory(category, sourceCode = state.selectedCode, sourceContext = navigationContext()) {
      const data = await apiJson(`/api/photos/${encodeURIComponent(sourceCode)}/renumber`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ category })
      });
      if (state.selectedCode !== sourceCode || navigationContext() !== sourceContext) return;
      state.photos = data.photos || [];
      state.selectedPrintPhotos = {};
      renderPhotos();
    }

    function initPhotoDragSort(host) {
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

    // 首屏冷启动加载动画：进度条跟随真实加载阶段推进；加载再快也保证至少显示 1.6 秒走完，页面数据全部显示才消失
    const BOOT_MIN_MS = 1200;
    let bootStartedAt = 0;
    function bootShow() {
      const loader = $("#bootLoader");
      if (loader) loader.classList.remove("boot-loader-hidden");
    }
    function bootHide() {
      const loader = $("#bootLoader");
      if (loader) loader.classList.add("boot-loader-hidden");
    }
    function bootStart() {
      bootStartedAt = Date.now();
    }
    function bootProgress(percent) {
      const fill = $("#bootLoaderFill");
      const num = $("#bootLoaderPercent");
      if (!fill) return;
      const target = Math.min(100, Math.max(0, Number(percent) || 0));
      fill.style.width = `${target}%`;
      if (num) num.textContent = String(Math.round(target));
    }
    function bootDone() {
      // 平滑到 100%；若加载过快则等待满最小时长，保证进度条可见
      const elapsed = Date.now() - (bootStartedAt || Date.now());
      const wait = Math.max(0, BOOT_MIN_MS - elapsed);
      bootProgress(100);
      setTimeout(() => {
        const loader = $("#bootLoader");
        if (!loader) return;
        loader.classList.add("is-done");
        setTimeout(() => loader.remove(), 500);
      }, wait + 150);
    }

    async function loadBootstrap(options = {}) {
      const skipOtherImages = Boolean(options.skipOtherImages);
      const context = navigationContext();
      if (!options.silent) bootStart();
      const data = await apiJson("/api/bootstrap");
      if (options.silent && context !== navigationContext()) return;
      state.auth.user = data.user || null;
      renderAuth();
      if (!state.auth.user) {
        // 未登录：登录页不显示加载遮罩，直接回填账号后保持隐藏
        bootHide();
        restoreLoginCredentials();
        return;
      }
      // 已登录：进入工作台才显示加载进度
      if (!options.silent) bootShow();
      bootProgress(8);
      state.revision = Number(data.revision || 0);
      if (data.app_version && $("#appVersionBadge")) $("#appVersionBadge").textContent = "v" + data.app_version.replace(/^A\d{8}-/, "");
      state.projectInfo = data.project_info || {};
      state.engineeringProjects = data.engineering_projects || [];
      // 删除工程后 active 可能失效：若返回的 active_id 不在当前工程列表里，回退到第一个工程，避免顶部残留已删工程名
      const serverActiveId = data.active_engineering_project_id || "";
      const activeStillValid = (data.engineering_projects || []).some((p) => p.id === serverActiveId);
      state.activeEngineeringProjectId = activeStillValid ? serverActiveId : (data.engineering_projects?.[0]?.id || "");
      state.hierarchy = data.hierarchy || [];
      state.projects = [];
      state.allProjectsLoaded = false;
      state.dashboard = data.dashboard || {};
      state.optimizationStatus = data.optimization_status || {};
      state.engineeringSettings = data.settings || {};
      state.printPageSize = Number(state.engineeringSettings.print_page_size || 4);
      state.treeRoot = buildTreeFromHierarchy(state.hierarchy);
      expandAdaptiveTree();
      // 渲染工程树是同步阻塞（单元多时耗时），先推到 85%，阻塞期间进度条动画持续
      bootProgress(85);
      renderEngineeringProjectSelect();
      renderTree();
      renderProjectInfo();
      renderOverview();
      if (skipOtherImages) {
        // 主界面已渲染：进度到 100% 并显示工程页面；其它影像后台静默补充
        bootProgress(100);
        bootDone();
        const idleLoadOtherImages = () => apiJson("/api/other-images/tree").then((otherImagesData) => {
          state.otherImages = otherImagesData.tree || { nodes: [], photo_count: 0 };
          renderOtherImagesTree();
          renderOverview();
        }).catch((error) => showNotice(error.message, true));
        if ("requestIdleCallback" in window) requestIdleCallback(idleLoadOtherImages, { timeout: 1500 });
        else setTimeout(idleLoadOtherImages, 50);
      } else {
        const otherImagesData = await apiJson("/api/other-images/tree");
        state.otherImages = otherImagesData.tree || { nodes: [], photo_count: 0 };
        renderOtherImagesTree();
        renderOverview();
        bootProgress(100);
        bootDone();
      }
      if (state.selectedPart) {
        const updated = findNode(state.treeRoot, state.selectedPart.key);
        if (updated) {
          // 保留原 part 对象(含已加载的单元列表 projects)，避免重载后列表被清空
          state.selectedPart.name = updated.name;
          state.selectedPart.code = updated.code;
          state.selectedPart.key = updated.key;
          state.selectedPart.partKey = updated.partKey;
          if (state.viewMode === "part") renderPart();
        } else {
          state.selectedPart = null;
          if (state.viewMode === "part") {
            setView("overview");
            renderOverview();
          }
        }
      }
    }

    let summaryRefreshTimer = 0;
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
    }

    async function ensureAllProjectsLoaded() {
      if (state.allProjectsLoaded) return;
      const data = await apiJson("/api/projects?slim=1");
      state.projects = data.projects || [];
      state.allProjectsLoaded = true;
      // 保留 bootstrap 构建的节点和 partKey，同时把完整单元列表挂回原节点。
      // 批量打印、单位选择器和分部页因此共用同一份完整数据，不再出现“0 个”。
      if (!state.treeRoot?.children?.length && state.projects.length) {
        state.treeRoot = buildTree(state.projects);
        expandAdaptiveTree();
      } else {
        hydrateTreeProjects(state.treeRoot, state.projects);
      }
      renderTree();
      renderOverview();
    }

    let lastAutoRefreshAt = Date.now();
    function anyUploadFormOpen() {
      return Array.from(document.querySelectorAll(".photo-upload-form")).some((form) => form.style.display !== "none");
    }
    async function fullRefresh(options = {}) {
      await refreshAll(options);
      if (state.selectedCode && !anyUploadFormOpen() && (state.viewMode === "part" || state.viewMode === "unit")) {
        const refreshed = await apiJson(`/api/photos/${encodeURIComponent(state.selectedCode)}`);
        state.photos = refreshed.photos || state.photos;
        renderPhotos();
      }
      if (!options.silent) showNotice("数据已刷新");
    }
    $("#refreshBtn").addEventListener("click", () => fullRefresh().catch((error) => showNotice(error.message, true)));
    function autoRefreshSilently() {
      const now = Date.now();
      if (now - lastAutoRefreshAt < 15000) return;
      lastAutoRefreshAt = now;
      apiJson("/api/revision").then((data) => {
        if (!data.authenticated) return;
        if (Number(data.revision || 0) !== Number(state.revision || 0)) return fullRefresh({ silent: true });
      }).catch(() => {});
    }
    window.addEventListener("focus", autoRefreshSilently);
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") autoRefreshSilently();
    });
    function setSupportTab(tab) {
      const nextTab = tab || "poster";
      document.querySelectorAll("[data-support-tab]").forEach((button) => {
        button.classList.toggle("active", button.dataset.supportTab === nextTab);
      });
      document.querySelectorAll("[data-support-panel]").forEach((panel) => {
        panel.classList.toggle("active", panel.dataset.supportPanel === nextTab);
      });
    }

    $("#supportBtn").addEventListener("click", (event) => {
      event.stopPropagation();
      closeTopMenus("supportPanel");
      $("#supportPanel").classList.toggle("open");
      $("#supportPanel").setAttribute("aria-hidden", $("#supportPanel").classList.contains("open") ? "false" : "true");
      if ($("#supportPanel").classList.contains("open")) {
        setSupportTab("status");
        loadProductConfig().catch(() => {});
        loadSharePoints().catch((error) => showNotice(error.message, true));
      }
    });
    document.querySelectorAll("[data-support-tab]").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.stopPropagation();
        setSupportTab(button.dataset.supportTab);
      });
    });
    document.addEventListener("click", (event) => {
      if (!$("#supportPanel")?.classList.contains("is-settings-embedded") && !event.target.closest(".support-wrap")) {
        $("#supportPanel").classList.remove("open");
        $("#supportPanel").setAttribute("aria-hidden", "true");
      }
    });

    function renderInviteProgress(inv) {
      if (!inv) return;
      // 未登录时不显示邀请进度
      if (!inv.logged_in) {
        const codeEl = $("#inviteCodeDisplay");
        if (codeEl) codeEl.textContent = "登录后查看";
        const remainEl = $("#inviteProgressRemain");
        if (remainEl) remainEl.textContent = "请先登录云账号，再查看邀请进度";
        return;
      }
      const code = inv.invite_code || "—";
      const registered = Number(inv.registered_count || 0);
      const qualified = Number(inv.qualified_count || 0);
      const pending = Number(inv.pending_count || 0);
      const milestone = Number(inv.milestone || 10);
      const remain = Math.max(0, milestone - (qualified % milestone));
      const reward = Number(inv.reward_months || 0);
      const inMilestone = qualified % milestone;
      const pct = Math.min(100, (inMilestone / milestone) * 100);
      if ($("#inviteCodeDisplay")) $("#inviteCodeDisplay").textContent = code;
      if ($("#inviteProgressText")) $("#inviteProgressText").textContent = `有效邀请 ${qualified} 人（待确认 ${pending} 人）`;
      if ($("#inviteProgressRemain")) $("#inviteProgressRemain").textContent = `还差 ${remain} 个有效邀请即可获得下一次奖励`;
      if ($("#inviteProgressBar")) $("#inviteProgressBar").style.width = pct + "%";
      if ($("#inviteRewardInfo")) $("#inviteRewardInfo").textContent = `已通过邀请免费获得 ${reward} 个月使用`;
    }

    function formatDateText(value) {
      if (!value) return "";
      return String(value).slice(0, 10);
    }

    function renderSupportLicense(license) {
      const box = $("#supportLicenseStatus");
      if (!box) return;
      const trialExpiry = formatDateText(license.trial_expires_at);
      const licenseExpiry = formatDateText(license.expires_at);
      let mainText = "未读取到软件到期时间";
      let subText = "请稍后重新打开免费使用面板。";
      if (license.ok) {
        mainText = license.is_lifetime
          ? `软件状态：终身授权${license.owner ? `（${license.owner}）` : ""}`
          : `软件授权到期时间：${licenseExpiry || "未设置"}`;
        subText = license.machine_id ? `机器ID：${license.machine_id}` : "授权已生效。";
      } else if (license.free_forever) {
        mainText = "免费版：永久免费";
        subText = `已使用 ${license.photo_count || 0} / ${license.free_photo_limit || 300} 张，可正常打印和导出，无产品水印。`;
      } else if (license.upload_locked) {
        mainText = "软件试用已到期";
        subText = trialExpiry ? `试用到期时间：${trialExpiry}，请联系管理员继续使用。` : "请联系管理员继续使用。";
      } else {
        mainText = `软件试用到期时间：${trialExpiry || "未读取到"}`;
        subText = `剩余 ${license.trial_remaining || 0} 天，可通过分享积分兑换使用时长。`;
      }
      box.innerHTML = `${escapeHtml(mainText)}<small>${escapeHtml(subText)}</small>`;
    }

    async function loadProductConfig() {
      const data = await apiJson("/api/cloud/product-config");
      const product = data.product || {};
      const pricing = product.pricing || {};
      const free = product.free || {};
      const invite = product.invite || {};
      const label = pricing.price_label || "内测会员价";
      const monthly = Number(pricing.monthly_price || 15);
      const lifetime = Number(pricing.lifetime_price || 169);
      const setText = (id, value) => { const node = $(id); if (node) node.textContent = value; };
      setText("#pricingLabel", `会员收费标准（${label}）：`);
      setText("#monthlyPriceText", monthly);
      setText("#monthlyPricePaymentText", monthly);
      setText("#lifetimePriceText", lifetime);
      setText("#lifetimePricePaymentText", lifetime);
      setText("#freePhotoLimitText", Number(free.photo_limit || 300));
      setText("#inviteMilestoneText", Number(invite.milestone || 10));
      setText("#inviteRewardDaysText", Number(invite.reward_days || 30));
      return product;
    }

    async function loadSharePoints() {
      const [licenseData, cloudData] = await Promise.all([
        apiJson("/api/license/status"),
        apiJson("/api/cloud/status").catch(() => ({ ok: false }))
      ]);
      renderSupportLicense(licenseData.license || {});
      renderCloudAccount(cloudData || {});
      if (cloudData && cloudData.logged_in) {
        await loadWechatBinding().catch((error) => renderWechatBinding({ error: error.message || "读取失败" }, true));
      }
      // 邀请进度
      try {
        const inv = await apiJson("/api/cloud/invite-status").catch(() => ({}));
        renderInviteProgress(Object.assign({ logged_in: !!(cloudData && cloudData.logged_in) }, inv));
      } catch (e) { /* 忽略 */ }
    }

    function renderCloudAccount(data) {
      const box = $("#cloudAccountStatus");
      const form = $("#cloudLoginForm");
      const logoutBtn = $("#cloudLogoutBtn");
      if (!box) return;
      if (data && data.logged_in && data.account) {
        const tier = data.is_member ? (data.license && data.license.is_lifetime ? "终身会员" : "会员") : "免费版";
        box.innerHTML = `<strong style="color:#1a7a3a">${escapeHtml(data.account)}</strong>（${tier}）`;
        form.style.display = "none";
        logoutBtn.style.display = "block";
        renderProjectOwnership(data.project_ownership || {});
        renderWechatBinding({}, true);
      } else {
        box.textContent = "未登录";
        form.style.display = "block";
        logoutBtn.style.display = "none";
        renderProjectOwnership({ state: "logged_out" });
        renderWechatBinding({}, false);
      }
    }

    function renderProjectOwnership(ownership) {
      const target = $("#cloudProjectOwnershipBox");
      if (!target) return;
      const stateName = String(ownership && ownership.state || "logged_out");
      if (stateName === "logged_out") {
        target.style.display = "none";
        target.innerHTML = "";
        return;
      }
      const projectName = escapeHtml(ownership.project_name || "当前本地工程");
      target.style.display = "block";
      if (stateName === "matched") {
        target.style.background = "#eaf7ef";
        target.style.color = "#176a38";
        target.innerHTML = `<strong>工程账号归属：</strong>${projectName}<br><small>已绑定当前云账号，手机与这台电脑会自动同步。</small>`;
        return;
      }
      if (stateName === "mismatch") {
        const owner = escapeHtml(ownership.owner_username || "另一账号");
        target.style.background = "#fff0ee";
        target.style.color = "#9c2f24";
        target.innerHTML = `<strong>已阻止串号：</strong>${projectName}<br><small>本地工程属于账号 ${owner}，当前账号不能上传或接收该工程影像。</small>`;
        return;
      }
      target.style.background = "#fff8e6";
      target.style.color = "#7a5510";
      target.innerHTML = `<strong>还差最后一步：</strong>${projectName}<br><small>确认后，手机登录同一账号即可自动拉取工程并把原图送回这台电脑。</small><button type="button" id="claimCloudProjectBtn" style="display:block;margin-top:8px;">绑定当前工程到此账号</button>`;
      $("#claimCloudProjectBtn")?.addEventListener("click", () => claimCloudProjectOwnership(ownership));
      maybePromptProjectClaim(ownership);
    }

    function maybePromptProjectClaim(ownership) {
      if (!ownership || !ownership.can_claim) return;
      const key = `engineering-image:ownership-prompt:${ownership.account_id || "account"}:${ownership.project_id || "project"}`;
      if (sessionStorage.getItem(key)) return;
      sessionStorage.setItem(key, "1");
      setTimeout(() => {
        if (window.confirm(`是否把本机工程“${ownership.project_name || "当前工程"}”绑定到刚登录的云账号？\n\n绑定后，手机登录同一账号即可自动拉取工程；为防串号，绑定后不能静默改给其它账号。`)) {
          claimCloudProjectOwnership(ownership).catch((error) => showNotice(error.message || "绑定失败", true));
        }
      }, 80);
    }

    async function claimCloudProjectOwnership(ownership) {
      const button = $("#claimCloudProjectBtn");
      if (button) button.disabled = true;
      try {
        const data = await apiJson("/api/cloud/project-ownership", { method: "POST" });
        if (!data.ok) throw new Error(data.error || "绑定失败");
        renderProjectOwnership(data.project_ownership || {});
        showNotice("当前工程已与云账号绑定，正在同步到手机。");
        apiJson("/api/mobile-sync/run", { method: "POST" }).catch(() => {});
      } finally {
        if (button && button.isConnected) button.disabled = false;
      }
    }

    function renderWechatBinding(data, loggedIn = true) {
      const wrapper = $("#wechatBindingBox");
      const status = $("#wechatBindingStatus");
      const unbind = $("#wechatUnbindBtn");
      if (!wrapper || !status || !unbind) return;
      if (!loggedIn) {
        wrapper.style.display = "none";
        status.textContent = "";
        unbind.style.display = "none";
        return;
      }
      wrapper.style.display = "block";
      if (data.error) {
        status.textContent = `检查失败：${data.error}`;
        unbind.style.display = "none";
      } else if (data.bound) {
        const lastLogin = String(data.binding && data.binding.last_login_at || "").slice(0, 16).replace("T", " ");
        status.textContent = lastLogin ? `已绑定，手机最近登录 ${lastLogin}` : "已绑定当前微信";
        unbind.style.display = "block";
      } else if (Object.prototype.hasOwnProperty.call(data, "bound")) {
        status.textContent = "尚未绑定；手机首次登录时输入这个桌面账号即可";
        unbind.style.display = "none";
      } else {
        status.textContent = "正在检查…";
        unbind.style.display = "none";
      }
    }

    async function loadWechatBinding() {
      const data = await apiJson("/api/cloud/wechat-binding");
      if (!data.ok) throw new Error(data.error || "读取微信绑定失败");
      renderWechatBinding(data, true);
      return data;
    }

    const SOFTWARE_SHARE_URL = "https://wwbro.lanzouu.com/b00l2vsyqj";
    const SOFTWARE_SHARE_PASSWORD = "djjp";

    async function sharePoster() {
      const text = `工程影像管理平台下载链接：${SOFTWARE_SHARE_URL}\n密码：${SOFTWARE_SHARE_PASSWORD}`;
      if (navigator.share) {
        await navigator.share({ title: "工程影像管理平台下载", text, url: SOFTWARE_SHARE_URL });
        return;
      }
      await copyText(text);
      showNotice("软件下载链接和密码已复制，可以直接粘贴发送。");
    }

    $("#sharePosterBtn").addEventListener("click", () => {
      sharePoster().catch((error) => {
        if (error.name !== "AbortError") showNotice(error.message || "分享失败", true);
      });
    });

    $("#copyInviteCodeBtn").addEventListener("click", async () => {
      const code = $("#inviteCodeDisplay") ? $("#inviteCodeDisplay").textContent : "";
      if (!code || code.includes("—") || code.includes("登录")) {
        showNotice("请先登录云账号，再复制邀请码。", true);
        return;
      }
      await copyText(code);
      showNotice("邀请码已复制；好友注册并首次登录软件后会计为有效邀请。");
    });
    $("#engineeringProjectSelect").addEventListener("change", (event) => {
      setActiveEngineeringProject(event.target.value).catch((error) => showNotice(error.message, true));
    });
    $("#newEngineeringProjectBtn")?.addEventListener("click", openNewEngineeringProjectModal);
    $("#closeNewEngineeringProjectBtn")?.addEventListener("click", closeNewEngineeringProjectModal);
    $("#cancelNewEngineeringProjectBtn")?.addEventListener("click", closeNewEngineeringProjectModal);
    $("#newEngineeringProjectForm")?.addEventListener("submit", (event) => {
      createEngineeringProject(event).catch((error) => showNotice(error.message || "新建工程失败", true));
    });
    $("#newEngineeringProjectModal")?.addEventListener("click", (event) => {
      if (event.target.id === "newEngineeringProjectModal") closeNewEngineeringProjectModal();
    });
    $("#projectInfoBtn")?.addEventListener("click", openProjectInfoModal);
    $("#closeProjectInfoBtn").addEventListener("click", closeProjectInfoModal);
    $("#cancelProjectInfoBtn").addEventListener("click", closeProjectInfoModal);
    $("#projectInfoForm").addEventListener("submit", (event) => {
      saveProjectInfo(event).catch((error) => showNotice(error.message, true));
    });
    $("#projectInfoIndustryInput")?.addEventListener("change", () => refreshProfessionalProjectTypes("").catch(() => {}));
    $("#projectInfoProjectTypeInput")?.addEventListener("change", () => refreshProfessionalPlanSummary().catch(() => {}));
    $("#openProfessionalPlanBtn")?.addEventListener("click", () => {
      const industry = $("#projectInfoIndustryInput")?.value || "水利工程";
      const projectType = $("#projectInfoProjectTypeInput")?.value || "";
      window.open(`/professional-plan?industry=${encodeURIComponent(industry)}&project_type=${encodeURIComponent(projectType)}`, "_blank");
    });
    $("#deleteEngineeringProjectBtn").addEventListener("click", () => {
      deleteCurrentEngineeringProject().catch((error) => showNotice(error.message, true));
    });
    document.querySelectorAll("[data-project-settings-tab]").forEach((button) => {
      button.addEventListener("click", () => setProjectSettingsTab(button.dataset.projectSettingsTab));
    });
    $("#refreshProjectMembersBtn")?.addEventListener("click", () => {
      loadProjectMembers().catch((error) => showNotice(error.message || "成员读取失败", true));
    });
    $("#createProjectInviteBtn")?.addEventListener("click", () => {
      createProjectInvite().catch((error) => showNotice(error.message || "邀请码生成失败", true));
    });
    $("#copyProjectInviteBtn")?.addEventListener("click", () => {
      const code = String(state.latestProjectInvite?.code || $("#projectInviteCode")?.textContent || "").trim();
      if (!code || code === "—") {
        showNotice("请先生成邀请码。", true);
        return;
      }
      copyText(code)
        .then(() => showNotice("项目邀请码已复制。"))
        .catch((error) => showNotice(error.message || "复制失败", true));
    });
    $("#projectMembersList")?.addEventListener("change", (event) => {
      const select = event.target.closest("[data-project-member-role]");
      if (!select) return;
      updateProjectMemberRole(select.dataset.projectMemberRole, select.value, select)
        .catch((error) => showNotice(error.message || "角色更新失败", true));
    });
    $("#projectMembersList")?.addEventListener("click", (event) => {
      const button = event.target.closest("[data-project-member-remove]");
      if (!button) return;
      removeProjectMember(
        button.dataset.projectMemberRemove,
        button.dataset.projectMemberName,
        button
      ).catch((error) => showNotice(error.message || "移除失败", true));
    });
    $("#projectInvitesList")?.addEventListener("click", (event) => {
      const button = event.target.closest("[data-project-invite-revoke]");
      if (!button) return;
      revokeProjectInvite(button.dataset.projectInviteRevoke, button)
        .catch((error) => showNotice(error.message || "撤销失败", true));
    });
    $("#settingsPrintPhotoPresetInput").addEventListener("change", syncPrintPhotoPresetInputs);
    $("#closeFolderReviewBtn").addEventListener("click", closeFolderReview);
    $("#cancelFolderReviewBtn").addEventListener("click", closeFolderReview);
    $("#confirmFolderReviewBtn").addEventListener("click", () => commitFolderReview().catch((error) => showNotice(error.message, true)));
    $("#folderReviewModal").addEventListener("click", (event) => {
      if (event.target.id === "folderReviewModal") closeFolderReview();
    });
    $("#projectInfoModal").addEventListener("click", (event) => {
      if (event.target.id === "projectInfoModal") closeProjectInfoModal();
    });
    if ($("#numberingRulesBtn")) $("#numberingRulesBtn").addEventListener("click", () => openNumberingRulesModal().catch((error) => showNotice(error.message, true)));
    if ($("#closeNumberingRulesBtn")) $("#closeNumberingRulesBtn").addEventListener("click", closeNumberingRulesModal);
    if ($("#cancelNumberingRulesBtn")) $("#cancelNumberingRulesBtn").addEventListener("click", closeNumberingRulesModal);
    if ($("#numberingRulesForm")) $("#numberingRulesForm").addEventListener("submit", (event) => {
      saveNumberingRules(event).catch((error) => showNotice(error.message, true));
    });
    if ($("#numberingRulesModal")) $("#numberingRulesModal").addEventListener("click", (event) => {
      if (event.target.id === "numberingRulesModal") closeNumberingRulesModal();
    });
    $("#setupPageBtn").addEventListener("click", () => window.open("/setup", "_blank"));
    $("#checkUpdateBtn").addEventListener("click", () => checkForUpdate(true).catch((error) => showNotice(error.message, true)));
    $("#dismissUpdateBtn").addEventListener("click", closeManualUpdate);
    $("#machineIdBtn").addEventListener("click", () => openMachineIdModal().catch((error) => showNotice(error.message, true)));
    $("#gateMachineIdBtn")?.addEventListener("click", () => openMachineIdModal().catch((error) => showNotice(error.message, true)));
    $("#closeMachineIdBtn").addEventListener("click", closeMachineIdModal);
    $("#copyMachineIdBtn").addEventListener("click", () => copyMachineId().catch((error) => showNotice(error.message, true)));
    $("#openLicensePageBtn").addEventListener("click", () => window.open("https://shuiliyingxiang.cn/member", "_blank", "noopener"));
    $("#machineIdModal").addEventListener("click", (event) => {
      if (event.target.id === "machineIdModal") closeMachineIdModal();
    });
    $("#sideConstructionBtn").addEventListener("click", () => openOverview("construction"));
    $("#sideOtherBtn").addEventListener("click", () => openOverview("other"));
    $("#topConstructionBtn").addEventListener("click", () => openOverview("construction"));
    $("#topOtherBtn").addEventListener("click", () => openOverview("other"));
    $("#treeLevelFilter").addEventListener("change", (event) => {
      state.treeLevelFilter = event.target.value;
      renderTreeLevelButtons();
      renderTree();
    });
    document.querySelectorAll("[data-tree-level]").forEach((button) => {
      button.addEventListener("click", () => {
        state.treeLevelFilter = button.dataset.treeLevel || "all";
        $("#treeLevelFilter").value = state.treeLevelFilter;
        renderTreeLevelButtons();
        renderTree();
      });
    });
    document.querySelectorAll("[data-top-tree-level]").forEach((button) => {
      button.addEventListener("click", () => {
        state.treeLevelFilter = button.dataset.topTreeLevel || "all";
        $("#treeLevelFilter").value = state.treeLevelFilter;
        renderTreeLevelButtons();
        renderTree();
      });
    });
    $("#addOtherRootBtn").addEventListener("click", () => openOtherImageModal(""));
    $("#otherImageForm").addEventListener("submit", (event) => {
      submitOtherImage(event).catch((error) => showNotice(error.message, true));
    });
    $("#closeOtherImageBtn").addEventListener("click", closeOtherImageModal);
    $("#cancelOtherImageBtn").addEventListener("click", closeOtherImageModal);
    $("#otherImageModal").addEventListener("click", (event) => {
      if (event.target.id === "otherImageModal") closeOtherImageModal();
    });
    $("#gateLoginBtn").addEventListener("click", () => submitAuth("/api/cloud/login").catch((error) => showNotice(error.message, true)));
    $("#gateStaffEnterBtn")?.addEventListener("click", () => submitProjectStaffEntry().catch((error) => showNotice(error.message || "项目人员进入失败", true)));
    // 输入即记住账号密码，未登录回填
    ["gateUsername", "gatePassword"].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.addEventListener("input", () => saveLoginCredentials($("#gateUsername")?.value, $("#gatePassword")?.value));
    });
    $("#cloudLoginBtn").addEventListener("click", async () => {
      const user = $("#cloudUser").value.trim();
      const pass = $("#cloudPass").value;
      if (!user || !pass) { showNotice("请输入账号和密码", true); return; }
      try {
        const data = await apiJson("/api/cloud/login", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ username: user, password: pass })
        });
        if (!data.ok) { showNotice(data.error || "登录失败", true); return; }
        $("#cloudUser").value = ""; $("#cloudPass").value = "";
        showNotice("云账号登录成功");
        loadSharePoints();
      } catch (e) { showNotice(e.message || "登录失败", true); }
    });
    $("#cloudRegBtn").addEventListener("click", () => {
      window.open("https://shuiliyingxiang.cn/member#register", "_blank", "noopener");
    });
    $("#cloudLogoutBtn").addEventListener("click", async () => {
      try { await apiJson("/api/cloud/logout", { method: "POST" }); } catch (e) {}
      showNotice("已退出云账号");
      loadSharePoints();
    });
    $("#wechatUnbindBtn")?.addEventListener("click", async () => {
      const password = window.prompt("请输入当前桌面账号的登录密码，确认解绑微信：");
      if (password === null) return;
      if (!password) { showNotice("请输入账号密码", true); return; }
      if (!window.confirm("解绑后，这台手机上的旧登录会立即失效；未上传原图仍保留在原账号独立队列。确定继续吗？")) return;
      const button = $("#wechatUnbindBtn");
      if (button) button.disabled = true;
      try {
        const data = await apiJson("/api/cloud/wechat-binding", {
          method: "DELETE",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ password })
        });
        if (!data.ok) throw new Error(data.error || "解绑失败");
        showNotice(data.message || "微信已解绑，旧手机登录已立即失效");
        await loadWechatBinding();
      } catch (error) {
        showNotice(error.message || "解绑失败", true);
      } finally {
        if (button) button.disabled = false;
      }
    });
    ["gateUsername", "gatePassword"].forEach((id) => {
      $(`#${id}`)?.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          submitAuth("/api/cloud/login").catch((error) => showNotice(error.message, true));
        }
      });
    });
    $("#gateTogglePass")?.addEventListener("click", () => {
      const input = $("#gatePassword");
      if (!input) return;
      const show = input.type === "password";
      input.type = show ? "text" : "password";
      $("#gateTogglePass").textContent = show ? "隐藏" : "显示";
    });
    $("#logoutBtn").addEventListener("click", async () => {
      try { await apiJson("/api/cloud/logout", { method: "POST" }); } catch (error) {}
      await apiJson("/api/auth/logout", { method: "POST" });
      state.auth.user = null;
      renderAuth();
      showNotice("已退出账号。");
    });
    $("#topOverviewBtn")?.addEventListener("click", () => openOverview("construction"));
    $("#constructionOverviewBtn")?.addEventListener("click", () => openOverview("construction"));
    $("#otherOverviewBtn")?.addEventListener("click", () => openOverview("other"));
    function setProjectImportMenu(open) {
      const menu = $("#projectImportMenu");
      const button = $("#projectImportMenuBtn");
      if (menu?.classList.contains("settings-static-menu")) {
        menu.classList.add("open");
        menu.setAttribute("aria-hidden", "false");
        button?.setAttribute("aria-expanded", "true");
        return;
      }
      const isOpen = Boolean(open);
      menu?.classList.toggle("open", isOpen);
      menu?.setAttribute("aria-hidden", isOpen ? "false" : "true");
      button?.setAttribute("aria-expanded", isOpen ? "true" : "false");
    }
    function closeTopMenus(except) {
      const menus = {
        printMenu: $("#printMenu"),
        settingsMenu: $("#settingsMenu"),
        actionsMenu: $("#actionsMenu"),
        quickMenu: $("#quickMenu"),
        projectImportMenu: $("#projectImportMenu"),
        supportPanel: $("#supportPanel"),
      };
      Object.entries(menus).forEach(([name, el]) => {
        if (!el) return;
        if (name === except) return;
        if (name === "projectImportMenu") setProjectImportMenu(false);
        else if (name === "supportPanel" && el.classList.contains("is-settings-embedded")) return;
        else el.classList.remove("open");
      });
      if (except !== "supportPanel" && !$("#supportPanel")?.classList.contains("is-settings-embedded")) $("#supportPanel")?.setAttribute("aria-hidden", "true");
    }
    $("#printMenuBtn")?.addEventListener("click", (event) => {
      event.stopPropagation();
      closeTopMenus("printMenu");
      $("#printMenu")?.classList.toggle("open");
    });
    $("#settingsMenuBtn").addEventListener("click", (event) => {
      event.stopPropagation();
      closeTopMenus();
      openProjectInfoModal();
    });
    $("#actionsMenuBtn").addEventListener("click", (event) => {
      event.stopPropagation();
      closeTopMenus("actionsMenu");
      $("#actionsMenu").classList.toggle("open");
      $("#actionsMenuBtn").setAttribute("aria-expanded", $("#actionsMenu").classList.contains("open") ? "true" : "false");
    });
    $("#quickMenuBtn")?.addEventListener("click", (event) => {
      event.stopPropagation();
      closeTopMenus("quickMenu");
      $("#quickMenu")?.classList.toggle("open");
    });
    $("#projectImportMenuBtn").addEventListener("click", (event) => {
      event.stopPropagation();
      const willOpen = !$("#projectImportMenu").classList.contains("open");
      closeTopMenus("projectImportMenu");
      setProjectImportMenu(willOpen);
    });
    document.addEventListener("click", (event) => {
      if (!event.target.closest(".print-menu-wrap")) $("#printMenu")?.classList.remove("open");
      if (!event.target.closest(".settings-menu-wrap")) {
        $("#settingsMenu")?.classList.remove("open");
        $("#actionsMenu")?.classList.remove("open");
        $("#actionsMenuBtn")?.setAttribute("aria-expanded", "false");
      }
      if (!event.target.closest(".quick-menu-wrap")) $("#quickMenu")?.classList.remove("open");
      if (!event.target.closest(".project-import-wrap")) setProjectImportMenu(false);
    });
    document.querySelectorAll("#settingsMenu button").forEach((button) => {
      button.addEventListener("click", () => $("#settingsMenu")?.classList.remove("open"));
    });
    document.querySelectorAll("#actionsMenu button").forEach((button) => {
      button.addEventListener("click", () => $("#actionsMenu").classList.remove("open"));
    });
    document.querySelectorAll("#quickMenu button").forEach((button) => {
      button.addEventListener("click", () => $("#quickMenu")?.classList.remove("open"));
    });
    document.querySelectorAll("#projectImportMenu button").forEach((button) => {
      button.addEventListener("click", () => {
        if (!$("#projectImportMenu")?.classList.contains("settings-static-menu")) setProjectImportMenu(false);
      });
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") setProjectImportMenu(false);
    });
    document.addEventListener("keydown", (event) => {
      if (event.key !== "Escape") return;
      const layers = [
        ["#photoPreviewModal", closePhotoPreview],
        ["#photoMoveModal", closePhotoMoveModal],
        ["#photoEditModal", closePhotoEdit],
        ["#addProcessModal", closeAddProcessModal],
        ["#uploadChoiceModal", closeUploadChoiceModal],
        ["#projectInfoModal", closeProjectInfoModal],
        ["#batchPrintModal", closeBatchPrint]
      ];
      const active = layers.find(([selector]) => $(selector)?.classList.contains("open"));
      if (active) {
        event.preventDefault();
        active[1]();
        return;
      }
      $("#unitMoreMenu")?.classList.remove("open");
      $("#actionsMenu")?.classList.remove("open");
      $("#unitMoreMenuBtn")?.setAttribute("aria-expanded", "false");
      $("#actionsMenuBtn")?.setAttribute("aria-expanded", "false");
    });
    document.querySelectorAll("[data-open-batch-print]").forEach((button) => {
      button.addEventListener("click", () => {
        $("#printMenu")?.classList.remove("open");
        openBatchPrint(button.dataset.openBatchPrint, button.dataset.batchMode || "print");
      });
    });
    $("#closeBatchPrintBtn").addEventListener("click", closeBatchPrint);
    $("#batchCancelBtn").addEventListener("click", closeBatchPrint);
    $("#batchPrintSearch").addEventListener("input", renderBatchPrintPicker);
    $("#batchSelectVisibleBtn").addEventListener("click", selectVisibleBatchProjects);
    $("#batchClearBtn").addEventListener("click", () => {
      state.batchSelectedUnits.clear();
      state.batchSelectedProcesses.clear();
      state.batchSelectionOrder = [];
      renderBatchPrintPicker();
    });
    $("#batchPrintSubmitBtn").addEventListener("click", submitBatchPrint);
    $("#batchPrintModal").addEventListener("click", (event) => {
      if (event.target.id === "batchPrintModal") closeBatchPrint();
    });
    $("#batchPrintModal").addEventListener("wheel", (event) => {
      const modal = document.querySelector(".batch-print-modal");
      if (!$("#batchPrintModal").classList.contains("open") || !modal) return;
      if (modal.scrollHeight <= modal.clientHeight) return;
      event.preventDefault();
      modal.scrollTop += event.deltaY;
    }, { passive: false });
    $("#batchPrintModal").addEventListener("touchstart", (event) => {
      state.batchTouchY = event.touches?.[0]?.clientY || 0;
    }, { passive: true });
    $("#batchPrintModal").addEventListener("touchmove", (event) => {
      const modal = document.querySelector(".batch-print-modal");
      if (!$("#batchPrintModal").classList.contains("open") || !modal || !event.touches?.length) return;
      if (modal.scrollHeight <= modal.clientHeight) return;
      const y = event.touches[0].clientY;
      const delta = state.batchTouchY - y;
      state.batchTouchY = y;
      event.preventDefault();
      modal.scrollTop += delta;
    }, { passive: false });
    $("#closeProjectPickerBtn").addEventListener("click", closeProjectPicker);
    $("#projectPickerSearch").addEventListener("input", renderProjectPicker);
    $("#projectPickerModal").addEventListener("click", (event) => {
      if (event.target.id === "projectPickerModal") closeProjectPicker();
    });
    $("#closePhotoPreviewBtn").addEventListener("click", closePhotoPreview);
    $("#photoZoomOutBtn").addEventListener("click", () => zoomPhotoPreview(-0.15));
    $("#photoZoomInBtn").addEventListener("click", () => zoomPhotoPreview(0.15));
    $("#photoZoomFitBtn").addEventListener("click", fitPhotoPreview);
    $("#photoZoomActualBtn").addEventListener("click", () => {
      state.photoPreviewScale = 1;
      renderPhotoPreviewScale();
    });
    $(".photo-preview-body").addEventListener("wheel", (event) => {
      if (!$("#photoPreviewModal").classList.contains("open")) return;
      event.preventDefault();
      zoomPhotoPreview(event.deltaY > 0 ? -0.1 : 0.1);
    }, { passive: false });
    window.addEventListener("resize", () => {
      if ($("#photoPreviewModal").classList.contains("open")) fitPhotoPreview();
      if ($("#batchPrintModal").classList.contains("open")) resizeBatchPrintBody();
    });
    $("#photoPreviewModal").addEventListener("click", (event) => {
      if (event.target.id === "photoPreviewModal") closePhotoPreview();
    });
    $("#closePhotoEditBtn").addEventListener("click", closePhotoEdit);
    $("#cancelPhotoEditBtn").addEventListener("click", closePhotoEdit);
    $("#viewOriginalPhotoBtn").addEventListener("click", viewOriginalPhoto);
    $("#restoreOriginalPhotoBtn").addEventListener("click", () => replaceEditedPhotoFromStorage("restore-original").catch((error) => showNotice(error.message, true)));
    $("#optimizePhotoBtn").addEventListener("click", () => replaceEditedPhotoFromStorage("optimize").catch((error) => showNotice(error.message, true)));
    $("#startPhotoOptimizationBtn").addEventListener("click", () => controlPhotoOptimization("start").catch((error) => showNotice(error.message, true)));
    $("#pausePhotoOptimizationBtn").addEventListener("click", () => controlPhotoOptimization("pause").catch((error) => showNotice(error.message, true)));
    $("#photoEditForm").addEventListener("submit", (event) => {
      savePhotoEdit(event).catch((error) => showNotice(error.message, true));
    });
    $("#photoEditModal").addEventListener("click", (event) => {
      if (event.target.id === "photoEditModal") closePhotoEdit();
    });
    $("#globalUploadBtn").addEventListener("click", () => {
      openUploadChoiceModal(null, null, state.viewMode === "unit");
    });
    $("#closeUploadChoiceBtn").addEventListener("click", closeUploadChoiceModal);
    $("#uploadProjectSearch").addEventListener("input", renderUploadProjectPicker);
    $("#uploadProcessSelect")?.addEventListener("change", renderUploadTargetSummary);
    $("#uploadModalFiles").addEventListener("change", (event) => updateUploadModalFileSummary(event.target.files, true));
    $("#uploadModalForm").addEventListener("submit", (event) => {
      uploadFromModal(event).catch((error) => showNotice(error.message, true));
    });
    $("#uploadModalForm").addEventListener("paste", (event) => {
      const files = Array.from(event.clipboardData?.files || []);
      if (!files.length) return;
      event.preventDefault();
      updateUploadModalFileSummary(files, true);
    });
    $("#autoMatchUploadBtn").addEventListener("click", () => {
      uploadAutoMatchFromModal().catch((error) => showNotice(error.message, true));
    });
    let uploadModalDragDepth = 0;
    $("#uploadModalForm").addEventListener("dragenter", (event) => {
      event.preventDefault();
      event.stopPropagation();
      uploadModalDragDepth += 1;
      $("#uploadModalForm").classList.add("is-dragging");
    });
    $("#uploadModalForm").addEventListener("dragover", (event) => {
      event.preventDefault();
      event.stopPropagation();
      event.dataTransfer.dropEffect = "copy";
      $("#uploadModalForm").classList.add("is-dragging");
    });
    $("#uploadModalForm").addEventListener("dragleave", () => {
      uploadModalDragDepth = Math.max(0, uploadModalDragDepth - 1);
      if (uploadModalDragDepth === 0) $("#uploadModalForm").classList.remove("is-dragging");
    });
    $("#uploadModalForm").addEventListener("drop", (event) => {
      event.preventDefault();
      event.stopPropagation();
      uploadModalDragDepth = 0;
      $("#uploadModalForm").classList.remove("is-dragging");
      updateUploadModalFileSummary(event.dataTransfer.files, true);
    });
    $("#uploadChoiceModal").addEventListener("click", (event) => {
      if (event.target.id === "uploadChoiceModal") closeUploadChoiceModal();
    });
    document.querySelectorAll("[data-upload-choice]").forEach((button) => {
      button.addEventListener("click", () => setUploadChoiceCategory(button.dataset.uploadChoice));
    });
    document.querySelectorAll("[data-unit-upload]").forEach((button) => {
      button.addEventListener("click", () => openUnitUpload(button.dataset.unitUpload));
    });
    $("#unitListSearchInput")?.addEventListener("input", (event) => {
      state.unitListQuery = event.target.value || "";
      renderPart();
    });
    $("#unitUploadFilter")?.addEventListener("change", (event) => {
      state.unitUploadFilter = event.target.value || "all";
      renderPart();
    });
    $("#movePhotoBtn")?.addEventListener("click", () => openPhotoMoveModal().catch((error) => showNotice(error.message, true)));
    $("#closePhotoMoveBtn")?.addEventListener("click", closePhotoMoveModal);
    $("#cancelPhotoMoveBtn")?.addEventListener("click", closePhotoMoveModal);
    $("#photoMoveSearchInput")?.addEventListener("input", () => renderPhotoMoveTargets().catch((error) => showNotice(error.message, true)));
    $("#photoMoveTargetSelect")?.addEventListener("change", () => refreshPhotoMoveProcesses().catch((error) => showNotice(error.message, true)));
    $("#confirmPhotoMoveBtn")?.addEventListener("click", () => confirmPhotoMove().catch((error) => showNotice(error.message, true)));
    $("#photoMoveModal")?.addEventListener("click", (event) => { if (event.target.id === "photoMoveModal") closePhotoMoveModal(); });
    $("#backOverviewBtn").addEventListener("click", openOverview);
    $("#backPartBtn").addEventListener("click", () => {
      if (state.selectedPart) {
        renderPart();
        setView("part");
        revalidatePart(state.selectedPart).catch((error) => showNotice(error.message, true));
      } else {
        openOverview("construction");
      }
    });
    $("#unitCategoryConstructionBtn")?.addEventListener("click", () => selectGalleryScope("construction", state.activeProcessName));
    $("#unitCategorySupervisionBtn")?.addEventListener("click", () => selectGalleryScope("supervision", state.activeProcessName));
    $("#galleryUploadBtn")?.addEventListener("click", () => openUnitUpload(state.activePhotoCategory, state.activeProcessName));
    $("#gallerySelectBtn")?.addEventListener("click", () => {
      if (state.photoSelectionMode) clearPhotoSelection();
      else {
        state.photoSelectionMode = true;
        state.photoSelectionAnchor = -1;
        renderPhotos();
      }
    });
    $("#cancelPhotoSelectionBtn")?.addEventListener("click", () => clearPhotoSelection());
    $("#selectAllCurrentPhotosBtn")?.addEventListener("click", () => {
      const current = activeGalleryPhotos();
      const allSelected = current.length > 0 && current.every((photo) => state.selectedPrintPhotos[printSelectionKey(state.activePhotoCategory, photo.id)]);
      current.forEach((photo) => setPhotoSelected(state.activePhotoCategory, photo.id, !allSelected));
      renderPhotos();
    });
    $("#deleteSelectedCurrentPhotosBtn")?.addEventListener("click", () => deleteSelectedPhotos(photoSectionKey(state.activePhotoCategory, state.activeProcessName)).catch((error) => showNotice(error.message, true)));
    $("#printSelectedPhotosBtn")?.addEventListener("click", () => openUnitPrint(state.activePhotoCategory, state.activeProcessName, true));
    $("#unitPrintCurrentBtn")?.addEventListener("click", () => openUnitPrint(state.activePhotoCategory, state.activeProcessName, false));
    $("#unitMoreMenuBtn")?.addEventListener("click", (event) => {
      event.stopPropagation();
      const menu = $("#unitMoreMenu");
      menu?.classList.toggle("open");
      $("#unitMoreMenuBtn").setAttribute("aria-expanded", menu?.classList.contains("open") ? "true" : "false");
    });
    document.addEventListener("click", (event) => {
      if (event.target.closest(".unit-more-wrap")) return;
      $("#unitMoreMenu")?.classList.remove("open");
      $("#unitMoreMenuBtn")?.setAttribute("aria-expanded", "false");
    });
    initPhotoForms();

    photoCategories.forEach(({ key }) => {
      $(`#${key}PrevPhotoPage`).addEventListener("click", () => {
        state.photoPage[key] -= 1;
        renderPhotos();
      });
      $(`#${key}NextPhotoPage`).addEventListener("click", () => {
        state.photoPage[key] += 1;
        renderPhotos();
      });
    });
    $("#importForm").addEventListener("submit", async (event) => {
      event.preventDefault();
      try {
        const file = $("#importFile").files[0];
        if (!file) {
          showNotice("请选择要导入的项目划分表文件。", true);
          return;
        }
        showNotice("正在导入项目划分，请稍候...");
        const form = new FormData();
        form.append("file", file);
        const data = await apiJson("/api/import-projects", { method: "POST", body: form });
        await refreshAll();
        $("#importForm").reset();
        $("#importFileLabel").textContent = "选择项目划分文件导入";
        const result = data.result || {};
        showNotice(`自动转换导入完成：成功 ${result.created || 0} 个单元，跳过 ${result.skipped || 0} 行。`);
      } catch (error) {
        showNotice(error.message || "项目划分导入失败。", true);
      }
    });

    $("#importFile").addEventListener("change", () => {
      const file = $("#importFile").files[0];
      $("#importFileLabel").textContent = file ? file.name : "选择项目划分文件导入";
      if (file) {
        setProjectImportMenu(false);
        $("#importForm").requestSubmit();
      }
    });

    $("#downloadProjectTemplateBtn").addEventListener("click", () => {
      window.location.href = "/api/project-template.xlsx";
    });

    $("#exportPackageBtn")?.addEventListener("click", () => {
      window.location.href = "/api/engineering-package/export";
    });

    $("#packageFile")?.addEventListener("change", () => {
      const file = $("#packageFile").files[0];
      $("#packageFileLabel").textContent = file ? file.name : "导入资料包";
      if (file) importEngineeringPackage(file).catch((error) => showNotice(error.message, true));
    });

    $("#clearProjectsBtn").addEventListener("click", async () => {
      if (!state.auth.user) {
        showNotice("请先登录后再删除项目划分。", true);
        return;
      }
      if (!confirm("确认删除当前项目划分？系统会先移动到备份目录，当前项目树将被清空。")) return;
      const safetyPassword = prompt("请输入删除安全密码");
      if (!safetyPassword) {
        showNotice("请输入删除安全密码。", true);
        return;
      }
      const data = await apiJson("/api/clear-projects", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ safety_password: safetyPassword })
      });
      state.selectedProject = null;
      state.selectedCode = "";
      openOverview("construction");
      await refreshAll();
      showNotice(`${data.message || "当前项目划分已清空"}：${data.deleted || 0} 个项目已移入备份。`);
    });

    photoCategories.forEach(({ key }) => {
      if (!$(`#${key}UploadForm`)) return;
      $(`#${key}UploadForm`).addEventListener("submit", async (event) => {
        event.preventDefault();
        await uploadCategoryFiles(key, $(`#${key}PhotoFiles`).files);
      });
    });
    function requireSelected(action) {
      if (!state.selectedCode) {
        showNotice("请先选择单元工程。", true);
        return;
      }
      action();
    }

    function exportSelectedZip() {
      requireSelected(() => { window.location.href = `/api/export/${encodeURIComponent(state.selectedCode)}/zip`; });
    }

    const PRINT_STYLES = {
      one: { style: "one", page_size: "1", single_alignment: "center", photo_preset: "custom", photo_width_cm: "1", photo_height_cm: "1", caption_position: "bottom", caption_size_mm: "7.5", caption_font_size: "10", margin_top_mm: "6", margin_right_mm: "6", margin_bottom_mm: "6", margin_left_mm: "6", horizontal_gap_mm: "2", vertical_gap_mm: "2", image_fit: "contain", show_page_title: "1", auto_fill: "1", caption_fields: "title,id,part_name,photo_date,photographer" },
      two: { style: "two", page_size: "2", single_alignment: "center", photo_preset: "custom", photo_width_cm: "1", photo_height_cm: "1", caption_position: "bottom", caption_size_mm: "7.5", caption_font_size: "10", margin_top_mm: "6", margin_right_mm: "6", margin_bottom_mm: "6", margin_left_mm: "6", horizontal_gap_mm: "3", vertical_gap_mm: "3", image_fit: "contain", show_page_title: "1", auto_fill: "1", caption_fields: "title,id,part_name,photo_date,photographer" },
      four: { style: "four", page_size: "4", single_alignment: "center", photo_preset: "custom", photo_width_cm: "1", photo_height_cm: "1", caption_position: "bottom", caption_size_mm: "7.5", caption_font_size: "10", margin_top_mm: "5", margin_right_mm: "5", margin_bottom_mm: "5", margin_left_mm: "5", horizontal_gap_mm: "3", vertical_gap_mm: "3", image_fit: "contain", show_page_title: "1", auto_fill: "1", caption_fields: "title,id,part_name,photo_date,photographer" },
      custom: null
    };

    const PRINT_SETUP_FIELD_IDS = { layout: "printSetupLayout", page_size: "printSetupPageSize", single_alignment: "printSetupSingleAlignment", photo_preset: "printSetupPreset", photo_width_cm: "printSetupPhotoWidth", photo_height_cm: "printSetupPhotoHeight", caption_position: "printSetupCaptionPosition", caption_size_mm: "printSetupCaptionSize", caption_font_size: "printSetupCaptionFont", margin_top_mm: "printSetupMarginTop", margin_right_mm: "printSetupMarginRight", margin_bottom_mm: "printSetupMarginBottom", margin_left_mm: "printSetupMarginLeft", horizontal_gap_mm: "printSetupHorizontalGap", vertical_gap_mm: "printSetupVerticalGap", image_fit: "printSetupImageFit", show_page_title: "printSetupShowPageTitle" };

    function lastPrintSettings() {
      const saved = state.engineeringSettings?.last_print_settings;
      return saved && typeof saved === "object" && Object.keys(saved).length ? saved : null;
    }

    function lastPrintJob() {
      const saved = state.engineeringSettings?.last_print_job;
      return saved && typeof saved === "object" && Array.isArray(saved.groups) && saved.groups.length ? saved : null;
    }

    function applyPrintSetupValues(values) {
      if (!values || typeof values !== "object") return;
      Object.entries(PRINT_SETUP_FIELD_IDS).forEach(([key, id]) => {
        if (values[key] === undefined || values[key] === null) return;
        const input = $(`#${id}`);
        if (!input) return;
        const value = String(values[key]);
        if (input.tagName === "SELECT" && !Array.from(input.options).some((option) => option.value === value)) return;
        input.value = value;
      });
      if (values.caption_fields !== undefined) {
        const fields = new Set(Array.isArray(values.caption_fields)
          ? values.caption_fields
          : String(values.caption_fields).split(",").filter(Boolean));
        document.querySelectorAll("[data-print-caption-field]").forEach((input) => { input.checked = fields.has(input.value); });
      }
      syncPrintSetupPreset();
      syncPrintSingleAlignment();
    }

    function refreshLastPrintStyle() {
      const button = $("#lastPrintStyleBtn");
      const description = $("#lastPrintStyleDesc");
      const saved = lastPrintSettings();
      const job = lastPrintJob();
      if (!button || !description) return;
      button.disabled = !saved || !job;
      if (!saved || !job) {
        description.textContent = saved ? "请先完成一次打印，保存所选照片" : "本工程暂未保存打印方案";
        return;
      }
      const pageSize = Number(saved.page_size || 4);
      const sizeLabels = { "4inch": "4寸", "5inch": "5寸", "6inch": "6寸", custom: "自定义尺寸" };
      const photoCount = Math.max(0, Number(job.photo_count || 0));
      description.textContent = `恢复上次选中的 ${photoCount || "多"} 张照片 · ${saved.layout === "portrait" ? "A4 竖版" : "A4 横版"} · 每页${pageSize}张 · ${sizeLabels[saved.photo_preset] || "自定义尺寸"}`;
    }

    function selectPrintStyle(style) {
      state.printStyle = Object.prototype.hasOwnProperty.call(PRINT_STYLES, style) ? style : "custom";
      document.querySelectorAll("[data-print-style]").forEach((button) => {
        const active = button.dataset.printStyle === state.printStyle;
        button.classList.toggle("active", active);
        button.setAttribute("aria-pressed", active ? "true" : "false");
      });
      const isCustom = state.printStyle === "custom";
      $("#printCustomPanel").classList.toggle("open", isCustom);
      state.pendingPrintUrl = state.printSourceUrl || state.pendingPrintUrl;
      if (!isCustom) applyPrintStyleToPanel(state.printStyle);
      syncPrintSegmentButtons();
    }

    function applyPrintStyleToPanel(style) {
      const params = PRINT_STYLES[style];
      if (!params) return;
      applyPrintSetupValues(params);
    }

    function syncPrintSetupPreset() {
      const sizes = { "4inch": [10.2, 7.6], "5inch": [12.7, 8.9], "6inch": [15.2, 10.2] };
      const size = sizes[$("#printSetupPreset").value];
      if (size) {
        $("#printSetupPhotoWidth").value = size[0];
        $("#printSetupPhotoHeight").value = size[1];
      }
      const custom = !size;
      $("#printSetupPhotoWidth").disabled = !custom;
      $("#printSetupPhotoHeight").disabled = !custom;
    }

    function syncPrintSingleAlignment() {
      const input = $("#printSetupSingleAlignment");
      if (!input) return;
      const enabled = Number($("#printSetupPageSize").value || 4) === 1;
      input.disabled = !enabled;
      input.closest("label")?.classList.toggle("is-disabled", !enabled);
    }


    function syncPrintSegmentButtons() {
      const layout = $("#printSetupLayout")?.value || "landscape";
      const captionMode = $("#printSetupCaptionMode")?.value || "inline";
      document.querySelectorAll("[data-print-layout]").forEach((button) => {
        const active = button.dataset.printLayout === layout;
        button.classList.toggle("active", active);
        button.setAttribute("aria-pressed", active ? "true" : "false");
      });
      document.querySelectorAll("[data-print-caption-mode]").forEach((button) => {
        const active = button.dataset.printCaptionMode === captionMode;
        button.classList.toggle("active", active);
        button.setAttribute("aria-pressed", active ? "true" : "false");
      });
    }

    function setPrintLayoutChoice(layout) {
      const value = layout === "portrait" ? "portrait" : "landscape";
      $("#printSetupLayout").value = value;
      syncPrintSegmentButtons();
    }

    function setPrintCaptionModeChoice(mode) {
      const value = mode === "separate" ? "separate" : "inline";
      $("#printSetupCaptionMode").value = value;
      syncPrintSegmentButtons();
    }

    function loadPrintSetupValues() {
      const settings = state.engineeringSettings || {};
      $("#printSetupLayout").value = settings.print_layout || "landscape";
      $("#printSetupCaptionMode").value = settings.print_caption_mode || "inline";
      syncPrintSegmentButtons();
      $("#printSetupPageSize").value = String(settings.print_page_size || 4);
      $("#printSetupSingleAlignment").value = settings.print_single_alignment || "center";
      $("#printSetupPreset").value = settings.print_photo_preset || "5inch";
      $("#printSetupPhotoWidth").value = settings.print_photo_width_cm || 12.7;
      $("#printSetupPhotoHeight").value = settings.print_photo_height_cm || 8.9;
      $("#printSetupCaptionPosition").value = settings.print_caption_position || "bottom";
      $("#printSetupCaptionSize").value = settings.print_caption_size_mm || 7.5;
      $("#printSetupCaptionFont").value = settings.print_caption_font_size || 10;
      $("#printSetupMarginTop").value = settings.print_margin_top_mm ?? 6;
      $("#printSetupMarginRight").value = settings.print_margin_right_mm ?? 6;
      $("#printSetupMarginBottom").value = settings.print_margin_bottom_mm ?? 6;
      $("#printSetupMarginLeft").value = settings.print_margin_left_mm ?? 6;
      $("#printSetupHorizontalGap").value = settings.print_horizontal_gap_mm ?? 2;
      $("#printSetupVerticalGap").value = settings.print_vertical_gap_mm ?? 2;
      $("#printSetupImageFit").value = settings.print_image_fit || "contain";
      $("#printSetupShowPageTitle").value = settings.print_show_page_title === false ? "0" : "1";
      const fields = new Set(settings.print_caption_fields || ["title", "id", "part_name", "photo_date", "photographer"]);
      document.querySelectorAll("[data-print-caption-field]").forEach((input) => { input.checked = fields.has(input.value); });
      syncPrintSetupPreset();
      syncPrintSingleAlignment();
      refreshLastPrintStyle();
    }

    function openPrintSetup(url) {
      state.pendingPrintUrl = url;
      state.printSourceUrl = url;
      loadPrintSetupValues();
      const savedPageSize = Number(state.engineeringSettings?.print_page_size || 4);
      const openingStyle = savedPageSize === 1 ? "one" : savedPageSize === 2 ? "two" : savedPageSize === 4 ? "four" : "custom";
      selectPrintStyle(openingStyle);
      $("#printSetupModal").classList.add("open");
      $("#printSetupModal").setAttribute("aria-hidden", "false");
    }

    function closePrintSetup() {
      $("#printSetupModal").classList.remove("open");
      $("#printSetupModal").setAttribute("aria-hidden", "true");
      state.pendingPrintUrl = "";
      state.printSourceUrl = "";
    }

    function printSetupParams() {
      if (state.printStyle !== "custom" && PRINT_STYLES[state.printStyle]) {
        const params = new URLSearchParams(PRINT_STYLES[state.printStyle]);
        params.set("layout", $("#printSetupLayout").value || "landscape");
        params.set("caption_mode", $("#printSetupCaptionMode").value || "inline");
        return params;
      }
      const pageSize = Math.max(1, Math.min(12, Number($("#printSetupPageSize").value || 4)));
      const fields = Array.from(document.querySelectorAll("[data-print-caption-field]:checked")).map((input) => input.value);
      return new URLSearchParams({
        layout: $("#printSetupLayout").value,
        caption_mode: $("#printSetupCaptionMode").value || "inline",
        auto_fill: "1",
        page_size: String(pageSize),
        single_alignment: $("#printSetupSingleAlignment").value,
        photo_preset: $("#printSetupPreset").value,
        photo_width_cm: $("#printSetupPhotoWidth").value || "12.7",
        photo_height_cm: $("#printSetupPhotoHeight").value || "8.9",
        caption_position: $("#printSetupCaptionPosition").value,
        caption_size_mm: $("#printSetupCaptionSize").value || "7.5",
        caption_font_size: $("#printSetupCaptionFont").value || "10",
        margin_top_mm: $("#printSetupMarginTop").value || "0",
        margin_right_mm: $("#printSetupMarginRight").value || "0",
        margin_bottom_mm: $("#printSetupMarginBottom").value || "0",
        margin_left_mm: $("#printSetupMarginLeft").value || "0",
        horizontal_gap_mm: $("#printSetupHorizontalGap").value || "0",
        vertical_gap_mm: $("#printSetupVerticalGap").value || "0",
        image_fit: $("#printSetupImageFit").value,
        show_page_title: $("#printSetupShowPageTitle").value,
        caption_fields: fields.join(",")
      });
    }

    async function rememberLastPrint(params) {
      const data = await apiJson("/api/engineering-settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ settings: { last_print_settings: Object.fromEntries(params.entries()) } })
      });
      state.engineeringSettings = data.settings || state.engineeringSettings;
      refreshLastPrintStyle();
    }

    async function confirmPrintSetup() {
      if (!state.pendingPrintUrl) return;
      const url = new URL(state.pendingPrintUrl, window.location.origin);
      const params = printSetupParams();
      await rememberLastPrint(params);
      params.forEach((value, key) => url.searchParams.set(key, value));
      const target = `${url.pathname}${url.search}`;
      closePrintSetup();
      window.open(target, "_blank");
      // 打印页会在服务器端冻结本次实际进入预览的照片；稍后回读设置，让
      // 当前窗口无需刷新即可启用“上次打印”。
      window.setTimeout(() => {
        apiJson("/api/engineering-settings")
          .then((data) => {
            state.engineeringSettings = data.settings || state.engineeringSettings;
            refreshLastPrintStyle();
          })
          .catch(() => {});
      }, 350);
    }

    function openUnitPrint(category = state.activePhotoCategory, processName = state.activeProcessName, selectionOnly = false) {
      requireSelected(() => {
        const url = new URL(`/print/${encodeURIComponent(category)}/${encodeURIComponent(state.selectedCode)}`, window.location.origin);
        const current = photosForSection(category, processName);
        const selectedIds = current
          .filter((photo) => state.selectedPrintPhotos[printSelectionKey(category, photo.id)])
          .map((photo) => String(photo.id || ""))
          .filter(Boolean);
        if (selectionOnly && !selectedIds.length) {
          showNotice("请先选择要打印的照片。", true);
          return;
        }
        // 固定本次当前可见图库，避免其它工序或后续新增照片混入预览。
        const fixedIds = selectionOnly ? selectedIds : current.map((photo) => String(photo.id || "")).filter(Boolean);
        if (!fixedIds.length) {
          showNotice("当前图库没有可打印的照片。", true);
          return;
        }
        if (fixedIds.length) url.searchParams.set("ids", fixedIds.join(","));
        openPrintSetup(`${url.pathname}${url.search}`);
      });
    }

    document.querySelectorAll("[data-print-style]").forEach((button) => button.addEventListener("click", () => selectPrintStyle(button.dataset.printStyle)));
    document.querySelectorAll("[data-print-layout]").forEach((button) => button.addEventListener("click", () => setPrintLayoutChoice(button.dataset.printLayout)));
    document.querySelectorAll("[data-print-caption-mode]").forEach((button) => button.addEventListener("click", () => setPrintCaptionModeChoice(button.dataset.printCaptionMode)));
    $("#printSetupPreset").addEventListener("change", syncPrintSetupPreset);
    $("#printSetupPageSize").addEventListener("input", syncPrintSingleAlignment);
    $("#printSetupCaptionPosition").addEventListener("change", () => {
      const side = ["left", "right"].includes($("#printSetupCaptionPosition").value);
      const current = Number($("#printSetupCaptionSize").value || 0);
      if (side && current < 16) $("#printSetupCaptionSize").value = "32";
      if (!side && current > 20) $("#printSetupCaptionSize").value = "7";
    });
    $("#closePrintSetupBtn").addEventListener("click", closePrintSetup);
    $("#cancelPrintSetupBtn").addEventListener("click", closePrintSetup);
    $("#confirmPrintSetupBtn").addEventListener("click", () => confirmPrintSetup().catch((error) => showNotice(error.message || "保存打印方案失败", true)));
    $("#printSetupModal").addEventListener("click", (event) => { if (event.target.id === "printSetupModal") closePrintSetup(); });

    $("#printConstructionBtn").addEventListener("click", () => openUnitPrint("construction"));
    $("#printSupervisionBtn").addEventListener("click", () => openUnitPrint("supervision"));
    $("#batchPrintQuickBtn")?.addEventListener("click", () => openBatchPrint(state.activePhotoCategory || "construction", "print"));
    $("#batchPrintCategoryToggle")?.addEventListener("click", (event) => {
      const button = event.target.closest("[data-batch-category]");
      if (!button) return;
      const category = normalizePhotoCategory(button.dataset.batchCategory);
      if (category === normalizePhotoCategory(state.batchPrintCategory)) return;
      state.batchPrintCategory = category;
      state.batchSelectedUnits = new Set();
      state.batchSelectedProcesses = new Set();
      state.batchSelectionOrder = [];
      $("#batchPrintTitle").textContent = `${batchLabel(category)}${state.batchPrintMode === "pdf" ? "批量导出PDF" : "批量打印"}`;
      syncBatchPrintCategoryButtons();
      renderBatchPrintPicker();
    });
    $("#exportZipBtn").addEventListener("click", exportSelectedZip);
    $("#deleteUnitBtn").addEventListener("click", () => deleteUnit().catch((error) => showNotice(error.message, true)));
    $("#exportPhotoStatsBtn").addEventListener("click", () => { window.location.href = "/api/export/photo-statistics.xlsx"; });
    $("#exportUnitStatsBtn").addEventListener("click", () => requireSelected(() => { window.location.href = `/api/export/photo-statistics.xlsx?codes=${encodeURIComponent(state.selectedCode)}`; }));
    $("#addProcessBtn").addEventListener("click", openAddProcessModal);
    $("#closeAddProcessBtn")?.addEventListener("click", closeAddProcessModal);
    $("#cancelAddProcessBtn")?.addEventListener("click", closeAddProcessModal);
    $("#addProcessForm")?.addEventListener("submit", (event) => addProcess(event).catch((error) => showNotice(error.message, true)));
    $("#addProcessModal")?.addEventListener("click", (event) => { if (event.target.id === "addProcessModal") closeAddProcessModal(); });
    $("#settingsRefreshBtn")?.addEventListener("click", () => fullRefresh().catch((error) => showNotice(error.message, true)));

    setView("overview");
    const startupUnitCode = routeUnitCode();
    // 托盘“检查更新”带参数时立即检查；正常启动延迟 5 秒，避免抢占首屏请求。
    const updateRequested = new URLSearchParams(window.location.search).get("check_update") === "1";
    setTimeout(() => checkForUpdate(updateRequested).catch((error) => {
      if (updateRequested) showNotice(error.message || "检查更新失败", true);
    }), updateRequested ? 0 : 5000);
    loadBootstrap({ skipOtherImages: true }).then(() => {
      if (!state.auth.user) return;
      if (startupUnitCode) {
        loadProject(startupUnitCode, "detail").catch((error) => showNotice(error.message, true));
      }
    }).catch((error) => showNotice(error.message, true));

    // ============ 首开引导：登录页新手提示（自包含，不侵入主逻辑） ============
    (function initFirstUseGuide() {
      const KEY = "album-guide-login-done";
      const host = $("#guideHost");
      // 仅在登录页（未登录）且首开时触发
      if (!host || document.body.classList.contains("is-authed")) return;
      if (localStorage.getItem(KEY)) return;
      if (!window.requestAnimationFrame) return;

      const steps = [
        {
          target: "#gateUsername",
          title: "第一步：填写账号",
          desc: "请输入您的手机号 / QQ 号 / 邮箱作为登录账号。",
          placement: "bottom"
        },
        {
          target: "#gatePassword",
          title: "第二步：输入密码",
          desc: "请输入密码，密码是注册时自己设置的那一个。",
          placement: "bottom"
        },
        {
          target: "#gateRegisterBtn",
          title: "第三步：新用户先注册",
          desc: "第一次使用请先点【注册】创建账号，再回来登录。",
          placement: "top"
        },
        {
          target: "#gateLoginBtn",
          title: "第四步：登录进入",
          desc: "注册完成后点【登录】，就能进入工程工作台了。",
          placement: "top"
        }
      ];

      let idx = 0;
      const overlay = document.createElement("div");
      overlay.className = "guide-overlay active";
      overlay.setAttribute("aria-hidden", "true");
      const spot = document.createElement("div");
      spot.className = "guide-spot";
      const pop = document.createElement("div");
      pop.className = "guide-pop";
      pop.setAttribute("role", "dialog");
      pop.innerHTML = `
        <span class="gp-title"></span>
        <span class="gp-desc"></span>
        <div class="gp-btns">
          <span class="gp-step"></span>
          <button type="button" class="gp-prev" style="display:none">上一步</button>
          <button type="button" class="gp-skip">跳过</button>
          <button type="button" class="gp-next">下一步</button>
        </div>`;
      document.body.appendChild(overlay);
      document.body.appendChild(spot);
      document.body.appendChild(pop);

      const $title = pop.querySelector(".gp-title");
      const $desc = pop.querySelector(".gp-desc");
      const $step = pop.querySelector(".gp-step");
      const $prev = pop.querySelector(".gp-prev");
      const $skip = pop.querySelector(".gp-skip");
      const $next = pop.querySelector(".gp-next");

      function targetEl(stage) {
        return document.querySelector(stage.target);
      }

      function positionElem(el, rect) {
        const vw = window.innerWidth;
        const vh = window.innerHeight;
        let left = rect.left + rect.width / 2 - el.offsetWidth / 2;
        let top = rect.top + rect.height / 2 - el.offsetHeight / 2;
        left = Math.max(8, Math.min(left, vw - el.offsetWidth - 8));
        top = Math.max(8, Math.min(top, vh - el.offsetHeight - 8));
        el.style.left = left + "px";
        el.style.top = top + "px";
      }

      function nextTop(pageTop) {
        let top = pageTop;
        top = Math.max(8, Math.min(top, window.innerHeight - 180));
        return top;
      }

      function render() {
        const stage = steps[idx];
        const el = targetEl(stage);
        if (!el) { finish(); return; }
        pop.style.opacity = "0";
        const rect = el.getBoundingClientRect();
        if (stage.placement === "top") {
          pop.style.left = Math.max(8, Math.min(rect.left + rect.width / 2 - 170, window.innerWidth - 348)) + "px";
          pop.style.top = nextTop(rect.top - 156) + "px";
        } else {
          pop.style.left = Math.max(8, Math.min(rect.left + rect.width / 2 - 170, window.innerWidth - 348)) + "px";
          pop.style.top = nextTop(rect.bottom + 16) + "px";
        }
        $title.textContent = stage.title;
        $desc.textContent = stage.desc;
        $step.textContent = `${idx + 1} / ${steps.length}`;
        $prev.style.display = idx === 0 ? "none" : "";
        $next.textContent = idx === steps.length - 1 ? "完成" : "下一步";
        pop.style.opacity = "1";
      }

      function resizeSpot(el) {
        if (!el) { spot.style.display = "none"; return; }
        const rect = el.getBoundingClientRect();
        spot.style.display = "block";
        spot.style.left = (rect.left - 8) + "px";
        spot.style.top = (rect.top - 8) + "px";
        spot.style.width = (rect.width + 16) + "px";
        spot.style.height = (rect.height + 16) + "px";
      }

      function show(idx2) {
        const stage = steps[idx2];
        const el = targetEl(stage);
        resizeSpot(el);
        render();
      }

      function next() {
        idx += 1;
        if (idx >= steps.length) { finish(); return; }
        show(idx);
      }

      function prev() {
        if (idx === 0) return;
        idx -= 1;
        show(idx);
      }

      function dismiss() {
        if (overlay && overlay.parentNode) overlay.parentNode.removeChild(overlay);
        if (spot && spot.parentNode) spot.parentNode.removeChild(spot);
        if (pop && pop.parentNode) pop.parentNode.removeChild(pop);
      }

      function closeQuietly() { dismiss(); }

      function finish() {
        try { localStorage.setItem(KEY, "1"); } catch (e) {}
        dismiss();
      }

      $next.addEventListener("click", next);
      $prev.addEventListener("click", prev);
      $skip.addEventListener("click", finish);

      window.addEventListener("resize", () => show(idx));

      // 若用户未走完引导就登录成功，自动关闭登录页引导（不写入"已引导"，避免抢占工作台首开提示）
      if (window.MutationObserver) {
        new MutationObserver(() => {
          if (document.body.classList.contains("is-authed")) closeQuietly();
        }).observe(document.body, { attributes: true, attributeFilter: ["class"] });
      }

      // 延时显示，等登录页布局稳定
      setTimeout(function(){ show(0); }, 900);
    })();

    // ============ 首开引导：工作台整体界面操作流程 ============
    (function initWorkspaceGuide() {
      const KEY = "album-guide-workspace-v2-done";
      if (localStorage.getItem(KEY)) return;

      // 工作台引导需等已登录(body.is-authed)且界面渲染完成后再触发。
      // loadBootstrap 是异步的，这里监听 body class 变化，一旦出现 is-authed 即启动。
      let workspaceGuideStarted = false;
      function waitAuthed() {
        if (document.body.classList.contains("is-authed")) { start(); return; }
        if (!window.MutationObserver) {
          setTimeout(waitAuthed, 500);
          return;
        }
        const observer = new MutationObserver(() => {
          if (!document.body.classList.contains("is-authed")) return;
          observer.disconnect();
          start();
        });
        observer.observe(document.body, { attributes: true, attributeFilter: ["class"] });
      }

      function start() {
        if (workspaceGuideStarted) return;
        workspaceGuideStarted = true;
        // 再等一帧让工作台各区域完成渲染、布局稳定
        setTimeout(() => {
          overlay.classList.add("active");
          spot.style.display = "block";
          pop.style.display = "block";
          show(0);
        }, 600);
      }

      const steps = [
        {
          target: "#newEngineeringProjectBtn",
          title: "第一步：新建独立工程",
          desc: "点右侧加号，填写工程名称、专业和独立删除密码。每个工程的划分、照片、成员和设置互不混用。",
          placement: "bottom"
        },
        {
          target: "#engineeringProjectSelect",
          title: "第二步：确认当前工程",
          desc: "这里会列出全部工程。导入和上传前先确认选中的是哪个工程，展开即可切换。",
          placement: "bottom"
        },
        {
          target: "#settingsMenuBtn",
          title: "第三步：导入项目划分",
          desc: "进入【设置 → 项目划分】，先下载标准 Excel 模板，再选择填写好的文件导入。只会写入当前工程。",
          placement: "bottom"
        },
        {
          target: "#settingsMenuBtn",
          title: "第四步：检查编号规则",
          desc: "进入【设置 → 上传与匹配 → 编号规则】，分别确认施工单元、施工工序、监理单元和监理工序格式，保存后仅对当前工程生效。",
          placement: "bottom"
        },
        {
          target: "#tree",
          title: "第五步：核对工程目录",
          desc: "导入完成后，左侧会按单位工程、分部工程、单元工程显示。先点一个单元检查名称和编号。",
          placement: "right"
        },
        {
          target: "#globalUploadBtn",
          title: "第六步：开始上传",
          desc: "选择单元、施工或监理、单元照片或具体工序，确认目标后再加入照片；小程序也会同步使用同一工程划分。",
          placement: "bottom"
        }
      ];

      let idx = 0;
      const overlay = document.createElement("div");
      overlay.className = "guide-overlay";
      overlay.setAttribute("aria-hidden", "true");
      const spot = document.createElement("div");
      spot.className = "guide-spot";
      spot.style.display = "none";
      const pop = document.createElement("div");
      pop.className = "guide-pop";
      pop.style.display = "none";
      pop.setAttribute("role", "dialog");
      pop.innerHTML = `
        <span class="gp-title"></span>
        <span class="gp-desc"></span>
        <div class="gp-btns">
          <span class="gp-step"></span>
          <button type="button" class="gp-prev" style="display:none">上一步</button>
          <button type="button" class="gp-skip">跳过</button>
          <button type="button" class="gp-next">下一步</button>
        </div>`;
      document.body.appendChild(overlay);
      document.body.appendChild(spot);
      document.body.appendChild(pop);

      const $title = pop.querySelector(".gp-title");
      const $desc = pop.querySelector(".gp-desc");
      const $step = pop.querySelector(".gp-step");
      const $prev = pop.querySelector(".gp-prev");
      const $skip = pop.querySelector(".gp-skip");
      const $next = pop.querySelector(".gp-next");

      function targetEl(stage) { return document.querySelector(stage.target); }

      function nextTop(pageTop) {
        let top = pageTop;
        top = Math.max(8, Math.min(top, window.innerHeight - 180));
        return top;
      }

      function clampPos(el) {
        el.style.left = Math.max(8, Math.min(parseFloat(el.style.left) || 0, window.innerWidth - el.offsetWidth - 8)) + "px";
        el.style.top = Math.max(8, Math.min(parseFloat(el.style.top) || 0, window.innerHeight - el.offsetHeight - 8)) + "px";
      }

      function render() {
        const stage = steps[idx];
        const el = targetEl(stage);
        if (!el) { finish(); return; }
        pop.style.opacity = "0";
        const rect = el.getBoundingClientRect();
        if (stage.placement === "top") {
          pop.style.left = (rect.left + rect.width / 2 - 170) + "px";
          pop.style.top = nextTop(rect.top - 156) + "px";
        } else if (stage.placement === "right") {
          pop.style.left = Math.min(rect.right + 18, window.innerWidth - 348) + "px";
          pop.style.top = Math.max(8, rect.top + rect.height / 2 - 60) + "px";
        } else {
          pop.style.left = (rect.left + rect.width / 2 - 170) + "px";
          pop.style.top = nextTop(rect.bottom + 16) + "px";
        }
        clampPos(pop);
        $title.textContent = stage.title;
        $desc.textContent = stage.desc;
        $step.textContent = `${idx + 1} / ${steps.length}`;
        $prev.style.display = idx === 0 ? "none" : "";
        $next.textContent = idx === steps.length - 1 ? "完成" : "下一步";
        pop.style.opacity = "1";
      }

      function resizeSpot(el) {
        if (!el) { spot.style.display = "none"; return; }
        const rect = el.getBoundingClientRect();
        spot.style.display = "block";
        spot.style.left = (rect.left - 8) + "px";
        spot.style.top = (rect.top - 8) + "px";
        spot.style.width = (rect.width + 16) + "px";
        spot.style.height = (rect.height + 16) + "px";
      }

      function show(i) {
        const stage = steps[i];
        const el = targetEl(stage);
        resizeSpot(el);
        render();
      }

      function next() {
        idx += 1;
        if (idx >= steps.length) { finish(); return; }
        show(idx);
      }

      function prev() {
        if (idx === 0) return;
        idx -= 1;
        show(idx);
      }

      function dismiss() {
        if (overlay && overlay.parentNode) overlay.parentNode.removeChild(overlay);
        if (spot && spot.parentNode) spot.parentNode.removeChild(spot);
        if (pop && pop.parentNode) pop.parentNode.removeChild(pop);
      }

      function finish() {
        try { localStorage.setItem(KEY, "1"); } catch (e) {}
        dismiss();
      }

      $next.addEventListener("click", next);
      $prev.addEventListener("click", prev);
      $skip.addEventListener("click", finish);
      window.addEventListener("resize", () => show(idx));

      // 用户停留在登录页多久都可以；真正登录并渲染工作台后再提示。
      waitAuthed();
    })();
