/* 工程影像管理平台 - 飞书台账面板（独立加载，不依赖主前端构建） */
(function () {
  if (window.__feishuPanelLoaded) return;
  window.__feishuPanelLoaded = true;

  var style = document.createElement("style");
  style.textContent = `
    .fp-fab { position: fixed; right: 24px; bottom: 24px; z-index: 9999;
      background: linear-gradient(135deg,#3370ff,#3370ff); color:#fff; border:none;
      border-radius: 999px; padding: 12px 20px; font-size: 14px; font-weight: 600;
      box-shadow: 0 8px 20px rgba(51,112,255,.35); cursor: pointer;
      font-family: "Microsoft YaHei",sans-serif; }
    .fp-fab:hover { transform: translateY(-2px); box-shadow: 0 12px 26px rgba(51,112,255,.45); }
    .fp-mask { position: fixed; inset: 0; z-index: 10000; background: rgba(15,23,42,.55);
      display: flex; align-items: center; justify-content: center; }
    .fp-box { width: min(920px, 92vw); max-height: 86vh; background: #fff; border-radius: 14px;
      overflow: hidden; display: flex; flex-direction: column; box-shadow: 0 30px 70px rgba(0,0,0,.35);
      font-family: "Microsoft YaHei",sans-serif; }
    .fp-head { display: flex; align-items: center; justify-content: space-between;
      padding: 16px 20px; border-bottom: 1px solid #e8ebf0; }
    .fp-head h3 { margin: 0; font-size: 16px; color: #1f2d3d; }
    .fp-close { border: none; background: #f2f4f7; color: #555; width: 30px; height: 30px;
      border-radius: 50%; cursor: pointer; font-size: 16px; }
    .fp-body { padding: 16px 20px; overflow: auto; }
    .fp-config { display: grid; grid-template-columns: auto 1fr auto; gap: 10px 12px;
      align-items: center; margin-bottom: 14px; padding: 14px; background: #f7f9fc;
      border-radius: 10px; font-size: 13px; color: #333; }
    .fp-config input[type=text] { padding: 7px 10px; border: 1px solid #d9dee7;
      border-radius: 7px; font-size: 13px; width: 100%; box-sizing: border-box; }
    .fp-btn { border: none; padding: 8px 16px; border-radius: 8px; cursor: pointer;
      font-size: 13px; background: #3370ff; color: #fff; }
    .fp-btn.ghost { background: #fff; color: #3370ff; border: 1px solid #3370ff; }
    .fp-status { font-size: 12px; color: #8a919c; }
    .fp-status.ok { color: #16a34a; }
    .fp-status.bad { color: #dc2626; }
    .fp-table { width: 100%; border-collapse: collapse; font-size: 13px; }
    .fp-table th { background: #f2f4f7; color: #55606e; text-align: left; padding: 9px 10px;
      border-bottom: 1px solid #e3e7ee; position: sticky; top: 0; }
    .fp-table td { padding: 8px 10px; border-bottom: 1px solid #f0f2f6; color: #333; }
    .fp-table tr:hover td { background: #f8faff; }
    .fp-empty { text-align: center; color: #9aa3b0; padding: 30px 0; font-size: 13px; }
    .fp-loading { text-align: center; color: #9aa3b0; padding: 20px 0; font-size: 13px; }
  `;
  document.head.appendChild(style);

  function el(tag, attrs, text) {
    var n = document.createElement(tag);
    if (attrs) for (var k in attrs) n.setAttribute(k, attrs[k]);
    if (text != null) n.textContent = text;
    return n;
  }

  function api(path, opts) {
    return fetch(path, opts).then(function (r) { return r.json(); });
  }

  function openPanel() {
    var mask = el("div", { class: "fp-mask" });
    var box = el("div", { class: "fp-box" });
    var head = el("div", { class: "fp-head" });
    head.appendChild(el("h3", null, "飞书台账"));
    var closeBtn = el("button", { class: "fp-close" }, "×");
    closeBtn.onclick = function () { document.body.removeChild(mask); };
    head.appendChild(closeBtn);

    var body = el("div", { class: "fp-body" });
    var cfgWrap = el("div", { class: "fp-config" });
    var enChk = el("input", { type: "checkbox" });
    var tokenInput = el("input", { type: "text", placeholder: "多维表格 app_token（自动填充，一般无需改）" });
    var tableInput = el("input", { type: "text", placeholder: "table_id（自动填充，一般无需改）" });
    var statusEl = el("span", { class: "fp-status" }, "加载中…");

    cfgWrap.appendChild(el("span", null, "启用同步"));
    cfgWrap.appendChild(enChk);
    cfgWrap.appendChild(statusEl);
    cfgWrap.appendChild(el("span", null, "app_token"));
    cfgWrap.appendChild(tokenInput);
    cfgWrap.appendChild(el("span"));
    cfgWrap.appendChild(el("span", null, "table_id"));
    cfgWrap.appendChild(tableInput);
    var saveBtn = el("button", { class: "fp-btn", type: "button" }, "保存配置");
    cfgWrap.appendChild(saveBtn);
    body.appendChild(cfgWrap);

    var tableWrap = el("div");
    body.appendChild(tableWrap);

    mask.appendChild(box);
    box.appendChild(head);
    box.appendChild(body);
    document.body.appendChild(mask);

    function refreshStatus() {
      api("/api/feishu/status").then(function (s) {
        enChk.checked = !!s.enabled;
        tokenInput.value = s.app_token || "";
        tableInput.value = s.table_id || "";
        statusEl.className = "fp-status " + (s.configured ? "ok" : "bad");
        statusEl.textContent = s.configured ? "已配置并启用" : "未配置";
      }).catch(function () {
        statusEl.className = "fp-status bad";
        statusEl.textContent = "接口不可用";
      });
    }

    function renderTable(rows) {
      if (!rows || !rows.length) {
        tableWrap.innerHTML = '<div class="fp-empty">台账暂无记录（上传照片后自动同步到这里）</div>';
        return;
      }
      var cols = ["项目编码", "单元工程", "照片编号", "题名", "拍摄者", "拍摄时间", "照片说明"];
      var t = el("table", { class: "fp-table" });
      var thead = el("thead");
      var tr = el("tr");
      cols.forEach(function (c) { tr.appendChild(el("th", null, c)); });
      thead.appendChild(tr);
      t.appendChild(thead);
      var tbody = el("tbody");
      rows.forEach(function (row) {
        var r = el("tr");
        cols.forEach(function (c) {
          var v = row[c];
          if (c === "拍摄时间" && typeof v === "number") {
            v = new Date(v).toLocaleString("zh-CN", { hour12: false });
          }
          r.appendChild(el("td", null, v == null ? "" : String(v)));
        });
        tbody.appendChild(r);
      });
      t.appendChild(tbody);
      tableWrap.innerHTML = "";
      tableWrap.appendChild(t);
    }

    function refreshRecords() {
      tableWrap.innerHTML = '<div class="fp-loading">加载台账…</div>';
      api("/api/feishu/records").then(function (r) {
        if (r.ok) renderTable(r.rows);
        else tableWrap.innerHTML = '<div class="fp-empty">' + (r.error || "读取失败") + "</div>";
      }).catch(function () {
        tableWrap.innerHTML = '<div class="fp-empty">读取失败：接口不可用</div>';
      });
    }

    saveBtn.onclick = function () {
      api("/api/feishu/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          enabled: enChk.checked,
          app_token: tokenInput.value,
          table_id: tableInput.value
        })
      }).then(function (r) {
        statusEl.className = "fp-status " + (r.configured ? "ok" : "bad");
        statusEl.textContent = r.configured ? "已配置并启用" : "未配置";
        if (r.configured) refreshRecords();
      });
    };

    refreshStatus();
    refreshRecords();
  }

  function init() {
    var fab = el("button", { class: "fp-fab" }, "飞书台账");
    fab.onclick = openPanel;
    document.body.appendChild(fab);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
