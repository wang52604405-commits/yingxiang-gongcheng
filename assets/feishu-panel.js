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
    .fp-box { width: min(1200px, 96vw); height: min(88vh, 780px); min-height: 400px; background: #fff;
      border-radius: 14px; overflow: hidden; display: flex; flex-direction: column;
      box-shadow: 0 30px 70px rgba(0,0,0,.35); font-family: "Microsoft YaHei",sans-serif; }
    .fp-head { display: flex; align-items: center; justify-content: space-between;
      padding: 16px 20px; border-bottom: 1px solid #e8ebf0; flex: 0 0 auto; }
    .fp-head h3 { margin: 0; font-size: 16px; color: #1f2d3d; }
    .fp-close { border: none; background: #f2f4f7; color: #555; width: 30px; height: 30px;
      border-radius: 50%; cursor: pointer; font-size: 16px; }
    .fp-body { padding: 16px 20px; overflow: hidden; flex: 1 1 auto; min-height: 0;
      display: flex; flex-direction: column; }
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
      border-bottom: 1px solid #e3e7ee; position: sticky; top: 0; z-index: 1; }
    .fp-table td { padding: 8px 10px; border-bottom: 1px solid #f0f2f6; color: #333; white-space: nowrap; }
    .fp-table tr:hover td { background: #eaf2ff; }
    .fp-table-scroll { flex: 1 1 auto; min-height: 0; overflow: auto; border: 1px solid #e8ebf0;
      border-radius: 8px; }
    .fp-toolbar { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; flex: 0 0 auto; }
    .fp-search { flex: 1 1 auto; box-sizing: border-box; padding: 8px 12px;
      border: 1px solid #d9dee7; border-radius: 8px; font-size: 13px; min-width: 0; }
    .fp-search:focus { outline: none; border-color: #3370ff; box-shadow: 0 0 0 3px rgba(51,112,255,.12); }
    .fp-empty { text-align: center; color: #9aa3b0; padding: 30px 0; font-size: 13px; }
    .fp-loading { text-align: center; color: #9aa3b0; padding: 20px 0; font-size: 13px; }
    .fp-fab .fp-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%;
      margin-right: 8px; background: #9aa3b0; vertical-align: middle; }
    .fp-fab .fp-dot.ok { background: #22c55e; box-shadow: 0 0 6px rgba(34,197,94,.7); }
    .fp-tip { font-size: 12px; color: #8a919c; margin: 10px 0 4px; line-height: 1.7; }
    .fp-toast { position: fixed; top: 18px; left: 50%; transform: translateX(-50%);
      z-index: 10001; background: rgba(20,30,45,.92); color: #fff; padding: 10px 18px;
      border-radius: 10px; font-size: 13px; font-family: "Microsoft YaHei",sans-serif;
      box-shadow: 0 8px 24px rgba(0,0,0,.3); opacity: 0; transition: opacity .25s; pointer-events: none; }
    .fp-toast.show { opacity: 1; }
  `;
  document.head.appendChild(style);

  function el(tag, attrs, text) {
    var n = document.createElement(tag);
    if (attrs) for (var k in attrs) n.setAttribute(k, attrs[k]);
    if (text != null) n.textContent = text;
    return n;
  }

  function showToast(text) {
    var t = document.querySelector(".fp-toast");
    if (!t) {
      t = el("div", { class: "fp-toast" });
      document.body.appendChild(t);
    }
    t.textContent = text;
    t.classList.add("show");
    clearTimeout(t._timer);
    t._timer = setTimeout(function () { t.classList.remove("show"); }, 2800);
  }

  (function () {
    var origFetch = window.fetch;
    if (!origFetch) return;
    window.fetch = function () {
      var url = arguments[0] && arguments[0].url ? arguments[0].url : String(arguments[0] || "");
      return origFetch.apply(this, arguments).then(function (resp) {
        try {
          if (/\/api\/upload/.test(url) && resp.ok) {
            resp.clone().json().then(function (data) {
              if (data && data.ok && data.added && data.added.length) {
                api("/api/feishu/status").then(function (s) {
                  if (s.configured) {
                    showToast("照片已同步至飞书台账（" + data.added.length + " 张）");
                    var dot = document.querySelector(".fp-fab .fp-dot");
                    if (dot) dot.className = "fp-dot ok";
                  }
                });
              }
            }).catch(function () {});
          }
        } catch (e) {}
        return resp;
      });
    };
  })();

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
    cfgWrap.style.display = "none";
    var enChk = el("input", { type: "checkbox" });
    var tokenInput = el("input", { type: "text", placeholder: "多维表格 app_token（自动填充，一般无需改）" });
    var tableInput = el("input", { type: "text", placeholder: "table_id（自动填充，一般无需改）" });
    var statusEl = el("span", { class: "fp-status" }, "加载中…");
    var shareUrl = "";
    var shareBtn = el("button", { class: "fp-btn ghost", type: "button" }, "远程查看（手机可开）");
    shareBtn.style.display = "none";
    shareBtn.onclick = function () { if (shareUrl) window.open(shareUrl, "_blank"); };

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
    var tipRow = el("div");
    tipRow.appendChild(shareBtn);
    tipRow.appendChild(el("span", { class: "fp-tip" },
      "  照片上传后自动同步到本客户台账；在外地时点“远程查看”，手机打开飞书链接即可看到本表。"));
    body.appendChild(cfgWrap);
    body.appendChild(tipRow);

    // 顶部工具条：全量同步 + 设置(收起配置) + 搜索，台账表格直接满铺显示
    var toolBar = el("div", { class: "fp-toolbar" });
    var syncBtn = el("button", { class: "fp-btn", type: "button" }, "全量同步");
    syncBtn.onclick = function () {
      syncBtn.textContent = "同步中…";
      syncBtn.disabled = true;
      api("/api/feishu/sync-all", { method: "POST" }).then(function (r) {
        syncBtn.textContent = "全量同步";
        syncBtn.disabled = false;
        if (r && r.ok) {
          showToast("同步完成：新增 " + (r.synced || 0) + " 条，已存在 " + (r.skipped || 0) + " 条，失败 " + (r.failed || 0) + " 条");
          refreshRecords();
        } else {
          showToast((r && r.error) || "同步失败", true);
        }
      }).catch(function () {
        syncBtn.textContent = "全量同步";
        syncBtn.disabled = false;
        showToast("同步失败：接口不可用", true);
      });
    };
    toolBar.appendChild(syncBtn);
    var settingsBtn = el("button", { class: "fp-btn ghost", type: "button" }, "设置");
    settingsBtn.onclick = function () {
      var show = cfgWrap.style.display === "none";
      cfgWrap.style.display = show ? "grid" : "none";
      tipRow.style.display = show ? "" : "none";
      settingsBtn.textContent = show ? "收起设置" : "设置";
    };
    toolBar.appendChild(settingsBtn);
    var tableSearch = el("input", { type: "text", class: "fp-search", placeholder: "搜索：编码 / 单元 / 题名 / 编号…" });
    tableSearch.oninput = function () { renderTable(allRows || []); };
    toolBar.appendChild(tableSearch);
    body.appendChild(toolBar);
    var tableScroll = el("div", { class: "fp-table-scroll" });
    var tableWrap = el("div");
    tableScroll.appendChild(tableWrap);
    body.appendChild(tableScroll);

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
        shareUrl = s.share_url || "";
        shareBtn.style.display = s.configured && shareUrl ? "" : "none";
      }).catch(function () {
        statusEl.className = "fp-status bad";
        statusEl.textContent = "接口不可用";
      });
    }

    var allRows = [];
    var sortCol = "";
    var sortDir = 1;
    function renderTable(rows) {
      var kw = (tableSearch.value || "").trim().toLowerCase();
      var filtered = rows;
      if (kw) {
        filtered = (rows || []).filter(function (row) {
          return cols.some(function (c) {
            var v = row[c];
            return v != null && String(v).toLowerCase().indexOf(kw) >= 0;
          });
        });
      }
      if (!filtered || !filtered.length) {
        tableWrap.innerHTML = '<div class="fp-empty">' + (kw ? "没有匹配的记录。" : "台账暂无记录（上传照片后自动同步到这里）") + "</div>";
        return;
      }
      var t = el("table", { class: "fp-table" });
      var thead = el("thead");
      var tr = el("tr");
      cols.forEach(function (c) {
        var th = el("th", null, c);
        th.style.cursor = "pointer";
        th.title = "点击按此列排序";
        th.onclick = function () {
          var dir = sortCol === c ? (sortDir === 1 ? -1 : 1) : 1;
          sortCol = c; sortDir = dir;
          var sorted = (allRows || []).slice();
          sorted.sort(function (a, b) {
            var av = a[c], bv = b[c];
            if (typeof av === "number" && typeof bv === "number") return (av - bv) * dir;
            return String(av == null ? "" : av).localeCompare(String(bv == null ? "" : bv), "zh-CN") * dir;
          });
          renderTable(sorted);
        };
        tr.appendChild(th);
      });
      thead.appendChild(tr);
      t.appendChild(thead);
      var tbody = el("tbody");
      filtered.forEach(function (row) {
        var r = el("tr");
        r.style.cursor = "pointer";
        r.title = "点击打开对应单元";
        cols.forEach(function (c) {
          var v = row[c];
          if (c === "拍摄时间" && typeof v === "number") {
            v = new Date(v).toLocaleString("zh-CN", { hour12: false });
          }
          r.appendChild(el("td", null, v == null ? "" : String(v)));
        });
        r.onclick = function () {
          var code = row["项目编码"] || row["project_code"] || "";
          if (!code) return;
          var maskEl = mask;
          try { if (maskEl && maskEl.parentNode) maskEl.parentNode.removeChild(maskEl); } catch (e) {}
          if (typeof loadProject === "function") {
            loadProject(code, "detail").catch(function (err) { if (window.showNotice) showNotice(err && err.message || "打开失败", true); });
          } else if (window.location) {
            window.location.href = "/?unit=" + encodeURIComponent(code);
          }
        };
        tbody.appendChild(r);
      });
      t.appendChild(tbody);
      tableWrap.innerHTML = "";
      tableWrap.appendChild(t);
    }

    var cols = ["项目编码", "单元工程", "照片编号", "题名", "拍摄者", "拍摄时间", "照片说明"];
    function refreshRecords() {
      tableWrap.innerHTML = '<div class="fp-loading">加载台账…</div>';
      api("/api/feishu/records").then(function (r) {
        if (r.ok) {
          allRows = r.rows || [];
          renderTable(allRows);
        } else {
          tableWrap.innerHTML = '<div class="fp-empty">' + (r.error || "读取失败") + "</div>";
        }
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

    var refreshBtn = el("button", { class: "fp-btn ghost", type: "button" }, "刷新台账");
    refreshBtn.style.marginLeft = "8px";
    refreshBtn.onclick = refreshRecords;
    cfgWrap.appendChild(refreshBtn);

    refreshStatus();
    refreshRecords();
  }

  function init() {
    var fab = el("button", { class: "fp-fab" });
    fab.appendChild(el("span", { class: "fp-dot" }));
    fab.appendChild(document.createTextNode("飞书台账"));
    fab.onclick = openPanel;
    document.body.appendChild(fab);
    api("/api/feishu/status").then(function (s) {
      var dot = fab.querySelector(".fp-dot");
      if (dot && s.configured) dot.className = "fp-dot ok";
    }).catch(function () {});
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
