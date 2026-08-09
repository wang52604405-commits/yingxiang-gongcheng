const $ = (selector) => document.querySelector(selector);
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
      printSetupMode: "default",
      pendingPrintUrl: "",
      batchSelectedCodes: new Set(),
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
      overviewExpandedUnits: new Set(),
      optimizationStatus: {},
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
      return [];
    }

    function isProcessProject() {
      return false;
    }

    function processCodeForName(name) {
      const settings = state.engineeringSettings || {};
      const prefix = String(settings.process_prefix || "").trim();
      if (!prefix) return "";
      const index = Math.max(1, selectedProcesses().indexOf(name) + 1);
      const digits = Math.max(1, Math.min(8, Number(settings.process_digits || 3)));
      return `${prefix}${String(index).padStart(digits, "0")}`;
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
      if (node.type === "part") return node.projects.length;
      return node.children.reduce((sum, childNode) => sum + pickerProjectCount(childNode), 0);
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

    async function openBatchPrint(category, mode = "print") {
      state.batchPrintCategory = normalizePhotoCategory(category);
      state.batchPrintMode = mode === "pdf" ? "pdf" : "print";
      state.batchSelectedCodes = new Set();
      state.batchVisibleCodes = [];
      $("#batchPrintTitle").textContent = `${batchLabel(state.batchPrintCategory)}${state.batchPrintMode === "pdf" ? "批量导出PDF" : "批量打印"}`;
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
      const activeClass = state.batchSelectedCodes.has(code) ? " active" : "";
      return `
        <button class="picker-project batch-project${activeClass}" type="button" data-batch-code="${escapeHtml(code)}">
          <strong>${escapeHtml(h.unitName || projectName(project))}</strong>
          <span>${escapeHtml(h.unitCode || code)}</span>
          <span class="batch-check">${activeClass ? "✓" : "+"}</span>
        </button>
      `;
    }

    function nodeDescendantCodes(node) {
      if (!node) return [];
      if (node.type === "part") return node.projects.map(projectCode).filter(Boolean);
      return node.children.flatMap((childNode) => nodeDescendantCodes(childNode));
    }

    function nodeAllSelected(node) {
      const codes = nodeDescendantCodes(node);
      return codes.length > 0 && codes.every((code) => state.batchSelectedCodes.has(code));
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
      body.querySelectorAll("[data-batch-code]").forEach((button) => {
        button.addEventListener("click", () => {
          const code = button.dataset.batchCode;
          state.batchSelectedCodes.has(code) ? state.batchSelectedCodes.delete(code) : state.batchSelectedCodes.add(code);
          renderBatchPrintPicker();
        });
      });
      body.querySelectorAll("[data-batch-select-node]").forEach((button) => {
        button.addEventListener("click", () => {
          const node = findNode(state.treeRoot, button.dataset.batchSelectNode);
          const codes = nodeDescendantCodes(node);
          if (!codes.length) return;
          const allSelected = codes.every((code) => state.batchSelectedCodes.has(code));
          codes.forEach((code) => {
            if (allSelected) {
              state.batchSelectedCodes.delete(code);
            } else {
              state.batchSelectedCodes.add(code);
            }
          });
          renderBatchPrintPicker();
        });
      });
    }

    function updateBatchPrintCount() {
      $("#batchPrintCount").textContent = `已选 ${state.batchSelectedCodes.size} 个`;
      $("#batchPrintSubmitBtn").textContent = `${state.batchPrintMode === "pdf" ? "导出PDF" : "打印"}已选 ${state.batchSelectedCodes.size} 个`;
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
      state.batchVisibleCodes.forEach((code) => state.batchSelectedCodes.add(code));
      renderBatchPrintPicker();
    }

    function submitBatchPrint() {
      const codes = Array.from(state.batchSelectedCodes);
      if (!codes.length) {
        showNotice(`请先选择要${state.batchPrintMode === "pdf" ? "导出PDF" : "批量打印"}的单元工程。`, true);
        return;
      }
      const url = `/print/${encodeURIComponent(state.batchPrintCategory)}/batch?codes=${encodeURIComponent(codes.join(","))}&mode=${encodeURIComponent(state.batchPrintMode)}`;
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
      });
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
      const name = project.project_name || projectInfoContractName() || project.id || "未命名工程";
      const code = project.project_code || "";
      if (!code || code === "default" || code === name) return name;
      return `${name} / ${code}`;
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

    const NUMBER_TEMPLATE_LABELS = [
      ["{unit_code}", "【单元编号】"],
      ["{unit_order}", "【单元顺序号】"],
      ["{seq}", "【流水号】"],
      ["{category}", "【类别】"],
      ["{code}", "【单元编号】"]
    ];

    function numberTemplateToReadable(template) {
      let value = String(template || "");
      NUMBER_TEMPLATE_LABELS.forEach(([token, label]) => {
        value = value.split(token).join(label);
      });
      return value;
    }

    function readableToNumberTemplate(template) {
      let value = String(template || "").trim();
      NUMBER_TEMPLATE_LABELS.forEach(([token, label]) => {
        const normalizedToken = token === "{code}" ? "{unit_code}" : token;
        value = value.split(label).join(normalizedToken);
      });
      return value;
    }

    function setProjectSettingsTab(tab) {
      const nextTab = tab || "info";
      document.querySelectorAll("[data-project-settings-tab]").forEach((button) => {
        button.classList.toggle("active", button.dataset.projectSettingsTab === nextTab);
      });
      document.querySelectorAll("[data-project-settings-panel]").forEach((panel) => {
        panel.classList.toggle("active", panel.dataset.projectSettingsPanel === nextTab);
      });
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

    function openProjectInfoModal() {
      const settings = state.engineeringSettings || {};
      const rules = settings.numbering_rules || {};
      const construction = rules.construction || {};
      const supervision = rules.supervision || {};
      $("#projectInfoNameInput").value = projectInfoValue("project_name");
      $("#projectInfoCodeInput").value = projectInfoValue("project_code");
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
      $("#settingsConstructionUnitTemplate").value = numberTemplateToReadable(construction.unit_template || construction.template || "{unit_code}-SY{seq}");
      $("#settingsConstructionStart").value = construction.start || 1;
      $("#settingsConstructionDigits").value = construction.digits || 3;
      $("#settingsSupervisionUnitTemplate").value = numberTemplateToReadable(supervision.unit_template || supervision.template || "{unit_code}-JY{seq}");
      $("#settingsSupervisionStart").value = supervision.start || 1;
      $("#settingsSupervisionDigits").value = supervision.digits || 3;
      $("#settingsPrintLayoutInput").value = settings.print_layout || "landscape";
      $("#settingsPrintPageSizeInput").value = String(settings.print_page_size || 4);
      $("#settingsPrintPhotoPresetInput").value = settings.print_photo_preset || "5inch";
      $("#settingsPrintPhotoWidthInput").value = settings.print_photo_width_cm || "";
      $("#settingsPrintPhotoHeightInput").value = settings.print_photo_height_cm || "";
      $("#settingsPrintCaptionFontSizeInput").value = settings.print_caption_font_size || 7.2;
      $("#settingsPrintCaptionPositionInput").value = settings.print_caption_position || "left";
      syncPrintPhotoPresetInputs();
      $("#settingsPhotoFieldsInput").value = (settings.photo_detail_fields || []).map((field) => `${field.label || ""}=${field.source === "custom" ? (field.value || "") : (field.source || "")}`).join("\n");
      setProjectSettingsTab("info");
      $("#projectInfoModal").classList.add("open");
      $("#projectInfoModal").setAttribute("aria-hidden", "false");
      renderPhotoOptimizationStatus();
      refreshPhotoOptimizationStatus().catch(() => {});
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
      const rules = {
        construction: {
          template: readableToNumberTemplate($("#constructionNumberTemplate").value),
          start: Number($("#constructionNumberStart").value || 1),
          digits: Number($("#constructionNumberDigits").value || 3)
        },
        supervision: {
          template: readableToNumberTemplate($("#supervisionNumberTemplate").value),
          start: Number($("#supervisionNumberStart").value || 1),
          digits: Number($("#supervisionNumberDigits").value || 3)
        }
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
        project_name: $("#projectInfoNameInput").value.trim(),
        project_code: $("#projectInfoCodeInput").value.trim(),
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
      const settingsPayload = {
        numbering_mode: $("#settingsNumberingModeInput").value,
        process_prefix: "",
        process_digits: 3,
        unit_order_digits: Number($("#settingsUnitOrderDigitsInput").value || 3),
        print_layout: $("#settingsPrintLayoutInput").value,
        print_page_size: Number($("#settingsPrintPageSizeInput").value || 4),
        print_photo_preset: $("#settingsPrintPhotoPresetInput").value,
        print_photo_width_cm: Number($("#settingsPrintPhotoWidthInput").value || 0),
        print_photo_height_cm: Number($("#settingsPrintPhotoHeightInput").value || 0),
        print_caption_font_size: Number($("#settingsPrintCaptionFontSizeInput").value || 7.2),
        print_caption_position: $("#settingsPrintCaptionPositionInput").value,
        watermark_ocr_enabled: true,
        photo_detail_fields: photoFields,
        numbering_rules: {
          construction: {
            template: constructionUnitTemplate,
            unit_template: constructionUnitTemplate,
            process_template: constructionUnitTemplate,
            start: Number($("#settingsConstructionStart").value || 1),
            digits: Number($("#settingsConstructionDigits").value || 3)
          },
          supervision: {
            template: supervisionUnitTemplate,
            unit_template: supervisionUnitTemplate,
            process_template: supervisionUnitTemplate,
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
      showNotice("工程设置已保存。");
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
      showNotice(`工程已删除，${data.deleted || 0} 个单元已移入备份。`);
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
      $("#authStatus").textContent = user ? `当前：${user.username}` : "未填写姓名";
      $("#logoutBtn").style.display = user ? "" : "none";
    }

    async function loadAuth() {
      const data = await apiJson("/api/auth/me");
      state.auth.user = data.user || null;
      renderAuth();
    }

    async function checkForUpdate(manual = false) {
      const data = await apiJson("/api/cloud/check-update");
      if (!data.ok) {
        if (manual) showNotice(data.error || "检查更新失败（服务器未部署或不可达）", true);
        return;
      }
      if (!data.has_update || !data.latest_version) {
        if (manual) showNotice("当前已是最新版本。");
        return;
      }
      // 有新版本：显示更新内容和下载
      const changelog = (data.changelog || []).join("\n");
      const fixes = (data.fixes || []).join("\n");
      const detail = `发现新版本 ${data.latest_version}\n\n【更新内容】\n${changelog || "（无）"}\n\n【修复内容】\n${fixes || "（无）"}\n\n是否下载最新安装包？`;
      const go = confirm(detail);
      if (go) {
        if (data.download_url) {
          window.open(data.download_url, "_blank");
        } else {
          window.location.href = "/api/cloud/download-update";
        }
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
      // 登录前先记住，失败也保留账号
      saveLoginCredentials(username, password);
      const data = await apiJson(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password, remember: true })
      });
      state.auth.user = data.user || null;
      passwordInput.value = "";
      renderAuth();
      showNotice("已进入软件");
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
        if (node.type === "part") {
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
          <div class="recent-upload-item" data-code="${escapeHtml(rec.project_code)}">
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
        list.querySelectorAll("[data-code]").forEach((row) => {
          row.addEventListener("click", () => loadProject(row.dataset.code, "detail").catch((error) => showNotice(error.message, true)));
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

    function setView(mode) {
      state.viewMode = mode;
      $("#overviewView").style.display = mode === "overview" ? "" : "none";
      $("#partView").style.display = mode === "part" ? "" : "none";
      $("#unitView").style.display = mode === "unit" ? "" : "none";
    }

    function routeUnitCode() {
      return new URLSearchParams(window.location.search).get("unit") || localStorage.getItem("last-unit-code") || "";
    }

    function setRouteUnitCode(code) {
      const url = new URL(window.location.href);
      if (code) {
        url.searchParams.set("unit", code);
        localStorage.setItem("last-unit-code", code);
      } else {
        url.searchParams.delete("unit");
        localStorage.removeItem("last-unit-code");
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
      part.projects = [];
      part.loading = true;
      renderPart();
      setView("part");
      try {
        await loadPartPage(part, 1);
      } catch (error) {
        part.loading = false;
        part.loadError = error.message || "分部单元加载失败";
        renderPart();
      }
      if (window.matchMedia("(pointer: coarse), (max-width: 900px)").matches) {
        setTimeout(() => $("#partView").scrollIntoView({ block: "start", behavior: "smooth" }), 0);
      }
    }

    async function loadPartPage(part, page = 1) {
      if (!part?.partKey) {
        renderPart();
        return;
      }
      part.loading = true;
      part.loadError = "";
      renderPart();
      const data = await apiJson(`/api/units?part_key=${encodeURIComponent(part.partKey)}&page=1&page_size=10000`);
      if (state.selectedPart !== part) return;
      part.projects = data.projects || [];
      part.currentPage = Number(data.page || 1);
      part.totalPages = Number(data.pages || 1);
      part.unitCount = Number(data.total || part.unitCount || 0);
      part.loading = false;
      part.projects.forEach((project) => {
        if (!state.projects.some((item) => projectCode(item) === projectCode(project))) state.projects.push(project);
      });
      renderPart();
    }

    function renderPart() {
      const part = state.selectedPart;
      if (!part) return;
      const parentName = part.parent?.name || "";
      $("#partTitle").textContent = part.name;
      $("#partSub").textContent = `${parentName}${part.code ? " / " + part.code : ""} · 四列显示，点击单元进入详情`;
      $("#partCount").textContent = `${Number(part.unitCount || part.projects.length)} 条`;

      const rows = part.projects;
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
              <span><small>施工</small><b>${Number(project.construction_photo_count || 0)}</b></span>
              <span><small>监理</small><b>${Number(project.supervision_photo_count || 0)}</b></span>
            </span>
          </span>
          <span class="unit-card-meta">
            <span>${Number(project.photo_count || 0)} 张照片</span>
            <span>${escapeHtml(project.latest_upload || "-")}</span>
          </span>
        </button>
      `).join("") : `<div class="empty">该分部工程下暂无单元工程。</div>`;
      unitRows.querySelectorAll("[data-unit-code]").forEach((button) => {
        button.addEventListener("click", () => loadProject(button.dataset.unitCode, "detail"));
      });
    }

    async function loadProject(code, tab = "detail") {
      const data = await apiJson(`/api/photos/${encodeURIComponent(code)}`);
      state.selectedProject = data.project;
      state.selectedCode = projectCode(data.project);
      setRouteUnitCode(state.selectedCode);
      if (!findOtherNode(state.selectedCode)) state.selectedOtherCode = "";
      state.photos = data.photos || [];
      state.photoPage = { construction: 1, supervision: 1 };
      state.selectedPrintPhotos = {};
      renderUnit();
      setView("unit");
      renderOtherImagesTree();
      if (window.matchMedia("(pointer: coarse), (max-width: 900px)").matches) {
        setTimeout(() => $("#unitView").scrollIntoView({ block: "start", behavior: "smooth" }), 0);
      }
      if (tab === "upload") openUploadChoiceModal();
      if (tab !== "upload" && state.pendingUploadCategory) {
        const category = state.pendingUploadCategory;
        state.pendingUploadCategory = "";
        focusUploadCategory(category);
      }
    }

    function renderUnit() {
      const project = state.selectedProject;
      if (!project) return;
      $("#unitTitle").textContent = projectName(project);
      $("#unitSub").textContent = projectCode(project);
      renderPhotos();
    }

    // 列表缩略图占位：缩略图未生成时显示灰色占位，绝不回退加载原图
    const THUMB_PLACEHOLDER = "data:image/svg+xml;charset=utf-8," + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="480" height="300"><rect width="100%" height="100%" fill="#eef2f1"/><text x="50%" y="50%" fill="#9aa5a1" font-size="16" text-anchor="middle" dominant-baseline="middle">图片加载中</text></svg>');

    // 照片列表分批渲染：每批 120 张，滚动到底自动加载下一批，避免一次性渲染上千节点
    const PHOTOS_BATCH = 120;
    let photoLazyObserver = null;

    function photoCardHTML(photo, key, sectionKey, isSelectMode) {
      const orientation = normalizePhotoOrientation(photo.orientation);
      const photoId = String(photo.id || "");
      const isPrintSelected = Boolean(state.selectedPrintPhotos[printSelectionKey(key, photoId)]);
      return `
        <article class="photo is-${orientation}${isPrintSelected ? " is-selected" : ""}${isSelectMode ? " is-select-mode" : ""}" draggable="${isSelectMode ? "false" : "true"}" data-photo-id="${escapeHtml(photoId)}" data-category="${key}" data-section-key="${escapeHtml(sectionKey)}">
          <button class="photo-preview-trigger" type="button" data-preview-src="${escapeHtml(photo.url || "")}" data-preview-title="${escapeHtml(photo.title || photo.id || photo.original_name || photo.filename || "照片")}">
            <img src="${escapeHtml(photo.thumb_url || THUMB_PLACEHOLDER)}" loading="lazy" decoding="async" alt="${escapeHtml(photo.title || photo.original_name || photo.filename || "photo")}">
          </button>
          <div class="photo-meta archive-info">
            <div class="photo-card-line">
              ${isSelectMode ? `<label class="photo-print-check" title="勾选后只打印选中的照片">
                <input type="checkbox" data-print-photo="${escapeHtml(photoId)}" data-category="${key}" ${isPrintSelected ? "checked" : ""}>
              </label>` : ""}
              <button class="photo-title-button" type="button" data-edit-photo="${escapeHtml(photo.id || "")}" data-category="${key}" title="点击修改照片信息">
                <strong class="photo-card-title" title="${escapeHtml(photo.title || photo.original_name || photo.filename || photo.id || "-")}">${escapeHtml(photoShortLabel(photo) || photo.title || photo.original_name || photo.filename || "-")}</strong>
              </button>
            </div>
          </div>
        </article>
      `;
    }

    function photosForSection(key, groupName) {
      const processMatches = (photo) => !groupName || String(photo.process_name || "").trim() === groupName;
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
      const isSelectMode = Boolean(state.photoSelectMode[sectionKey]);
      const next = photos.slice(rendered, rendered + PHOTOS_BATCH);
      listEl.insertAdjacentHTML("beforeend", next.map((photo) => photoCardHTML(photo, key, sectionKey, isSelectMode)).join(""));
      listEl.dataset.rendered = String(rendered + next.length);
    }

    function setupLazyPhotoLoad() {
      if (photoLazyObserver) {
        photoLazyObserver.disconnect();
        photoLazyObserver = null;
      }
      document.querySelectorAll("#photoSectionsHost .photo-section").forEach((sectionEl) => {
        const listEl = sectionEl.querySelector(".photos");
        const key = sectionEl.dataset.category;
        const groupName = sectionEl.dataset.processName || "";
        const total = photosForSection(key, groupName).length;
        const rendered = parseInt(listEl?.dataset.rendered || "0", 10);
        if (rendered < total) {
          photoLazyObserver = photoLazyObserver || new IntersectionObserver((entries) => {
            entries.forEach((entry) => {
              if (entry.isIntersecting) {
                const sec = entry.target.closest(".photo-section");
                if (sec) loadMorePhotos(sec);
              }
            });
          }, { rootMargin: "500px 0px" });
          photoLazyObserver.observe(listEl);
        }
      });
    }

    function renderPhotos() {
      const host = $("#photoSectionsHost");
      if (!host) return;
      // 其它影像单元只有施工影像，不显示监理栏
      const isOtherUnit = Boolean(findOtherNode(state.selectedCode));
      const categories = isOtherUnit
        ? photoCategories.filter((c) => c.key !== "supervision")
        : photoCategories;
      const groups = isProcessProject()
        ? selectedProcesses().map((name) => ({ name, code: processCodeForName(name) }))
        : [{ name: "", code: "" }];
      host.className = `photo-side photo-sections ${groups.length > 1 ? "is-process-layout" : ""}`;
      host.innerHTML = groups.map((group, groupIndex) => categories.map(({ key }) => {
        const sectionId = `${key}_${groupIndex}`;
        const groupName = String(group.name || "").trim();
        const processMatches = (photo) => !groupName || String(photo.process_name || "").trim() === groupName;
        const photos = categoryPhotos(key).filter(processMatches);
        const titlePrefix = group.name ? `${group.code ? group.code + " " : ""}${group.name} · ` : "";
        const sectionKey = photoSectionKey(key, group.name);
        const isSelectMode = Boolean(state.photoSelectMode[sectionKey]);
        const useConstructionBtn = key === "supervision"
          ? `<button class="secondary" type="button" data-use-construction="${escapeHtml(sectionKey)}" data-process-name="${escapeHtml(group.name)}">复制施工照片</button>`
          : "";
        return `
          <section class="photo-section" data-photo-section="${escapeHtml(sectionKey)}" data-category="${key}" data-process-name="${escapeHtml(group.name)}">
            <div class="photo-section-head">
              <h3 class="photo-section-title">${escapeHtml(titlePrefix)}${key === "supervision" ? "监理单元影像" : "施工单元影像"}</h3>
              <div class="photo-section-actions">
                <button type="button" data-toggle-select-photos="${escapeHtml(sectionKey)}">${isSelectMode ? "取消" : "多选"}</button>
                <button class="secondary" type="button" data-delete-selected-photos="${escapeHtml(sectionKey)}">删除</button>
                ${useConstructionBtn}
                <button type="button" data-unit-upload="${key}" data-process-name="${escapeHtml(group.name)}">上传</button>
              </div>
            </div>
            <form id="${sectionId}UploadForm" class="photo-upload-form" style="display:none;" data-category="${key}" data-process-name="${escapeHtml(group.name)}">
              <label>选择照片<input id="${sectionId}PhotoFiles" type="file" accept=".jpg,.jpeg,.png" multiple></label>
              <label>题名<input id="${sectionId}PhotoTitle" type="text" placeholder="文件名含日期和文字时自动识别，可留空"></label>
              <label>时间<input id="${sectionId}PhotoDate" type="date" title="文件名含日期可自动识别，留空自动提取"></label>
              <label>摄影者<input id="${sectionId}PhotoPhotographer" type="text"></label>
              <label>文字说明<textarea id="${sectionId}PhotoDescription"></textarea></label>
              <div class="upload-drop-zone" tabindex="0">
                <strong>拖拽 JPG/PNG 到这里上传，也可直接粘贴图片</strong>
                <span>文件选择、拖拽、粘贴使用同一套上传规则。</span>
              </div>
              <div class="actions"><button type="submit">上传照片</button></div>
              <div id="${sectionId}UploadResult" class="inline-result" style="display:none;"></div>
            </form>
            <div id="${sectionId}PhotosList" class="photos" data-rendered="${Math.min(photos.length, PHOTOS_BATCH)}">
              ${photos.length ? photos.slice(0, PHOTOS_BATCH).map((photo) => photoCardHTML(photo, key, sectionKey, isSelectMode)).join("") : `<div class="empty">暂无照片。</div>`}
            </div>
          </section>
        `;
      }).join("")).join("");

      host.querySelectorAll("button[data-unit-upload]").forEach((button) => {
        button.addEventListener("click", () => {
          const section = button.closest(".photo-section");
          const form = section?.querySelector(".photo-upload-form");
          if (form) form.style.display = form.style.display === "none" ? "grid" : "none";
        });
      });
      host.querySelectorAll("button[data-renumber-photos]").forEach((button) => {
        button.addEventListener("click", () => renumberPhotos().catch((error) => showNotice(error.message, true)));
      });
      host.querySelectorAll("button[data-use-construction]").forEach((button) => {
        button.addEventListener("click", async () => {
          const processName = button.dataset.processName || "";
          if (!window.confirm("将本单元尚未复制的施工照片复制到监理影像，并自动生成监理编号（JY…）。已复制照片会自动跳过，确定继续吗？")) return;
          try {
            if (!(await ensureAuthenticated("使用施工照片"))) return;
            const data = await apiJson(`/api/photos/${encodeURIComponent(state.selectedCode)}/copy-construction-to-supervision`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ process_name: processName })
            });
            state.photos = data.photos || [];
            state.selectedPrintPhotos = {};
            renderPhotos();
            showNotice(`已复制 ${data.added ? data.added.length : 0} 张施工照片到监理影像。`);
          } catch (error) {
            showNotice(error.message, true);
          }
        });
      });
      host.querySelectorAll("button[data-toggle-select-photos]").forEach((button) => {
        button.addEventListener("click", () => {
          const key = button.dataset.toggleSelectPhotos || "";
          state.photoSelectMode[key] = !state.photoSelectMode[key];
          renderPhotos();
        });
      });
      host.querySelectorAll("button[data-delete-selected-photos]").forEach((button) => {
        button.addEventListener("click", () => deleteSelectedPhotos(button.dataset.deleteSelectedPhotos).catch((error) => showNotice(error.message, true)));
      });
      host.querySelectorAll(".photo-upload-form").forEach((form) => {
        form.addEventListener("submit", (event) => {
          event.preventDefault();
          uploadCategoryFiles(form.dataset.category, form.querySelector("input[type=file]").files, form).catch((error) => showNotice(error.message, true));
        });
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
          uploadCategoryFiles(form.dataset.category, event.dataTransfer.files, form).catch((error) => showNotice(error.message, true));
        });
        form.addEventListener("paste", (event) => {
          const files = Array.from(event.clipboardData?.files || []);
          if (!files.length) return;
          event.preventDefault();
          uploadCategoryFiles(form.dataset.category, files, form).catch((error) => showNotice(error.message, true));
        });
      });
      host.querySelectorAll("button[data-edit-photo]").forEach((button) => {
        button.addEventListener("click", (event) => {
          event.stopPropagation();
          const card = button.closest(".photo");
          if (card && state.photoSelectMode[card.dataset.sectionKey]) {
            togglePhotoSelection(card);
            return;
          }
          openPhotoEdit(button.dataset.category, button.dataset.editPhoto).catch((error) => showNotice(error.message, true));
        });
      });
      host.querySelectorAll("input[data-print-photo]").forEach((input) => {
        input.addEventListener("click", (event) => event.stopPropagation());
        input.addEventListener("change", () => {
          setPhotoSelected(input.dataset.category, input.dataset.printPhoto, input.checked);
          input.closest(".photo")?.classList.toggle("is-selected", input.checked);
        });
      });
      host.querySelectorAll(".photo[data-photo-id]").forEach((card) => {
        card.addEventListener("click", (event) => {
          if (!state.photoSelectMode[card.dataset.sectionKey]) return;
          if (event.target.closest(".photo-title-button, .photo-print-check, input, label")) return;
          event.preventDefault();
          togglePhotoSelection(card);
        });
      });
      host.querySelectorAll("[data-preview-src]").forEach((button) => {
        button.addEventListener("click", (event) => {
          const card = button.closest(".photo");
          if (card && state.photoSelectMode[card.dataset.sectionKey]) {
            event.preventDefault();
            event.stopPropagation();
            togglePhotoSelection(card);
            return;
          }
          openPhotoPreview(button.dataset.previewSrc, button.dataset.previewTitle);
        });
      });
      initPhotoDragSort(host);
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

    async function openUploadChoiceModal() {
      $("#uploadChoiceSub").textContent = state.selectedCode
        ? `${projectName(state.selectedProject)} / ${state.selectedCode}`
        : "先选择项目划分，再选择上传类型。";
      $("#uploadProjectSearch").value = "";
      $("#uploadModalResult").style.display = "none";
      $("#uploadModalResult").classList.remove("is-warning");
      setUploadChoiceCategory(state.uploadChoiceCategory || "construction");
      $("#uploadProjectPickerBody").innerHTML = `<div class="unit-image-empty">正在加载单元工程…</div>`;
      await ensureAllProjectsLoaded();
      renderUploadProjectPicker();
      $("#uploadChoiceModal").classList.add("open");
      $("#uploadChoiceModal").setAttribute("aria-hidden", "false");
      setTimeout(() => $("#uploadProjectSearch").focus(), 0);
    }

    function openUnitUpload(category) {
      if (!state.selectedCode || !state.selectedProject) {
        showNotice("请先选择单元工程。", true);
        return;
      }
      category = normalizePhotoCategory(category);
      const form = $(`#${category}UploadForm`);
      if (!form) return;
      const shouldOpen = form.style.display === "none" || !form.style.display;
      photoCategories.forEach(({ key }) => {
        const item = $(`#${key}UploadForm`);
        const button = document.querySelector(`[data-unit-upload="${key}"]`);
        if (!item || !button) return;
        item.style.display = key === category && shouldOpen ? "grid" : "none";
        button.textContent = key === category && shouldOpen ? "收起" : "上传";
      });
      if (shouldOpen) {
        const input = $(`#${category}PhotoFiles`);
        form.scrollIntoView({ behavior: "smooth", block: "nearest" });
        setTimeout(() => input?.focus(), 0);
      }
    }

    function closeUploadChoiceModal() {
      $("#uploadChoiceModal").classList.remove("open");
      $("#uploadChoiceModal").setAttribute("aria-hidden", "true");
    }

    async function focusUploadCategory(category) {
      setUploadChoiceCategory(category);
      closeUploadChoiceModal();
      if (!state.selectedCode) {
        showNotice("请先在项目划分中选择单元工程。", true);
        return;
      }
      await loadProject(state.selectedCode, "detail");
      category = normalizePhotoCategory(category);
      setView("unit");
      document.querySelectorAll(".photo-section").forEach((section) => section.classList.remove("is-target"));
      const input = document.querySelector(`form[data-category="${category}"] input[type=file]`);
      if (!input) return;
      const section = input.closest(".photo-section");
      section.classList.add("is-target");
      section.scrollIntoView({ behavior: "smooth", block: "start" });
      input.focus();
      setTimeout(() => section.classList.remove("is-target"), 1800);
    }

    function normalizeImageFiles(files) {
      return Array.from(files || []).filter((file) => /\.(jpe?g|png)$/i.test(file.name || ""));
    }

    function updateUploadModalFileSummary(files) {
      const allFiles = Array.from(files || $("#uploadModalFiles").files || []);
      const imageFiles = normalizeImageFiles(allFiles);
      const skipped = Math.max(0, allFiles.length - imageFiles.length);
      const summary = $("#uploadModalFileSummary");
      if (!summary) return;
      if (!allFiles.length) {
        summary.textContent = "照片文件名包含单元编码或单元名称时，可自动匹配上传。";
        return;
      }
      summary.textContent = skipped
        ? `已选择 ${imageFiles.length} 张照片，已忽略 ${skipped} 个非 JPG/PNG 文件。`
        : `已选择 ${imageFiles.length} 张照片。`;
    }

    async function uploadFromModal(event, droppedFiles = null) {
      event?.preventDefault();
      if (!state.selectedCode) {
        showNotice("请先在项目划分中选择单元工程。", true);
        return;
      }
      if (!(await ensureAuthenticated("上传照片"))) return;
      const allFiles = droppedFiles ? Array.from(droppedFiles || []) : Array.from($("#uploadModalFiles").files || []);
      const files = normalizeImageFiles(allFiles);
      if (!files.length) {
        showNotice("请选择或拖入 JPG/PNG 照片。", true);
        return;
      }
      const form = new FormData();
      let photoDate = $("#uploadModalDate").value;
      // 日期为空时：先从文件名提取，取不到则提交由后端 EXIF 兜底
      if (!photoDate) {
        const firstFile = files[0];
        if (firstFile) photoDate = parseDateFromName(firstFile.name);
      }
      form.append("category", state.uploadChoiceCategory || "construction");
      form.append("title", $("#uploadModalTitle").value.trim());
      form.append("photo_date", photoDate);
      form.append("photographer", $("#uploadModalPhotographer").value.trim());
      form.append("description", "");
      form.append("orientation", "landscape");
      files.forEach((file) => form.append("files", file));

      const uploadCode = state.selectedCode;
      const data = await apiJson(`/api/upload/${encodeURIComponent(uploadCode)}`, { method: "POST", body: form });
      if (state.selectedCode === uploadCode) state.photos = data.photos || state.photos;
      $("#uploadModalForm").reset();
      updateUploadModalFileSummary([]);
      await refreshAll();
      renderUploadProjectPicker();
      if (state.viewMode === "unit" && state.selectedCode === uploadCode) renderPhotos();
      const result = $("#uploadModalResult");
      result.classList.remove("is-warning");
      result.innerHTML = `
        <span>上传成功，已归档 ${files.length} 张到 ${escapeHtml(uploadCode)}。</span>
        <button class="secondary mini" type="button" id="uploadModalDetailBtn">查看详情</button>
      `;
      result.style.display = "flex";
      $("#uploadModalDetailBtn").addEventListener("click", () => {
        closeUploadChoiceModal();
        loadProject(uploadCode, "detail").catch((error) => showNotice(error.message, true));
      });
      showNotice("照片已上传。");
    }

    async function uploadAutoMatchFromModal() {
      if (!(await ensureAuthenticated("自动匹配上传照片"))) return;
      const allFiles = Array.from($("#uploadModalFiles").files || []);
      const files = normalizeImageFiles(allFiles);
      if (!files.length) {
        showNotice("请选择 JPG/PNG 照片后再自动匹配上传。", true);
        return;
      }
      await previewFolderImport(files, state.uploadChoiceCategory || "construction");
      closeUploadChoiceModal();
      return;
      const form = new FormData();
      let photoDate = $("#uploadModalDate").value;
      // 日期为空时：先从文件名提取，取不到则提交由后端 EXIF 兜底
      if (!photoDate) {
        const firstFile = files[0];
        if (firstFile) photoDate = parseDateFromName(firstFile.name);
      }
      form.append("category", state.uploadChoiceCategory || "construction");
      form.append("title", $("#uploadModalTitle").value.trim());
      form.append("photo_date", photoDate);
      form.append("photographer", $("#uploadModalPhotographer").value.trim());
      form.append("description", "");
      form.append("orientation", "landscape");
      files.forEach((file) => form.append("files", file));

      const data = await apiJson("/api/upload-auto-match", { method: "POST", body: form });
      $("#uploadModalForm").reset();
      updateUploadModalFileSummary([]);
      await refreshAll();
      renderUploadProjectPicker();
      if (state.selectedCode) {
        const refreshed = await apiJson(`/api/photos/${encodeURIComponent(state.selectedCode)}`);
        state.photos = refreshed.photos || state.photos;
        if (state.viewMode === "unit") renderPhotos();
      }
      const unmatched = data.unmatched || [];
      const result = $("#uploadModalResult");
      result.classList.toggle("is-warning", Boolean(unmatched.length));
      result.innerHTML = `
        <span>自动匹配上传成功：${Number(data.added_count || 0)} 张，归档到 ${Number(data.project_count || 0)} 个单元${unmatched.length ? `；未匹配 ${unmatched.length} 张：${escapeHtml(unmatched.slice(0, 5).join("、"))}${unmatched.length > 5 ? "等" : ""}` : "。"}</span>
      `;
      result.style.display = "flex";
      showNotice(unmatched.length ? "已上传匹配成功的照片，未匹配照片未上传。" : "照片已按名称自动匹配上传。", Boolean(unmatched.length));
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
      if (!(await ensureAuthenticated("修改照片信息"))) return;
      const photo = state.photos.find((item) => normalizePhotoCategory(item.category) === normalizePhotoCategory(category) && String(item.id || "") === String(photoId || ""));
      if (!photo) {
        showNotice("未找到要修改的照片。", true);
        return;
      }
      state.editingPhoto = { category: normalizePhotoCategory(category), photoId: String(photoId || "") };
      $("#photoEditTitleInput").value = photo.title || "";
      $("#photoEditDateInput").value = displayPhotoDate(photo) || "";
      $("#photoEditPhotographerInput").value = photo.photographer || "";
      $("#photoEditRotationInput").value = String(Number(photo.rotation || 0) || 0);
      $("#photoEditDescriptionInput").value = photo.description || "";
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
      return state.photos.find((item) => String(item.id || "") === state.editingPhoto.photoId) || null;
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

    async function savePhotoEdit(event) {
      event.preventDefault();
      if (!state.editingPhoto) return;
      if (!(await ensureAuthenticated("修改照片信息"))) return;
      const title = $("#photoEditTitleInput").value.trim();
      const photoDate = $("#photoEditDateInput").value.trim();
      const photographer = $("#photoEditPhotographerInput").value.trim();
      const currentPhoto = state.photos.find((item) => normalizePhotoCategory(item.category) === state.editingPhoto.category && String(item.id || "") === state.editingPhoto.photoId);
      const processName = currentPhoto?.process_name || "";
      const processCode = currentPhoto?.process_code || "";
      const orientation = normalizePhotoOrientation("landscape");
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
      const data = await apiJson(`/api/photos/${encodeURIComponent(state.selectedCode)}/${encodeURIComponent(state.editingPhoto.photoId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title, photo_date: photoDate, photographer, process_name: processName, process_code: processCode, orientation, rotation, description })
      });
      state.photos = data.photos || [];
      closePhotoEdit();
      renderPhotos();
      await refreshAll();
      showNotice("照片信息已修改。");
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

    function togglePhotoSelection(card) {
      const input = card.querySelector("input[data-print-photo]");
      if (!input) return;
      input.checked = !input.checked;
      setPhotoSelected(input.dataset.category, input.dataset.printPhoto, input.checked);
      card.classList.toggle("is-selected", input.checked);
    }

    function selectedPhotosForSection(sectionKey) {
      const section = document.querySelector(`[data-photo-section="${CSS.escape(sectionKey || "")}"]`);
      if (!section) return [];
      return Array.from(section.querySelectorAll("input[data-print-photo]:checked"))
        .map((input) => ({ category: input.dataset.category, photoId: input.dataset.printPhoto }))
        .filter((item) => item.category && item.photoId);
    }

    async function deleteSelectedPhotos(sectionKey) {
      const selected = selectedPhotosForSection(sectionKey);
      if (!selected.length) {
        showNotice("请先勾选要删除的照片。", true);
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
      let latestPhotos = state.photos;
      for (const item of selected) {
        const data = await apiJson(`/api/delete-photo/${encodeURIComponent(state.selectedCode)}/${encodeURIComponent(item.photoId)}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ category: item.category, safety_password: safetyPassword })
        });
        latestPhotos = data.photos || latestPhotos;
        delete state.selectedPrintPhotos[printSelectionKey(item.category, item.photoId)];
      }
      state.photos = latestPhotos || [];
      renderPhotos();
      await refreshAll();
      showNotice(`已删除 ${selected.length} 张照片。`);
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
      await refreshAll();
      showNotice("照片已删除。如需整理编号，请点击重新编号。");
    }

    async function reorderPhoto(category, photoId, direction) {
      if (!state.auth.user) {
        showNotice("请先登录后再调整照片排序。", true);
        return;
      }
      const data = await apiJson(`/api/photos/${encodeURIComponent(state.selectedCode)}/reorder`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ category, photo_id: photoId, direction })
      });
      state.photos = data.photos || [];
      renderPhotos();
      try {
        await renumberCategory(category);
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
      const orderedIds = Array.from(list.querySelectorAll(".photo[data-photo-id]")).map((item) => item.dataset.photoId).filter(Boolean);
      const data = await apiJson(`/api/photos/${encodeURIComponent(state.selectedCode)}/reorder-list`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ category, ordered_ids: orderedIds })
      });
      state.photos = data.photos || [];
      renderPhotos();
      try {
        await renumberCategory(category);
      } catch (error) {
        showNotice("排序已保存，但编号更新失败：" + error.message, true);
        return;
      }
      showNotice("拖拽排序已保存，编号已自动更新。");
    }

    async function renumberCategory(category) {
      const data = await apiJson(`/api/photos/${encodeURIComponent(state.selectedCode)}/renumber`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ category })
      });
      state.photos = data.photos || [];
      state.selectedPrintPhotos = {};
      renderPhotos();
    }

    function initPhotoDragSort(host) {
      let dragged = null;
      host.querySelectorAll(".photo[draggable='true']").forEach((card) => {
        card.addEventListener("dragstart", (event) => {
          // 照片缩略图和标题都包在 button 里，必须允许从 button 上发起拖拽排序，
          // 否则用户抓照片/标题拖不动，编号和缩略图自然不跟着走。
          if (event.target.closest("input, select, textarea, label")) {
            event.preventDefault();
            return;
          }
          dragged = card;
          event.dataTransfer.effectAllowed = "move";
          event.dataTransfer.setData("text/plain", card.dataset.photoId || "");
          setTimeout(() => card.classList.add("is-dragging-sort"), 0);
        });
        card.addEventListener("dragend", () => {
          card.classList.remove("is-dragging-sort");
          host.querySelectorAll(".photo.is-drag-over").forEach((item) => item.classList.remove("is-drag-over"));
          dragged = null;
        });
      });

      host.querySelectorAll(".photos").forEach((list) => {
        list.addEventListener("dragover", (event) => {
          if (!dragged || dragged.parentElement !== list) return;
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
        });
        list.addEventListener("drop", (event) => {
          if (!dragged || dragged.parentElement !== list) return;
          event.preventDefault();
          const category = dragged.dataset.category || list.querySelector(".photo[data-category]")?.dataset.category || "";
          host.querySelectorAll(".photo.is-drag-over").forEach((item) => item.classList.remove("is-drag-over"));
          saveDraggedPhotoOrder(list, category).catch((error) => {
            showNotice(error.message, true);
            renderPhotos();
          });
        });
      });
    }

    async function renumberPhotos() {
      if (!state.selectedCode) {
        showNotice("请先选择单元工程。", true);
        return;
      }
      if (!(await ensureAuthenticated("重新编号"))) return;
      const data = await apiJson(`/api/photos/${encodeURIComponent(state.selectedCode)}/renumber`, { method: "POST" });
      state.photos = data.photos || [];
      state.selectedPrintPhotos = {};
      renderPhotos();
      showNotice("已按当前照片顺序重新编号。");
    }

    async function renumberAllPhotos() {
      if (!(await ensureAuthenticated("整体编号重排"))) return;
      if (!window.confirm("将对当前工程全部单元的照片整体重排：灌注桩单元会先按桩号连体（钻孔→钢筋笼→混凝土）并按施工完成时间排序，再统一重新编号。确定继续吗？")) return;
      try {
        const data = await apiJson("/api/renumber-all", { method: "POST" });
        await refreshAll();
        showNotice(`整体重排完成：共处理 ${data.renumbered || 0} 张照片（${data.project_count || 0} 个单元），灌注桩单元已按桩号连体+施工时间排序。`);
      } catch (error) {
        showNotice(error.message, true);
      }
    }

    // 首屏冷启动加载动画：进度条跟随真实加载阶段推进；加载再快也保证至少显示 1.6 秒走完，页面数据全部显示才消失
    const BOOT_MIN_MS = 1200;
    let bootStartedAt = 0;
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
      bootStart();
      bootProgress(8);
      const data = await apiJson("/api/bootstrap");
      bootProgress(42);
      state.auth.user = data.user || null;
      renderAuth();
      if (!state.auth.user) {
        // 未登录：回填上次记住的账号和密码，方便再次登录
        restoreLoginCredentials();
        bootDone();
        return;
      }
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
          state.selectedPart = updated;
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

    async function refreshAll(options = {}) {
      return loadBootstrap(options);
    }

    async function ensureAllProjectsLoaded() {
      if (state.allProjectsLoaded) return;
      const data = await apiJson("/api/projects?slim=1");
      const selectedPart = state.selectedPart;
      const selectedPartName = selectedPart?.name || "";
      const selectedPartCode = selectedPart?.code || "";
      state.projects = data.projects || [];
      state.allProjectsLoaded = true;
      state.treeRoot = buildTree(state.projects);
      expandAdaptiveTree();
      if (selectedPart) state.selectedPart = findPartNode(selectedPartName, selectedPartCode);
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
      if (!event.target.closest(".support-wrap")) {
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
      } else {
        box.textContent = "未登录";
        form.style.display = "block";
        logoutBtn.style.display = "none";
      }
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
    $("#projectInfoBtn")?.addEventListener("click", openProjectInfoModal);
    $("#closeProjectInfoBtn").addEventListener("click", closeProjectInfoModal);
    $("#cancelProjectInfoBtn").addEventListener("click", closeProjectInfoModal);
    $("#projectInfoForm").addEventListener("submit", (event) => {
      saveProjectInfo(event).catch((error) => showNotice(error.message, true));
    });
    $("#deleteEngineeringProjectBtn").addEventListener("click", () => {
      deleteCurrentEngineeringProject().catch((error) => showNotice(error.message, true));
    });
    document.querySelectorAll("[data-project-settings-tab]").forEach((button) => {
      button.addEventListener("click", () => setProjectSettingsTab(button.dataset.projectSettingsTab));
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
    $("#machineIdBtn").addEventListener("click", () => openMachineIdModal().catch((error) => showNotice(error.message, true)));
    $("#gateMachineIdBtn")?.addEventListener("click", () => openMachineIdModal().catch((error) => showNotice(error.message, true)));
    $("#closeMachineIdBtn").addEventListener("click", closeMachineIdModal);
    $("#copyMachineIdBtn").addEventListener("click", () => copyMachineId().catch((error) => showNotice(error.message, true)));
    $("#openLicensePageBtn").addEventListener("click", () => window.open("/license", "_blank"));
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
    $("#gateRegisterBtn").addEventListener("click", () => { window.location.href = "/license?register=1"; });
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
    $("#cloudRegBtn").addEventListener("click", async () => {
      const user = $("#cloudUser").value.trim();
      const pass = $("#cloudPass").value;
      const invite = $("#cloudInvite").value.trim();
      const email = $("#cloudEmail").value.trim();
      const deletePass = $("#cloudDeletePass").value;
      const deletePassConfirm = $("#cloudDeletePassConfirm").value;
      if (!user || !pass) { showNotice("请输入账号和登录密码", true); return; }
      if (pass.length < 8 || !/[A-Za-z]/.test(pass) || !/\d/.test(pass)) {
        showNotice("登录密码至少 8 位，并同时包含字母和数字。", true);
        return;
      }
      if (deletePass.length < 6) { showNotice("请设置至少 6 位的工程删除密码。", true); return; }
      if (deletePass !== deletePassConfirm) { showNotice("两次输入的工程删除密码不一致。", true); return; }
      try {
        const data = await apiJson("/api/cloud/register", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            username: user,
            password: pass,
            email,
            invite_code: invite,
            delete_password: deletePass,
            delete_password_confirm: deletePassConfirm
          })
        });
        if (!data.ok) { showNotice(data.error || "注册失败", true); return; }
        showNotice("注册成功。工程删除密码已安全保存，请牢记；现在可以登录。 ");
        $("#cloudInvite").value = "";
        $("#cloudEmail").value = "";
        $("#cloudDeletePass").value = "";
        $("#cloudDeletePassConfirm").value = "";
        const projectData = await apiJson("/api/project-info");
        state.projectInfo = projectData.project_info || state.projectInfo;
        state.engineeringProjects = projectData.engineering_projects || state.engineeringProjects;
        state.activeEngineeringProjectId = projectData.active_engineering_project_id || state.activeEngineeringProjectId;
      } catch (e) { showNotice(e.message || "注册失败", true); }
    });
    $("#cloudLogoutBtn").addEventListener("click", async () => {
      try { await apiJson("/api/cloud/logout", { method: "POST" }); } catch (e) {}
      showNotice("已退出云账号");
      loadSharePoints();
    });
    ["gateUsername"].forEach((id) => {
      $(`#${id}`).addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          submitAuth("/api/cloud/login").catch((error) => showNotice(error.message, true));
        }
      });
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
        el.classList.remove("open");
      });
      if (except !== "supportPanel") $("#supportPanel")?.setAttribute("aria-hidden", "true");
    }
    $("#printMenuBtn")?.addEventListener("click", (event) => {
      event.stopPropagation();
      closeTopMenus("printMenu");
      $("#printMenu")?.classList.toggle("open");
    });
    $("#settingsMenuBtn").addEventListener("click", (event) => {
      event.stopPropagation();
      closeTopMenus("settingsMenu");
      $("#settingsMenu").classList.toggle("open");
    });
    $("#actionsMenuBtn").addEventListener("click", (event) => {
      event.stopPropagation();
      closeTopMenus("actionsMenu");
      $("#actionsMenu").classList.toggle("open");
    });
    $("#quickMenuBtn")?.addEventListener("click", (event) => {
      event.stopPropagation();
      closeTopMenus("quickMenu");
      $("#quickMenu")?.classList.toggle("open");
    });
    $("#projectImportMenuBtn").addEventListener("click", (event) => {
      event.stopPropagation();
      $("#importFile").click();
    });
    document.addEventListener("click", (event) => {
      if (!event.target.closest(".print-menu-wrap")) $("#printMenu")?.classList.remove("open");
      if (!event.target.closest(".settings-menu-wrap")) {
        $("#settingsMenu").classList.remove("open");
        $("#actionsMenu").classList.remove("open");
      }
      if (!event.target.closest(".quick-menu-wrap")) $("#quickMenu")?.classList.remove("open");
      if (!event.target.closest(".project-import-wrap")) $("#projectImportMenu").classList.remove("open");
    });
    document.querySelectorAll("#settingsMenu button").forEach((button) => {
      button.addEventListener("click", () => $("#settingsMenu").classList.remove("open"));
    });
    document.querySelectorAll("#actionsMenu button").forEach((button) => {
      button.addEventListener("click", () => $("#actionsMenu").classList.remove("open"));
    });
    document.querySelectorAll("#quickMenu button").forEach((button) => {
      button.addEventListener("click", () => $("#quickMenu")?.classList.remove("open"));
    });
    document.querySelectorAll("#projectImportMenu button").forEach((button) => {
      button.addEventListener("click", () => $("#projectImportMenu").classList.remove("open"));
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
      state.batchSelectedCodes.clear();
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
      openUploadChoiceModal();
    });
    $("#closeUploadChoiceBtn").addEventListener("click", closeUploadChoiceModal);
    $("#uploadProjectSearch").addEventListener("input", renderUploadProjectPicker);
    $("#uploadModalFiles").addEventListener("change", (event) => updateUploadModalFileSummary(event.target.files));
    $("#uploadModalForm").addEventListener("submit", (event) => {
      uploadFromModal(event).catch((error) => showNotice(error.message, true));
    });
    $("#uploadModalForm").addEventListener("paste", (event) => {
      const files = Array.from(event.clipboardData?.files || []);
      if (!files.length) return;
      event.preventDefault();
      uploadFromModal(event, files).catch((error) => showNotice(error.message, true));
    });
    $("#uploadModalForm").addEventListener("paste", (event) => {
      const files = Array.from(event.clipboardData?.files || []);
      if (!files.length) return;
      event.preventDefault();
      uploadFromModal(event, files).catch((error) => showNotice(error.message, true));
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
      updateUploadModalFileSummary(event.dataTransfer.files);
      uploadFromModal(event, event.dataTransfer.files).catch((error) => showNotice(error.message, true));
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
    $("#backOverviewBtn").addEventListener("click", openOverview);
    $("#backPartBtn").addEventListener("click", () => {
      if (state.selectedPart) {
        renderPart();
        setView("part");
      } else {
        openOverview("construction");
      }
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
        $("#importFileLabel").textContent = "选择文件";
        const result = data.result || {};
        showNotice(`自动转换导入完成：成功 ${result.created || 0} 个单元，跳过 ${result.skipped || 0} 行。`);
      } catch (error) {
        showNotice(error.message || "项目划分导入失败。", true);
      }
    });

    $("#importFile").addEventListener("change", () => {
      const file = $("#importFile").files[0];
      $("#importFileLabel").textContent = file ? file.name : "选择文件";
      if (file) $("#importForm").requestSubmit();
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

    function exportSelectedCsv() {
      requireSelected(() => { window.location.href = `/api/export/${encodeURIComponent(state.selectedCode)}/metadata.csv`; });
    }

    function exportSelectedJson() {
      requireSelected(() => { window.location.href = `/api/export/${encodeURIComponent(state.selectedCode)}/metadata.json`; });
    }

    function exportSelectedZip() {
      requireSelected(() => { window.location.href = `/api/export/${encodeURIComponent(state.selectedCode)}/zip`; });
    }

    function setPrintSetupMode(mode) {
      state.printSetupMode = mode === "custom" ? "custom" : "default";
      document.querySelectorAll("[data-print-mode]").forEach((button) => {
        button.classList.toggle("active", button.dataset.printMode === state.printSetupMode);
      });
      $("#printCustomPanel").classList.toggle("open", state.printSetupMode === "custom");
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

    function loadPrintSetupValues() {
      const settings = state.engineeringSettings || {};
      $("#printSetupLayout").value = settings.print_layout || "landscape";
      $("#printSetupPageSize").value = String(settings.print_page_size || 4);
      $("#printSetupPreset").value = settings.print_photo_preset || "5inch";
      $("#printSetupPhotoWidth").value = settings.print_photo_width_cm || 12.7;
      $("#printSetupPhotoHeight").value = settings.print_photo_height_cm || 8.9;
      $("#printSetupCaptionPosition").value = settings.print_caption_position || "bottom";
      $("#printSetupCaptionSize").value = settings.print_caption_size_mm || 7;
      $("#printSetupCaptionFont").value = settings.print_caption_font_size || 7.2;
      $("#printSetupMarginTop").value = settings.print_margin_top_mm ?? 6;
      $("#printSetupMarginRight").value = settings.print_margin_right_mm ?? 6;
      $("#printSetupMarginBottom").value = settings.print_margin_bottom_mm ?? 6;
      $("#printSetupMarginLeft").value = settings.print_margin_left_mm ?? 6;
      $("#printSetupHorizontalGap").value = settings.print_horizontal_gap_mm ?? 2;
      $("#printSetupVerticalGap").value = settings.print_vertical_gap_mm ?? 2;
      $("#printSetupImageFit").value = settings.print_image_fit || "cover";
      $("#printSetupShowPageTitle").value = settings.print_show_page_title === false ? "0" : "1";
      const fields = new Set(settings.print_caption_fields || ["title", "id", "photo_date"]);
      document.querySelectorAll("[data-print-caption-field]").forEach((input) => { input.checked = fields.has(input.value); });
      syncPrintSetupPreset();
    }

    function openPrintSetup(url) {
      state.pendingPrintUrl = url;
      loadPrintSetupValues();
      setPrintSetupMode("default");
      $("#printSetupModal").classList.add("open");
      $("#printSetupModal").setAttribute("aria-hidden", "false");
    }

    function closePrintSetup() {
      $("#printSetupModal").classList.remove("open");
      $("#printSetupModal").setAttribute("aria-hidden", "true");
      state.pendingPrintUrl = "";
    }

    function printSetupParams() {
      if (state.printSetupMode === "default") {
        return new URLSearchParams({
          layout: "landscape", page_size: "4", photo_preset: "5inch",
          caption_position: "bottom", caption_size_mm: "7", caption_font_size: "7.2",
          margin_top_mm: "4", margin_right_mm: "4", margin_bottom_mm: "4", margin_left_mm: "4",
          horizontal_gap_mm: "2", vertical_gap_mm: "2", image_fit: "cover",
          show_page_title: "1", caption_fields: "title,id,photo_date"
        });
      }
      const pageSize = Math.max(1, Math.min(12, Number($("#printSetupPageSize").value || 4)));
      const fields = Array.from(document.querySelectorAll("[data-print-caption-field]:checked")).map((input) => input.value);
      return new URLSearchParams({
        layout: $("#printSetupLayout").value,
        page_size: String(pageSize),
        photo_preset: $("#printSetupPreset").value,
        photo_width_cm: $("#printSetupPhotoWidth").value || "12.7",
        photo_height_cm: $("#printSetupPhotoHeight").value || "8.9",
        caption_position: $("#printSetupCaptionPosition").value,
        caption_size_mm: $("#printSetupCaptionSize").value || "7",
        caption_font_size: $("#printSetupCaptionFont").value || "7.2",
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

    function confirmPrintSetup() {
      if (!state.pendingPrintUrl) return;
      const url = new URL(state.pendingPrintUrl, window.location.origin);
      printSetupParams().forEach((value, key) => url.searchParams.set(key, value));
      const target = `${url.pathname}${url.search}`;
      closePrintSetup();
      window.open(target, "_blank");
    }

    function openUnitPrint(category) {
      requireSelected(() => {
        const url = new URL(`/print/${encodeURIComponent(category)}/${encodeURIComponent(state.selectedCode)}`, window.location.origin);
        const ids = selectedPrintIds(category);
        if (ids.length) url.searchParams.set("ids", ids.join(","));
        openPrintSetup(`${url.pathname}${url.search}`);
      });
    }

    document.querySelectorAll("[data-print-mode]").forEach((button) => button.addEventListener("click", () => setPrintSetupMode(button.dataset.printMode)));
    $("#printSetupPreset").addEventListener("change", syncPrintSetupPreset);
    $("#printSetupCaptionPosition").addEventListener("change", () => {
      const side = ["left", "right"].includes($("#printSetupCaptionPosition").value);
      const current = Number($("#printSetupCaptionSize").value || 0);
      if (side && current < 16) $("#printSetupCaptionSize").value = "32";
      if (!side && current > 20) $("#printSetupCaptionSize").value = "7";
    });
    $("#closePrintSetupBtn").addEventListener("click", closePrintSetup);
    $("#cancelPrintSetupBtn").addEventListener("click", closePrintSetup);
    $("#confirmPrintSetupBtn").addEventListener("click", confirmPrintSetup);
    $("#printSetupModal").addEventListener("click", (event) => { if (event.target.id === "printSetupModal") closePrintSetup(); });

    $("#printConstructionBtn").addEventListener("click", () => openUnitPrint("construction"));
    $("#printSupervisionBtn").addEventListener("click", () => openUnitPrint("supervision"));
    $("#menuPrintConstructionBtn").addEventListener("click", () => openBatchPrint("construction", "print"));
    $("#menuPrintSupervisionBtn").addEventListener("click", () => openBatchPrint("supervision", "print"));
    $("#renumberAllBtn").addEventListener("click", renumberAllPhotos);
    $("#exportZipBtn").addEventListener("click", exportSelectedZip);
    $("#deleteUnitBtn").addEventListener("click", () => deleteUnit().catch((error) => showNotice(error.message, true)));
    $("#exportPhotoStatsBtn").addEventListener("click", () => { window.location.href = "/api/export/photo-statistics.xlsx"; });
    $("#exportUnitStatsBtn").addEventListener("click", () => requireSelected(() => { window.location.href = `/api/export/photo-statistics.xlsx?codes=${encodeURIComponent(state.selectedCode)}`; }));
    $("#settingsProjectInfoBtn").addEventListener("click", openProjectInfoModal);
    $("#settingsExportCsvBtn").addEventListener("click", exportSelectedCsv);
    $("#settingsExportJsonBtn").addEventListener("click", exportSelectedJson);

    setView("overview");
    const startupUnitCode = routeUnitCode();
    // 启动后静默检查更新（有新版本才提示）
    setTimeout(() => checkForUpdate(false).catch(() => {}), 5000);
    loadBootstrap({ skipOtherImages: true }).then(() => {
      if (!state.auth.user) return;
      if (startupUnitCode) {
        loadProject(startupUnitCode, "detail").catch((error) => showNotice(error.message, true));
      }
    }).catch((error) => showNotice(error.message, true));
