(function () {
  "use strict";

  var BASE = "/mh/api";
  var busy = false;
  var LAST_SEARCH = null;
  var QUEUED_SEARCH = null;
  var scoreTimer = null;
  var SCORE_KIND = "text";
  var SCORE_PRESETS = { text: [0.03, 0.055, 0.08, 0.12, 0.18], image: [0.65, 0.75, 0.82, 0.90, 0.95] };
  var TOP_PRESETS = [24, 48, 100];
  var PAGE_PATH = "/mh";
  var PAGE_QUERY = null;
  var GIF_INFO = null;
  var SEARCH_ITEMS = Object.create(null);
  var SEARCH_SELECTED = Object.create(null);
  var SEARCH_DELETED = Object.create(null);
  var SEARCH_BUSY = false;
  var PM = {
    cfg: null,
    chats: [],
    loaded: false,
    loading: false,
    records: [],
    selected: Object.create(null),
    page: 1,
    pages: 1,
    total: 0,
    querySeq: 0,
    timer: null,
    indexTimer: null
  };

  function enforceDefaultSort() {
    var path = location.pathname.replace(/\/+$/, "");
    if (path !== "/scenes" && path !== "/images") return;
    var url = new URL(location.href);
    var initialized = sessionStorage.getItem("mh_sort_init");
    if (!initialized) {
      sessionStorage.setItem("mh_sort_init", "1");
      if (url.searchParams.get("sortby") === "path" && !url.searchParams.has("c")) {
        url.searchParams.set("sortby", "filesize");
        url.searchParams.set("sortdir", "desc");
        location.replace(url.pathname + "?" + url.searchParams.toString() + url.hash);
        return;
      }
    }
    if (url.searchParams.has("sortby")) return;
    url.searchParams.set("sortby", "filesize");
    url.searchParams.set("sortdir", "desc");
    location.replace(url.pathname + "?" + url.searchParams.toString() + url.hash);
  }

  function ensureStyle() {
    if (document.getElementById("mh-style")) return;
    var style = document.createElement("style");
    style.id = "mh-style";
    style.textContent = [
      "#mh-search-btn,#mh-sim-btn,#mh-pm-btn{position:fixed;z-index:2147483647;color:#fff;background:#1f6feb;",
      "border:0;border-radius:8px;padding:10px 14px;font-size:14px;font-weight:600;cursor:pointer;",
      "box-shadow:0 4px 16px rgba(0,0,0,.35)}",
      "#mh-search-btn{left:22px;bottom:22px}",
      "#mh-pm-btn{left:22px;bottom:70px;background:#238636}",
      "#mh-sim-btn{right:22px;bottom:22px}",
      "#mh-backdrop{display:none;position:fixed;inset:0;z-index:2147483646;background:rgba(0,0,0,.72)}",
      "#mh-backdrop.open{display:flex;align-items:center;justify-content:center}",
      "#mh-panel{width:min(1080px,94vw);max-height:88vh;display:flex;flex-direction:column;",
      "background:#202b33;color:#d7dde2;border:1px solid #3b4a55;border-radius:12px;overflow:hidden;",
      "box-shadow:0 18px 60px rgba(0,0,0,.6);font:14px/1.4 system-ui,-apple-system,Segoe UI,sans-serif}",
      "#mh-head{display:flex;align-items:center;gap:10px;padding:14px 18px;background:#172027;",
      "border-bottom:1px solid #3b4a55}",
      "#mh-head strong{font-size:16px;color:#fff;flex:1}",
      "#mh-close{background:transparent;border:0;color:#9fb0bd;font-size:24px;line-height:1;cursor:pointer}",
      "#mh-tools{display:flex;gap:8px;padding:12px 18px;border-bottom:1px solid #33414b}",
      "#mh-q{flex:1;min-width:80px;background:#11181d;color:#e7edf2;border:1px solid #40515e;",
      "border-radius:7px;padding:9px 11px;font-size:14px;outline:none}",
      "#mh-go{background:#238636;color:#fff;border:0;border-radius:7px;padding:9px 16px;cursor:pointer;",
      "font-weight:600}",
      "#mh-status{padding:8px 18px;color:#9fb0bd;min-height:20px}",
      "#mh-results{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;",
      "padding:0 18px 18px;overflow:auto}",
      ".mh-card{background:#11181d;border:1px solid #33414b;border-radius:8px;overflow:hidden;",
      "color:#cfd8df;text-decoration:none;display:block;min-height:90px}",
      ".mh-card img{display:block;width:100%;height:150px;object-fit:cover;background:#0b1014}",
      ".mh-card span{display:block;padding:6px 8px;font-size:12px;color:#9fb0bd;white-space:nowrap;",
      "overflow:hidden;text-overflow:ellipsis}",
      ".mh-card:hover{border-color:#58a6ff}",
      "#mh-note{padding:0 18px 12px;color:#8b9aa6;font-size:12px}",
      "#mh-pm-backdrop{display:none;position:fixed;inset:0;z-index:2147483646;background:rgba(0,0,0,.78)}",
      "#mh-pm-backdrop.open{display:flex;align-items:center;justify-content:center}",
      "#mh-pm-panel{width:min(1560px,97vw);height:92vh;display:flex;flex-direction:column;background:#161d24;",
      "color:#d7dde2;border:1px solid #3b4a55;border-radius:12px;overflow:hidden;",
      "box-shadow:0 18px 60px rgba(0,0,0,.65);font:13px/1.4 system-ui,-apple-system,Segoe UI,sans-serif}",
      "#mh-pm-head{display:flex;align-items:center;gap:12px;padding:12px 16px;background:#111820;border-bottom:1px solid #33414b}",
      "#mh-pm-head strong{font-size:15px;color:#fff}",
      "#mh-pm-head .mh-pm-status{flex:1;color:#9fb0bd;font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}",
      "#mh-pm-x{background:transparent;border:0;color:#9fb0bd;font-size:24px;line-height:1;cursor:pointer}",
      "#mh-pm-top{display:flex;flex-wrap:wrap;gap:7px;align-items:center;padding:9px 14px;background:#151f27;border-bottom:1px solid #2b3944}",
      "#mh-pm-top select,#mh-pm-top input,#mh-pm-top button{background:#0f161c;color:#dbe3ea;border:1px solid #3b4a57;border-radius:6px;padding:6px 8px;font-size:12px}",
      "#mh-pm-top input{outline:none}",
      "#mh-pm-top button{cursor:pointer;background:#1f6feb;border-color:#1f6feb;color:#fff;font-weight:600}",
      "#mh-pm-top button.gray{background:#26333f;border-color:#3b4a57}",
      "#mh-pm-body{display:flex;flex:1;min-height:0}",
      "#mh-pm-side{width:270px;min-width:230px;display:flex;flex-direction:column;border-right:1px solid #2b3944;background:#131b22}",
      "#mh-pm-side .mh-pm-sidebar{padding:8px;display:flex;flex-direction:column;gap:6px;border-bottom:1px solid #26323d}",
      "#mh-pm-side input,#mh-pm-side select{background:#0f161c;color:#dbe3ea;border:1px solid #3b4a57;border-radius:6px;padding:6px 8px;font-size:12px}",
      "#mh-pm-chats{flex:1;overflow:auto;padding:4px 8px 10px}",
      ".mh-pm-chat{display:flex;gap:7px;align-items:flex-start;padding:4px 3px;border-radius:5px;cursor:pointer}",
      ".mh-pm-chat:hover{background:#1b2731}",
      ".mh-pm-chat input{margin-top:2px;flex:0 0 auto}",
      ".mh-pm-chat span{word-break:break-all;color:#c4d0da;font-size:12px}",
      ".mh-pm-chat em{color:#7f919f;font-style:normal;font-size:11px}",
      ".mh-pm-check{display:flex;align-items:center;gap:6px;color:#aab8c4;font-size:12px;padding:2px 0}",
      "#mh-pm-main{flex:1;display:flex;flex-direction:column;min-width:0}",
      "#mh-pm-tools{display:flex;flex-wrap:wrap;align-items:center;gap:6px;padding:8px 12px;border-bottom:1px solid #2b3944;background:#141d25}",
      "#mh-pm-tools button{background:#26333f;color:#e2e9ef;border:1px solid #3b4a57;border-radius:6px;padding:6px 10px;cursor:pointer;font-size:12px}",
      "#mh-pm-tools button.blue{background:#1f6feb;border-color:#1f6feb;color:#fff;font-weight:600}",
      "#mh-pm-tools button.red{background:#8b2f2f;border-color:#a44141;color:#fff}",
      "#mh-pm-tools button:disabled{opacity:.45;cursor:not-allowed}",
      "#mh-pm-tools .mh-pm-count{color:#9fb0bd;font-size:12px;margin-left:auto}",
      "#mh-pm-grid{flex:1;overflow:auto;display:grid;grid-template-columns:repeat(auto-fill,minmax(155px,1fr));gap:9px;padding:10px 12px;align-content:start}",
      ".mh-pm-card{position:relative;background:#0f161c;border:1px solid #2d3b47;border-radius:8px;overflow:hidden;min-height:120px;cursor:pointer}",
      ".mh-pm-card.sel{border-color:#58a6ff;box-shadow:0 0 0 1px #58a6ff inset}",
      ".mh-pm-card img{display:block;width:100%;height:150px;object-fit:cover;background:#0a0f13}",
      ".mh-pm-card .mh-pm-chk{position:absolute;left:6px;top:6px;width:16px;height:16px;z-index:2;cursor:pointer}",
      ".mh-pm-card .mh-pm-meta{padding:6px 7px;font-size:11px;color:#9fb0bd;line-height:1.35}",
      ".mh-pm-card .mh-pm-name{color:#dbe4eb;font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}",
      ".mh-pm-card .mh-pm-sub{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}",
      ".mh-pm-card .mh-pm-tag{display:inline-block;margin-top:3px;padding:1px 5px;border-radius:4px;background:#23313d;color:#9fc2e0;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}",
      ".mh-pm-empty{grid-column:1/-1;color:#8394a2;text-align:center;padding:60px 10px}",
      "#mh-pm-pager{display:flex;align-items:center;justify-content:center;gap:10px;padding:8px;border-top:1px solid #2b3944;background:#141d25;font-size:12px;color:#aab8c4}",
      "#mh-pm-pager button{background:#26333f;color:#e2e9ef;border:1px solid #3b4a57;border-radius:6px;padding:5px 10px;cursor:pointer}",
      "#mh-pm-preview{display:none;position:fixed;inset:0;z-index:2147483647;background:rgba(0,0,0,.88);align-items:center;justify-content:center}",
      "#mh-pm-preview.open{display:flex}",
      "#mh-pm-preview-box{max-width:94vw;max-height:94vh;display:flex;flex-direction:column;gap:8px;align-items:center}",
      "#mh-pm-preview-box img{max-width:94vw;max-height:84vh;object-fit:contain;background:#000;border-radius:6px}",
      "#mh-pm-preview-meta{color:#cfd8df;font-size:13px;text-align:center;max-width:90vw;word-break:break-all}",
      "#mh-pm-preview-actions{display:flex;gap:8px}",
      "#mh-pm-preview-actions button{background:#26333f;color:#fff;border:1px solid #4a5b69;border-radius:6px;padding:7px 12px;cursor:pointer}"
    ].join("");
    document.head.appendChild(style);
  }

  // ---------- similarity modal ----------
  function ensureModal() {
    if (document.getElementById("mh-backdrop")) return;
    ensureStyle();
    var wrap = document.createElement("div");
    wrap.id = "mh-backdrop";
    wrap.innerHTML =
      '<div id="mh-panel">' +
      '<div id="mh-head"><strong id="mh-title">MineHub 搜索</strong>' +
      '<button id="mh-close" title="关闭">×</button></div>' +
      '<div id="mh-tools"><input id="mh-q" placeholder="中文/英文描述搜图，回车搜索">' +
      '<button id="mh-go">搜索</button></div>' +
      '<div id="mh-status"></div><div id="mh-results"></div>' +
      '<div id="mh-note">结果来自本地 MineHub SigLIP2 索引；点击卡片进入 MineHub 详情。</div>' +
      '</div>';
    document.body.appendChild(wrap);
    var box = document.getElementById("mh-backdrop");
    document.getElementById("mh-close").onclick = close;
    document.getElementById("mh-go").onclick = searchText;
    document.getElementById("mh-q").onkeydown = function (e) {
      if (e.key === "Enter") searchText();
    };
    box.addEventListener("click", function (e) { if (e.target === box) close(); });
  }

  function setStatus(text) {
    var el = document.getElementById("mh-status");
    if (el) el.textContent = text || "";
  }

  function close() {
    var box = document.getElementById("mh-backdrop");
    if (box) box.classList.remove("open");
  }

  
  function scoreValue() {
    var el = document.getElementById("mh-min-score");
    var n = el ? parseFloat(el.value) : 0;
    return Number.isFinite(n) ? n : 0;
  }

  function updateScoreLabel() {
    var el = document.getElementById("mh-min-score-val");
    if (el) el.textContent = scoreValue().toFixed(3);
  }

  function renderScorePresets() {
    var box = document.getElementById("mh-score-presets");
    if (!box) return;
    var values = SCORE_PRESETS[SCORE_KIND] || SCORE_PRESETS.text;
    var current = scoreValue();
    box.textContent = "";
    values.forEach(function (v) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "mh-preset" + (Math.abs(v - current) < 0.0001 ? " active" : "");
      b.textContent = v.toFixed(3);
      b.onclick = function () { setScoreValue(v); };
      box.appendChild(b);
    });
  }

  function setScoreValue(value) {
    var el = document.getElementById("mh-min-score");
    if (!el) return;
    var min = parseFloat(el.min);
    var max = parseFloat(el.max);
    var v = Math.max(min, Math.min(max, Number(value)));
    if (!Number.isFinite(v)) return;
    el.value = String(v);
    updateScoreLabel();
    renderScorePresets();
    rerunWithOptions();
  }

  function setScoreRange(kind) {
    var el = document.getElementById("mh-min-score");
    if (!el) return;
    SCORE_KIND = kind === "image" ? "image" : "text";
    var value = parseFloat(el.value);
    if (kind === "text") {
      el.min = "0";
      el.max = "0.5";
      el.step = "0.005";
      if (!Number.isFinite(value) || value > 0.5) el.value = "0.055";
    } else {
      el.min = "0.5";
      el.max = "1";
      el.step = "0.005";
      if (!Number.isFinite(value) || value < 0.5) el.value = "0.82";
    }
    updateScoreLabel();
    renderScorePresets();
  }

  function topValue() {
    var el = document.getElementById("mh-top");
    var n = el ? parseInt(el.value, 10) : 24;
    return Number.isFinite(n) ? Math.max(1, Math.min(100, n)) : 24;
  }

  function renderTopPresets() {
    var box = document.getElementById("mh-top-presets");
    if (!box) return;
    var current = topValue();
    box.textContent = "";
    TOP_PRESETS.forEach(function (n) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "mh-preset" + (n === current ? " active" : "");
      b.textContent = String(n);
      b.onclick = function () { setTopValue(n); };
      box.appendChild(b);
    });
  }

  function setTopValue(value) {
    var el = document.getElementById("mh-top");
    if (!el) return;
    var n = parseInt(value, 10);
    if (!Number.isFinite(n)) n = 24;
    el.value = String(Math.max(1, Math.min(100, n)));
    renderTopPresets();
    rerunWithOptions();
  }

  function currentMode() {
    var el = document.getElementById("mh-mode");
    return el && el.value === "regex" ? "regex" : "semantic";
  }

  function currentKind() {
    var el = document.getElementById("mh-kind");
    var value = el ? el.value : "all";
    return value === "image" || value === "scene" ? value : "all";
  }

  function currentMatch() {
    var el = document.getElementById("mh-match");
    return el && el.value === "any" ? "any" : "all";
  }

  function updateModeUI() {
    var mode = currentMode();
    var regex = mode === "regex";
    var scoreRow = document.getElementById("mh-score-row");
    var presets = document.getElementById("mh-regex-presets");
    var ignore = document.getElementById("mh-ignore-wrap");
    var input = document.getElementById("mh-q");
    var sep = document.getElementById("mh-sep-hint");
    if (scoreRow) scoreRow.classList.toggle("mh-hidden", regex);
    if (presets) presets.classList.toggle("open", regex);
    if (ignore) ignore.style.display = regex ? "" : "none";
    if (input) {
      input.placeholder = regex
        ? "正则表达式；多个用；或,分隔，例如 电脑|显示器"
        : "中文/英文描述；多个关键词用；或,分隔";
      input.title = regex
        ? "按文件名、路径、标签和 ID 做正则匹配；不区分大小写可关闭"
        : "SigLIP2 语义搜索；多个关键词按“全部/任一”组合";
    }
    if (sep) sep.textContent = regex
      ? "多正则：； ; 换行（| 保留为或）"
      : "分隔：； ; ， , 、 | 换行";
  }

  function baseName(path) {
    var value = String(path || "").replace(/\//g, "\\");
    return value.split("\\").pop() || "";
  }

  function rerunWithOptions() {
    if (!LAST_SEARCH) return;
    var next = Object.assign({}, LAST_SEARCH, { top: topValue() });
    if (LAST_SEARCH.stash_id) {
      next.min_score = scoreValue();
    } else {
      next.kind = currentKind();
      next.match = currentMatch();
      next.mode = currentMode();
      if (next.mode === "regex") {
        delete next.min_score;
        var input = document.getElementById("mh-q");
        next.text = input ? input.value.trim() : (next.text || "");
        if (!next.text) return;
      } else {
        next.min_score = scoreValue();
      }
    }
    LAST_SEARCH = next;
    clearTimeout(scoreTimer);
    scoreTimer = setTimeout(function () { if (LAST_SEARCH) doSearch(LAST_SEARCH); }, 250);
  }

  function updateSearchActions() {
    var n = Object.keys(SEARCH_SELECTED).length;
    var box = document.getElementById("mh-search-actions");
    var count = document.getElementById("mh-search-selected-count");
    if (box) box.style.display = n ? "flex" : "none";
    if (count) count.textContent = "已选 " + n + " 个";
    ["mh-search-trash", "mh-search-delete", "mh-search-clear"].forEach(function (id) {
      var e = document.getElementById(id);
      if (e) e.disabled = SEARCH_BUSY || !n;
    });
  }

  function toggleSearchSelection(key, checked, card) {
    if (checked) SEARCH_SELECTED[key] = SEARCH_ITEMS[key];
    else delete SEARCH_SELECTED[key];
    if (card) card.classList.toggle("sel", checked);
    updateSearchActions();
  }

  function clearSearchSelection() {
    SEARCH_SELECTED = Object.create(null);
    var checks = document.querySelectorAll("#mh-results .mh-card-check");
    for (var i = 0; i < checks.length; i++) checks[i].checked = false;
    var cards = document.querySelectorAll("#mh-results .mh-card.sel");
    for (var j = 0; j < cards.length; j++) cards[j].classList.remove("sel");
    updateSearchActions();
  }

  function searchDelete(mode) {
    if (SEARCH_BUSY) return;
    var keys = Object.keys(SEARCH_SELECTED);
    if (!keys.length) return;
    var items = keys.map(function (k) { return SEARCH_SELECTED[k]; });
    var message = mode === "trash"
      ? "确定将 " + items.length + " 个结果放入电脑回收站？\n会同时移除 Stash 记录和生成的预览文件，原文件可在回收站恢复。"
      : "确定永久删除 " + items.length + " 个结果的原文件？\n此操作不可恢复，Stash 记录和生成的预览文件也会移除。";
    if (!window.confirm(message)) return;
    SEARCH_BUSY = true;
    updateSearchActions();
    setStatus(mode === "trash" ? "正在放入回收站…" : "正在永久删除…");
    fetch(BASE + "/library/delete", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ mode: mode, items: items.map(function (x) {
        return { kind: x.kind, id: x.stash_id };
      }) })
    }).then(function (r) {
      return r.json().then(function (j) {
        if (!r.ok) throw new Error(j.error || ("HTTP " + r.status));
        return j;
      });
    }).then(function (j) {
      var ok = (j.items || []).filter(function (x) { return x.ok; });
      ok.forEach(function (x) {
        var key = x.kind + "|" + x.id;
        SEARCH_DELETED[key] = true;
        delete SEARCH_SELECTED[key];
        var cards = document.querySelectorAll("#mh-results .mh-card");
        for (var i = 0; i < cards.length; i++) {
          if (cards[i].dataset.mhKey === key) cards[i].remove();
        }
      });
      setStatus((mode === "trash" ? "已放入回收站 " : "已删除 ") + ok.length + " 个" +
        (j.failed ? "；失败 " + j.failed + " 个" : ""));
      updateSearchActions();
    }).catch(function (e) {
      setStatus("删除失败：" + (e.message || e));
    }).finally(function () {
      SEARCH_BUSY = false;
      updateSearchActions();
    });
  }

  function searchText() {
    var input = document.getElementById("mh-q");
    var text = input ? input.value.trim() : "";
    if (!text) { setStatus("请输入搜索描述"); return; }
    var hint = document.getElementById("mh-search-hint");
    if (hint) hint.style.display = "none";
    var mode = currentMode();
    var payload = {
      mode: mode,
      text: text,
      top: topValue(),
      kind: currentKind(),
      match: currentMatch()
    };
    if (mode === "regex") {
      payload.ignore_case = !document.getElementById("mh-ignore-case") ||
        document.getElementById("mh-ignore-case").checked;
    } else {
      setScoreRange("text");
      payload.min_score = scoreValue();
    }
    document.getElementById("mh-title").textContent =
      mode === "regex" ? "MineHub 正则搜索" : "MineHub 搜索";
    doSearch(payload);
  }

  function cardCaption(item, payload) {
    var label = item.kind === "scene" ? "场景" : "图片";
    var score = Number(item.score);
    if (payload.mode === "regex" || item.score == null || !Number.isFinite(score)) {
      var name = item.title || baseName(item.source_path);
      return label + " #" + item.stash_id + (name ? " · " + name : "");
    }
    return label + " #" + item.stash_id + " · " + score.toFixed(3);
  }

  function cardFields(item) {
    var parts = [];
    if (item.source_path) parts.push(item.source_path);
    if (item.tags) parts.push(item.tags);
    return parts.join("\n");
  }

  function doSearch(payload) {
    LAST_SEARCH = payload;
    if (busy) { QUEUED_SEARCH = payload; return; }
    busy = true;
    SEARCH_ITEMS = Object.create(null);
    SEARCH_SELECTED = Object.create(null);
    updateSearchActions();
    setStatus("搜索中…");
    var results = document.getElementById("mh-results");
    results.textContent = "";
    var ctrl = new AbortController();
    var timer = setTimeout(function () { ctrl.abort(); }, 30000);
    fetch(BASE + "/search", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
      signal: ctrl.signal
    }).then(function (r) {
      return r.json().then(function (j) {
        if (!r.ok) throw new Error(j.error || ("HTTP " + r.status));
        return j;
      });
    }).then(function (j) {
      var rows = (j.results || []).filter(function (x) {
        return !SEARCH_DELETED[x.kind + "|" + x.stash_id];
      });
      var cutoff = Number(payload.min_score);
      var isRegex = payload.mode === "regex";
      var cutoffText = isRegex ? " · 正则匹配" :
        (Number.isFinite(cutoff) ? " · 相似度 ≥ " + cutoff.toFixed(3) : "");
      var kindText = payload.kind === "image" ? " · 仅图片" :
        (payload.kind === "scene" ? " · 仅场景" : "");
      setStatus(rows.length ? ("共 " + rows.length + " 个结果" + cutoffText + kindText) :
        ("没有找到结果" + cutoffText + kindText));
      rows.forEach(function (x) {
        var key = x.kind + "|" + x.stash_id;
        SEARCH_ITEMS[key] = x;
        var card = document.createElement("div");
        card.className = "mh-card";
        card.dataset.mhKey = key;
        var link = document.createElement("a");
        link.className = "mh-card-main";
        link.href = x.page_url;
        link.title = cardFields(x) || ((x.kind === "scene" ? "场景" : "图片") + " #" + x.stash_id);
        var img = document.createElement("img");
        img.loading = "lazy";
        img.src = x.thumbnail_url;
        img.alt = "";
        var cap = document.createElement("span");
        cap.textContent = cardCaption(x, payload);
        link.appendChild(img);
        link.appendChild(cap);
        card.appendChild(link);
        var preview = document.createElement("a");
        preview.className = "mh-card-preview";
        preview.href = x.page_url;
        preview.target = "_blank";
        preview.rel = "noopener";
        preview.title = "在 Stash 原生页面预览";
        preview.setAttribute("aria-label", "在 Stash 原生页面预览");
        preview.innerHTML = '<svg data-prefix="fas" data-icon="magnifying-glass" class="svg-inline--fa fa-magnifying-glass fa-icon" role="img" viewBox="0 0 512 512" aria-hidden="true"><path fill="currentColor" d="M416 208c0 45.9-14.9 88.3-40 122.7L502.6 457.4c12.5 12.5 12.5 32.8 0 45.3s-32.8 12.5-45.3 0L330.7 376C296.3 401.1 253.9 416 208 416 93.1 416 0 322.9 0 208S93.1 0 208 0 416 93.1 416 208zM208 352a144 144 0 1 0 0-288 144 144 0 1 0 0 288z"></path></svg>';
        card.appendChild(preview);
        var wrap = document.createElement("label");
        wrap.className = "mh-card-check-wrap";
        wrap.title = "选择此结果";
        var chk = document.createElement("input");
        chk.type = "checkbox";
        chk.className = "mh-card-check";
        chk.title = "选择此结果";
        chk.onclick = function (ev) {
          ev.stopPropagation();
          toggleSearchSelection(key, chk.checked, card);
        };
        var tick = document.createElement("span");
        tick.className = "mh-card-check-tick";
        tick.textContent = "✓";
        wrap.appendChild(chk);
        wrap.appendChild(tick);
        card.appendChild(wrap);
        results.appendChild(card);
      });
    }).catch(function (e) {
      setStatus(e.name === "AbortError" ? "搜索超时，请确认 MineHub 服务正在运行" :
        ("搜索失败：" + (e.message || e)));
    }).finally(function () {
      clearTimeout(timer);
      busy = false;
      if (QUEUED_SEARCH) {
        var next = QUEUED_SEARCH;
        QUEUED_SEARCH = null;
        doSearch(next);
      }
    });
  }

  // ---------- QQ cache panel ----------
  function pmFetch(path, payload) {
    var opts = payload === undefined ? {} : {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload)
    };
    return fetch(BASE + path, opts).then(function (r) {
      return r.json().then(function (j) {
        if (!r.ok) throw new Error(j.error || ("HTTP " + r.status));
        return j;
      });
    });
  }

  function pmSetStatus(text) {
    var el = document.querySelector("#mh-pm-head .mh-pm-status");
    if (el) el.textContent = text || "";
  }

  function pmValue(id) {
    var el = document.getElementById(id);
    return el ? el.value : "";
  }

  function fmtSize(n) {
    n = Number(n) || 0;
    if (n < 1024) return n + " B";
    var u = ["KB", "MB", "GB", "TB"], v = n;
    for (var i = 0; i < u.length; i++) {
      v /= 1024;
      if (v < 1024 || i === u.length - 1) return v.toFixed(v < 100 ? 2 : 0) + " " + u[i];
    }
    return n + " B";
  }

  var CAT_LABELS = { daily: "日常", screenshot: "截图", anime: "二次元", adult: "成人", sexy: "性感", sticker: "表情包", review: "待复核", other: "其他" };
  var LEVEL_LABELS = { safe: "安全", suggestive: "擦边", explicit: "露骨" };

  function labelText(label) {
    if (!label) return "";
    var s = (CAT_LABELS[label.category] || label.category || "?") + "·" + (LEVEL_LABELS[label.level] || label.level || "?");
    if (label.needs_review) s += "·待复核";
    return s;
  }

  function ensurePmModal() {
    if (document.getElementById("mh-pm-backdrop")) return;
    ensureStyle();
    var wrap = document.createElement("div");
    wrap.id = "mh-pm-backdrop";
    wrap.innerHTML =
      '<div id="mh-pm-panel">' +
      '<div id="mh-pm-head"><strong>QQ 缓存管理</strong><span class="mh-pm-status"></span><button id="mh-pm-x" title="关闭">×</button></div>' +
      '<div id="mh-pm-top">' +
      '<select id="mh-pm-root" title="扫描目录"></select>' +
      '<button id="mh-pm-scan">扫描</button>' +
      '<select id="mh-pm-kind"><option value="all">图片+视频</option><option value="image">仅图片</option><option value="video">仅视频</option></select>' +
      '<select id="mh-pm-scope"><option value="all">Ori+Thumb</option><option value="ori">仅 Ori</option><option value="thumb">仅 Thumb</option></select>' +
      '<input id="mh-pm-min" type="number" min="0" step="0.1" placeholder="最小 MB" style="width:78px">' +
      '<input id="mh-pm-text" placeholder="文件名 / 子目录" style="width:150px">' +
      '<select id="mh-pm-sort"><option value="size">按大小</option><option value="mtime">按时间</option><option value="name">按名称</option><option value="chat">按归属</option><option value="path">按路径</option></select>' +
      '<select id="mh-pm-dir"><option value="desc">降序</option><option value="asc">升序</option></select>' +
      '<select id="mh-pm-cat"><option value="all">全部分类</option><option value="nsfw">仅 NSFW</option><option value="safe">仅安全</option><option value="daily">日常</option><option value="screenshot">截图</option><option value="anime">二次元</option><option value="adult">成人</option><option value="sexy">性感</option><option value="sticker">表情包</option><option value="review">待复核</option><option value="other">其他</option></select>' +
      '<select id="mh-pm-level"><option value="all">全部等级</option><option value="safe">安全</option><option value="suggestive">擦边</option><option value="explicit">露骨</option></select>' +
      '<input id="mh-pm-tags" placeholder="标签(空格)" style="width:120px">' +
      '<label class="mh-pm-check"><input id="mh-pm-only" type="checkbox">仅已打标</label>' +
      '<label class="mh-pm-check"><input id="mh-pm-review" type="checkbox">仅待复核</label>' +
      '<button id="mh-pm-labels" class="gray">重载标签</button>' +
      '<button id="mh-pm-index" class="gray">更新归属索引</button>' +
      '</div>' +
      '<div id="mh-pm-body">' +
      '<aside id="mh-pm-side">' +
      '<div class="mh-pm-sidebar">' +
      '<select id="mh-pm-chatmode"><option value="off">不过滤聊天</option><option value="include">仅显示勾选</option><option value="exclude">排除勾选</option></select>' +
      '<input id="mh-pm-chatsearch" placeholder="搜索好友 / 群…">' +
      '<label class="mh-pm-check"><input id="mh-pm-unknown" type="checkbox">显示无归属文件</label>' +
      '<label class="mh-pm-check"><input id="mh-pm-mapped" type="checkbox">仅显示有归属</label>' +
      '</div><div id="mh-pm-chats"></div>' +
      '</aside>' +
      '<main id="mh-pm-main">' +
      '<div id="mh-pm-tools">' +
      '<button id="mh-pm-all">全选本页</button><button id="mh-pm-none">清空选择</button>' +
      '<button id="mh-pm-move" class="blue">移动到…</button><button id="mh-pm-del" class="red">移入回收站</button>' +
      '<button id="mh-pm-open">系统打开</button>' +
      '<span class="mh-pm-count"></span>' +
      '</div><div id="mh-pm-grid"><div class="mh-pm-empty">选择目录后点击「扫描」。</div></div>' +
      '<div id="mh-pm-pager"><button id="mh-pm-prev">上一页</button><span id="mh-pm-pageinfo">-</span><button id="mh-pm-next">下一页</button></div>' +
      '</main></div></div>' +
      '<div id="mh-pm-preview"><div id="mh-pm-preview-box"><img id="mh-pm-preview-img" alt="">' +
      '<div id="mh-pm-preview-meta"></div><div id="mh-pm-preview-actions">' +
      '<button id="mh-pm-preview-open">系统打开</button><button id="mh-pm-preview-close">关闭</button>' +
      '</div></div></div>';
    document.body.appendChild(wrap);

    document.getElementById("mh-pm-x").onclick = function () { wrap.classList.remove("open"); };
    wrap.addEventListener("click", function (e) { if (e.target === wrap) wrap.classList.remove("open"); });
    document.getElementById("mh-pm-scan").onclick = pmScan;
    document.getElementById("mh-pm-labels").onclick = function () {
      pmFetch("/reload-labels", {}).then(function (j) {
        pmSetStatus("标签已重载：" + j.labels + " 条");
        pmQuery();
      }).catch(function (e) { pmSetStatus("重载标签失败：" + e.message); });
    };
    document.getElementById("mh-pm-index").onclick = pmBuildIndex;
    document.getElementById("mh-pm-all").onclick = function () {
      PM.records.forEach(function (r) { PM.selected[r.path] = true; });
      pmRenderSelection();
    };
    document.getElementById("mh-pm-none").onclick = function () {
      PM.selected = Object.create(null);
      pmRenderSelection();
    };
    document.getElementById("mh-pm-move").onclick = pmMove;
    document.getElementById("mh-pm-del").onclick = pmRecycle;
    document.getElementById("mh-pm-open").onclick = pmOpenSelected;
    document.getElementById("mh-pm-prev").onclick = function () { if (PM.page > 1) { PM.page--; pmQuery(); } };
    document.getElementById("mh-pm-next").onclick = function () { if (PM.page < PM.pages) { PM.page++; pmQuery(); } };
    document.getElementById("mh-pm-preview-close").onclick = function () {
      document.getElementById("mh-pm-preview").classList.remove("open");
    };
    document.getElementById("mh-pm-preview").addEventListener("click", function (e) {
      if (e.target.id === "mh-pm-preview") e.target.classList.remove("open");
    });

    var filters = ["mh-pm-kind", "mh-pm-scope", "mh-pm-min", "mh-pm-text", "mh-pm-sort", "mh-pm-dir",
      "mh-pm-cat", "mh-pm-level", "mh-pm-tags", "mh-pm-only", "mh-pm-review", "mh-pm-chatmode",
      "mh-pm-unknown", "mh-pm-mapped"];
    filters.forEach(function (id) {
      var el = document.getElementById(id);
      if (!el) return;
      el.addEventListener(el.tagName === "INPUT" && el.type === "text" ? "input" : "change", function () {
        PM.page = 1;
        pmSchedule();
      });
    });
    document.getElementById("mh-pm-min").addEventListener("input", function () { PM.page = 1; pmSchedule(); });
    document.getElementById("mh-pm-tags").addEventListener("input", function () { PM.page = 1; pmSchedule(); });
    document.getElementById("mh-pm-text").addEventListener("input", function () { PM.page = 1; pmSchedule(); });
    document.getElementById("mh-pm-chatsearch").addEventListener("input", pmRenderChats);
    document.getElementById("mh-pm-chatmode").addEventListener("change", pmUpdateChatControls);
  }

  function pmSchedule() {
    clearTimeout(PM.timer);
    PM.timer = setTimeout(pmQuery, 260);
  }

  function openPm() {
    ensurePmModal();
    var box = document.getElementById("mh-pm-backdrop");
    box.classList.add("open");
    if (!PM.loaded) {
      pmSetStatus("加载配置…");
      Promise.all([pmFetch("/pm/config"), pmFetch("/pm/chats")]).then(function (res) {
        PM.cfg = res[0];
        PM.chats = res[1].chats || [];
        PM.loaded = true;
        pmRenderRoots();
        pmRenderChats();
        pmUpdateChatControls();
        pmSetStatus("配置已加载，选择目录后点击扫描");
      }).catch(function (e) {
        pmSetStatus("加载失败：" + e.message + "（请确认 MineHub 服务正在运行）");
      });
    }
  }

  function pmRenderRoots() {
    var sel = document.getElementById("mh-pm-root");
    sel.textContent = "";
    (PM.cfg.roots || []).forEach(function (r) {
      var o = document.createElement("option");
      o.value = r.path;
      o.textContent = r.label;
      o.dataset.account = r.account || "";
      sel.appendChild(o);
    });
    if (PM.cfg.default_root) sel.value = PM.cfg.default_root;
  }

  function pmRenderChats() {
    var host = document.getElementById("mh-pm-chats");
    if (!host) return;
    var q = (pmValue("mh-pm-chatsearch") || "").trim().toLowerCase();
    host.textContent = "";
    PM.chats.forEach(function (c) {
      var label = (c.kind === "group" ? "群 · " : c.kind === "self" ? "自己 · " : "好友 · ") + (c.name || c.chat_id);
      if (c.account) label += " [" + c.account + "]";
      if (q && (label + " " + (c.uin || "") + " " + c.chat_id).toLowerCase().indexOf(q) < 0) return;
      var row = document.createElement("label");
      row.className = "mh-pm-chat";
      var chk = document.createElement("input");
      chk.type = "checkbox";
      chk.checked = !!PM.selected["chat:" + c.key];
      chk.addEventListener("change", function () {
        if (chk.checked) PM.selected["chat:" + c.key] = true;
        else delete PM.selected["chat:" + c.key];
        PM.page = 1;
        pmSchedule();
      });
      var text = document.createElement("span");
      text.textContent = label;
      var count = document.createElement("em");
      count.textContent = " [" + c.count + "]";
      row.appendChild(chk);
      row.appendChild(text);
      row.appendChild(count);
      host.appendChild(row);
    });
  }

  function pmCheckedChats() {
    return Object.keys(PM.selected).filter(function (k) { return k.indexOf("chat:") === 0; }).map(function (k) { return k.slice(5); });
  }

  function pmUpdateChatControls() {
    var mode = pmValue("mh-pm-chatmode") || "off";
    document.getElementById("mh-pm-unknown").disabled = mode !== "include";
  }

  function pmScan() {
    var root = pmValue("mh-pm-root");
    if (!root) { pmSetStatus("没有可扫描目录"); return; }
    pmSetStatus("扫描中…");
    pmFetch("/pm/scan", { roots: [root] }).then(function (j) {
      PM.page = 1;
      PM.selected = Object.create(null);
      pmSetStatus("扫描完成：" + j.records + " 个文件" + (j.cached ? "（缓存）" : ""));
      pmQuery();
    }).catch(function (e) { pmSetStatus("扫描失败：" + e.message); });
  }

  function pmQuery() {
    if (!PM.loaded) return;
    var seq = ++PM.querySeq;
    var minMb = parseFloat(pmValue("mh-pm-min") || "0") || 0;
    var tags = (pmValue("mh-pm-tags") || "").replace(/,/g, " ").split(/\s+/).filter(Boolean);
    var payload = {
      page: PM.page,
      page_size: 120,
      kind: pmValue("mh-pm-kind") || "all",
      scope: pmValue("mh-pm-scope") || "all",
      min_bytes: Math.round(minMb * 1024 * 1024),
      text: pmValue("mh-pm-text") || "",
      sort: pmValue("mh-pm-sort") || "size",
      dir: pmValue("mh-pm-dir") || "desc",
      chat_mode: pmValue("mh-pm-chatmode") || "off",
      checked_chats: pmCheckedChats(),
      include_unknown: document.getElementById("mh-pm-unknown").checked,
      only_mapped: document.getElementById("mh-pm-mapped").checked,
      mh_cat: pmValue("mh-pm-cat") || "all",
      mh_level: pmValue("mh-pm-level") || "all",
      mh_tags: tags,
      only_labeled: document.getElementById("mh-pm-only").checked,
      only_review: document.getElementById("mh-pm-review").checked
    };
    pmSetStatus("查询中…");
    pmFetch("/pm/query", payload).then(function (j) {
      if (seq !== PM.querySeq) return;
      PM.records = j.records || [];
      PM.page = j.page || 1;
      PM.pages = j.pages || 1;
      PM.total = j.total || 0;
      pmRenderGrid();
      pmSetStatus("共 " + j.total + " 个文件 · " + fmtSize(j.total_size) + " · 有归属 " + j.mapped + " · 已打标 " + j.labeled);
    }).catch(function (e) {
      if (seq === PM.querySeq) pmSetStatus("查询失败：" + e.message);
    });
  }

  function pmThumb(path, size) {
    return BASE + "/pm/thumb?size=" + size + "&path=" + encodeURIComponent(path);
  }

  function pmRenderGrid() {
    var grid = document.getElementById("mh-pm-grid");
    grid.textContent = "";
    if (!PM.records.length) {
      var empty = document.createElement("div");
      empty.className = "mh-pm-empty";
      empty.textContent = "没有匹配的文件";
      grid.appendChild(empty);
      pmRenderSelection();
      pmRenderPager();
      return;
    }
    PM.records.forEach(function (rec) {
      var card = document.createElement("div");
      card.className = "mh-pm-card" + (PM.selected[rec.path] ? " sel" : "");
      card.title = rec.path;
      var chk = document.createElement("input");
      chk.type = "checkbox";
      chk.className = "mh-pm-chk";
      chk.checked = !!PM.selected[rec.path];
      chk.addEventListener("click", function (e) { e.stopPropagation(); });
      chk.addEventListener("change", function () {
        if (chk.checked) PM.selected[rec.path] = true;
        else delete PM.selected[rec.path];
        card.classList.toggle("sel", chk.checked);
        pmRenderSelection();
      });
      var img = document.createElement("img");
      img.decoding = "async";
      img.alt = "";
      img.loading = "eager";
      img.src = pmThumb(rec.path, 320);
      img.addEventListener("click", function (e) { e.stopPropagation(); pmPreview(rec); });
      var meta = document.createElement("div");
      meta.className = "mh-pm-meta";
      var name = document.createElement("div");
      name.className = "mh-pm-name";
      name.textContent = rec.name;
      var sub = document.createElement("div");
      sub.className = "mh-pm-sub";
      var bits = [fmtSize(rec.size), rec.kind === "video" ? "视频" : "图片"];
      if (rec.variant) bits.push(rec.variant);
      sub.textContent = bits.join(" · ");
      meta.appendChild(name);
      meta.appendChild(sub);
      if (rec.chats && rec.chats.length) {
        var chat = document.createElement("div");
        chat.className = "mh-pm-sub";
        chat.textContent = rec.chats.map(function (c) { return c.label; }).join(" / ");
        meta.appendChild(chat);
      }
      var lab = labelText(rec.label);
      if (lab) {
        var chip = document.createElement("span");
        chip.className = "mh-pm-tag";
        chip.textContent = lab;
        meta.appendChild(chip);
      }
      card.appendChild(chk);
      card.appendChild(img);
      card.appendChild(meta);
      card.addEventListener("click", function () {
        chk.checked = !chk.checked;
        if (chk.checked) PM.selected[rec.path] = true;
        else delete PM.selected[rec.path];
        card.classList.toggle("sel", chk.checked);
        pmRenderSelection();
      });
      grid.appendChild(card);
    });
    pmRenderSelection();
    pmRenderPager();
  }

  function pmRenderPager() {
    document.getElementById("mh-pm-pageinfo").textContent = "第 " + PM.page + " / " + PM.pages + " 页";
    document.getElementById("mh-pm-prev").disabled = PM.page <= 1;
    document.getElementById("mh-pm-next").disabled = PM.page >= PM.pages;
  }

  function pmRenderSelection() {
    var count = Object.keys(PM.selected).filter(function (k) { return k.indexOf("chat:") !== 0; }).length;
    document.querySelector("#mh-pm-tools .mh-pm-count").textContent = "已选 " + count + " / 共 " + PM.total;
  }

  function pmPreview(rec) {
    var box = document.getElementById("mh-pm-preview");
    var img = document.getElementById("mh-pm-preview-img");
    img.src = pmThumb(rec.path, 1600);
    var meta = document.getElementById("mh-pm-preview-meta");
    meta.textContent = rec.name + " · " + fmtSize(rec.size) + (rec.chats && rec.chats.length ? " · " + rec.chats.map(function (c) { return c.label; }).join(" / ") : "");
    document.getElementById("mh-pm-preview-open").onclick = function () {
      pmFetch("/pm/open", { path: rec.path }).catch(function (e) { pmSetStatus("打开失败：" + e.message); });
    };
    box.classList.add("open");
  }

  function pmMove() {
    var paths = Object.keys(PM.selected).filter(function (k) { return k.indexOf("chat:") !== 0; });
    if (!paths.length) { pmSetStatus("请先选择文件"); return; }
    var dest = prompt("移动到目标文件夹（必须已存在）", PM.cfg && PM.cfg.move_default || "F:\\MineHubData\\library\\review");
    if (!dest) return;
    if (!confirm("将 " + paths.length + " 个文件移动到：\n" + dest)) return;
    pmSetStatus("移动中…");
    pmFetch("/pm/move", { paths: paths, dest: dest }).then(function (j) {
      PM.selected = Object.create(null);
      var msg = "已移动 " + j.moved.length + " 个文件";
      if (j.errors && j.errors.length) msg += "；失败 " + j.errors.length + " 个：" + j.errors.slice(0, 3).join("；");
      pmSetStatus(msg);
      pmQuery();
    }).catch(function (e) { pmSetStatus("移动失败：" + e.message); });
  }

  function pmRecycle() {
    var paths = Object.keys(PM.selected).filter(function (k) { return k.indexOf("chat:") !== 0; });
    if (!paths.length) { pmSetStatus("请先选择文件"); return; }
    if (!confirm("将 " + paths.length + " 个文件移入 Windows 回收站？")) return;
    pmSetStatus("正在移入回收站…");
    pmFetch("/pm/recycle", { paths: paths }).then(function (j) {
      PM.selected = Object.create(null);
      var msg = "已移入回收站 " + j.deleted.length + " 个文件";
      if (j.errors && j.errors.length) msg += "；失败 " + j.errors.length + " 个：" + j.errors.slice(0, 3).join("；");
      pmSetStatus(msg);
      pmQuery();
    }).catch(function (e) { pmSetStatus("删除失败：" + e.message); });
  }

  function pmOpenSelected() {
    var paths = Object.keys(PM.selected).filter(function (k) { return k.indexOf("chat:") !== 0; });
    if (!paths.length) { pmSetStatus("请先选择文件"); return; }
    pmFetch("/pm/open", { path: paths[0] }).catch(function (e) { pmSetStatus("打开失败：" + e.message); });
  }

  function pmBuildIndex() {
    var sel = document.getElementById("mh-pm-root");
    var opt = sel.options[sel.selectedIndex];
    var account = opt && opt.dataset ? opt.dataset.account : "";
    if (!account) { pmSetStatus("当前目录没有 QQ 归属索引"); return; }
    if (!confirm("从 QQ 消息库重建账号 " + account + " 的归属索引？需要 QQ 已登录或已保存密钥。")) return;
    pmSetStatus("开始建立归属索引…");
    pmFetch("/pm/index", { account: account }).then(function () {
      clearInterval(PM.indexTimer);
      PM.indexTimer = setInterval(pmPollIndex, 1500);
    }).catch(function (e) { pmSetStatus("索引任务启动失败：" + e.message); });
  }

  function pmPollIndex() {
    pmFetch("/pm/index/status").then(function (j) {
      var job = j.job || {};
      if (job.status === "running") {
        pmSetStatus("建立归属索引：" + (job.stage || "") + " " + (job.current || 0) + "/" + (job.total || 0));
        return;
      }
      clearInterval(PM.indexTimer);
      PM.indexTimer = null;
      if (job.status === "done") {
        pmSetStatus("归属索引完成：" + job.chats + " 个聊天 · " + job.media + " 条媒体（" + job.seconds + "s）");
        pmFetch("/pm/chats").then(function (res) {
          PM.chats = res.chats || [];
          pmRenderChats();
          pmQuery();
        });
      } else if (job.status === "error") {
        pmSetStatus("归属索引失败：" + (job.error || "未知错误"));
      } else {
        pmSetStatus("索引任务结束：" + job.status);
      }
    }).catch(function (e) { pmSetStatus("查询索引状态失败：" + e.message); });
  }

  // ---------- duplicate detection ----------
  var DUPE = { poll: null, timer: null, initialized: false };

  function dupeSetStatus(text) {
    var el = document.getElementById("mh-dupe-status");
    if (el) el.textContent = text || "";
  }

  function dupeOpenPath(path) {
    pmFetch("/pm/open", { path: path }).catch(function (e) {
      dupeSetStatus("打开失败：" + e.message);
    });
  }

  function dupeValues() {
    var recursive = document.getElementById("mh-dupe-recursive");
    return {
      mode: pmValue("mh-dupe-mode") || "similar",
      scope: pmValue("mh-dupe-scope") || "library",
      algo: pmValue("mh-dupe-algo") || "phash",
      threshold: Number(pmValue("mh-dupe-threshold") || 10),
      root: (pmValue("mh-dupe-root") || "").trim(),
      recursive: !!(recursive && recursive.checked),
      limit: 60
    };
  }

  function dupeUpdateScopeControls() {
    var v = dupeValues();
    var exact = v.mode === "exact";
    var hide = exact || v.scope === "scene";
    var folder = !exact && v.scope === "folder";
    ["mh-dupe-algo-wrap", "mh-dupe-scan-wrap"].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.style.display = hide ? "none" : "";
    });
    ["mh-dupe-folder-wrap", "mh-dupe-recursive-wrap"].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.style.display = folder ? "" : "none";
    });
  }

  function dupeToggleMode() {
    var exact = dupeValues().mode === "exact";
    ["mh-dupe-scope-wrap", "mh-dupe-similar-opts"].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.style.display = exact ? "none" : "";
    });
    dupeUpdateScopeControls();
    dupeQuery();
  }

  function dupeQuery() {
    var v = dupeValues();
    var hint = document.getElementById("mh-dupe-hint");
    if (v.mode === "exact") {
      if (hint) hint.style.display = "none";
      dupeSetStatus("读取账本 MD5…");
      pmFetch("/dupes/exact", { limit: v.limit }).then(function (data) {
        dupeRenderExact(data);
      }).catch(function (e) { dupeSetStatus("读取失败：" + e.message); });
      return;
    }
    if (hint) hint.style.display = "none";
    if (v.scope === "scene") {
      dupeSetStatus("读取 Stash 场景 pHash 组…");
      pmFetch("/dupes/scenes", { distance: v.threshold, limit: v.limit }).then(function (data) {
        dupeRenderSimilar(data);
      }).catch(function (e) {
        dupeSetStatus("读取场景组失败：" + e.message);
      });
      return;
    }
    if (v.scope === "folder") {
      dupeSetStatus("读取文件夹状态…");
      pmFetch("/dupes/status?scope=folder", undefined).then(function (s) {
        var input = document.getElementById("mh-dupe-root");
        if (input && !input.value && s.root) input.value = s.root;
        if (s.job && s.job.status === "running") {
          dupePoll("folder");
          return;
        }
        if (!s.hashed) {
          if (hint) hint.style.display = "";
          var host = document.getElementById("mh-dupe-results");
          if (host) host.textContent = "";
          dupeSetStatus(s.root ? ("已选文件夹尚未扫描：" + s.root) : "请输入文件夹路径，然后点击「扫描并计算」");
          return;
        }
        pmFetch("/dupes/groups", v).then(function (data) {
          dupeRenderSimilar(data);
        }).catch(function (e) {
          dupeSetStatus("分组失败：" + e.message);
        });
      }).catch(function (e) {
        dupeSetStatus("读取文件夹状态失败：" + e.message);
      });
      return;
    }
    dupeSetStatus("正在分组…");
    pmFetch("/dupes/groups", v).then(function (data) {
      dupeRenderSimilar(data);
    }).catch(function (e) {
      dupeSetStatus("分组失败：" + e.message + "（请先扫描）");
    });
  }

  function dupeMakeImage(item, label, big) {
    var box = document.createElement("div");
    box.className = big ? "mh-dupe-rep" : "mh-dupe-member";
    var img = document.createElement("img");
    img.loading = "lazy";
    img.src = item.thumb_url;
    img.alt = "";
    img.title = item.path || "";
    box.appendChild(img);
    var info = document.createElement("div");
    info.className = big ? "mh-dupe-rep-info" : "";
    if (label) {
      var title = document.createElement("strong");
      title.textContent = label;
      info.appendChild(title);
    }
    if (big) {
      var meta = document.createElement("div");
      meta.textContent = (item.kind === "video" ? "视频 · 5 帧 pHash" : "图片") +
        " · 大小 " + fmtSize(item.size) + " · " + (item.width || "?") + "×" + (item.height || "?") +
        (item.distance === null || item.distance === undefined ? " · Stash pHash 组" : " · 距代表 " + item.distance);
      info.appendChild(meta);
      var path = document.createElement("div");
      path.className = "text-muted";
      path.style.wordBreak = "break-all";
      path.textContent = item.path || "";
      info.appendChild(path);
      var actions = document.createElement("div");
      actions.className = "mt-2";
      if (item.page_url) {
        var a = document.createElement("a");
        a.className = "btn btn-secondary btn-sm mr-1";
        a.href = item.page_url;
        a.textContent = "在 MineHub 打开";
        actions.appendChild(a);
      }
      var open = document.createElement("button");
      open.className = "btn btn-secondary btn-sm";
      open.textContent = "系统打开";
      open.onclick = function () { dupeOpenPath(item.path); };
      actions.appendChild(open);
      info.appendChild(actions);
    } else {
      var sub = document.createElement("span");
      sub.textContent = (item.kind === "video" ? "视频 · " : "图片 · ") +
        (item.distance === null || item.distance === undefined ? "场景组" : "距离 " + item.distance) +
        " · " + fmtSize(item.size);
      info.appendChild(sub);
      box.onclick = function () {
        if (item.page_url) location.href = item.page_url;
        else dupeOpenPath(item.path);
      };
      box.style.cursor = "pointer";
    }
    if (big) box.appendChild(info);
    else box.appendChild(info);
    return box;
  }

  function dupeRenderSimilar(data) {
    var host = document.getElementById("mh-dupe-results");
    if (!host) return;
    host.textContent = "";
    var hint = document.getElementById("mh-dupe-hint");
    if (!data.groups || !data.groups.length) {
      if (hint) hint.style.display = "";
      dupeSetStatus((data.scene_mode ? "Stash 场景 pHash" : "已哈希 " + data.hashed + " 个文件") +
        "；严格阈值 " + data.threshold + " 下没有重复组" + (data.root ? " · " + data.root : ""));
      return;
    }
    if (hint) hint.style.display = "none";
    data.groups.forEach(function (g) {
      var card = document.createElement("div");
      card.className = "mh-dupe-group";
      card.appendChild(dupeMakeImage(g.representative,
        (g.representative.kind === "video" ? "代表视频" : "代表图") + " · " + g.count + " 个文件", true));
      var members = document.createElement("div");
      members.className = "mh-dupe-members";
      g.members.forEach(function (m) { members.appendChild(dupeMakeImage(m, m.name || "", false)); });
      card.appendChild(members);
      host.appendChild(card);
    });
    var prefix = data.scene_mode ? "Stash 场景 pHash" :
      "已哈希 " + data.hashed + " 个文件" +
      (data.images !== undefined || data.videos !== undefined
        ? "（图片 " + (data.images || 0) + " / 视频 " + (data.videos || 0) + "）" : "");
    dupeSetStatus(prefix + " · 找到 " + data.total_groups + " 组 / " +
      data.total_files + " 个文件 · 严格阈值 " + data.threshold +
      (data.root ? " · " + data.root : "") +
      (data.returned < data.total_groups ? "（显示前 " + data.returned + " 组）" : ""));
  }

  function dupeRenderExact(data) {
    var host = document.getElementById("mh-dupe-results");
    if (!host) return;
    host.textContent = "";
    if (!data.groups || !data.groups.length) {
      dupeSetStatus("账本中没有 MD5 完全相同的文件");
      return;
    }
    data.groups.forEach(function (g) {
      var card = document.createElement("div");
      card.className = "mh-dupe-group";
      var head = document.createElement("div");
      head.className = "mh-dupe-rep-info mb-2";
      var title = document.createElement("strong");
      title.textContent = "MD5 " + g.md5 + " · " + g.count + " 个 · " + fmtSize(g.total_size);
      head.appendChild(title);
      card.appendChild(head);
      g.members.forEach(function (m) {
        var row = document.createElement("div");
        row.className = "mh-dupe-exact-row";
        var name = document.createElement("span");
        name.style.flex = "0 0 auto";
        name.textContent = m.name;
        var path = document.createElement("span");
        path.className = "path";
        path.textContent = m.path;
        var state = document.createElement("span");
        state.className = "text-muted";
        state.textContent = m.state;
        var open = document.createElement("button");
        open.className = "btn btn-secondary btn-sm";
        open.textContent = "打开";
        open.onclick = function () { dupeOpenPath(m.path); };
        row.appendChild(name);
        row.appendChild(path);
        row.appendChild(state);
        row.appendChild(open);
        card.appendChild(row);
      });
      host.appendChild(card);
    });
    dupeSetStatus("完全相同文件：" + data.total_groups + " 组 / " + data.total_files +
      " 个" + (data.returned < data.total_groups ? "（显示前 " + data.returned + " 组）" : ""));
  }

  function dupeStopPoll() {
    if (DUPE.poll) clearTimeout(DUPE.poll);
    DUPE.poll = null;
  }

  function dupePoll(scope) {
    dupeStopPoll();
    DUPE.poll = setTimeout(function () {
      pmFetch("/dupes/status?scope=" + encodeURIComponent(scope), undefined).then(function (s) {
        var j = s.job || {};
        if (j.status === "running") {
          dupeSetStatus("扫描哈希：" + (j.done || 0) + " / " + (j.total || 0) +
            " · 错误 " + (j.errors || 0));
          dupePoll(scope);
          return;
        }
        dupeStopPoll();
        var btn = document.getElementById("mh-dupe-scan");
        if (btn) btn.disabled = false;
        if (j.status === "error") dupeSetStatus("扫描失败：" + (j.error || "未知错误"));
        else dupeSetStatus("哈希完成：" + (s.hashed || 0) + " 张，错误 " + (s.errors || 0));
        dupeQuery();
      }).catch(function (e) {
        dupeSetStatus("查询进度失败：" + e.message);
      });
    }, 1000);
  }

  function dupeScan() {
    var v = dupeValues();
    if (v.scope === "scene") return;
    if (v.scope === "folder" && !v.root) {
      dupeSetStatus("请输入要扫描的文件夹路径");
      return;
    }
    dupeStopPoll();
    var btn = document.getElementById("mh-dupe-scan");
    if (btn) btn.disabled = true;
    var host = document.getElementById("mh-dupe-results");
    if (host) host.textContent = "";
    var payload = { scope: v.scope, limit: 0, force: false };
    if (v.scope === "folder") {
      payload.root = v.root;
      payload.recursive = v.recursive;
    }
    pmFetch("/dupes/scan", payload).then(function (j) {
      dupeSetStatus("扫描任务已开始…");
      dupePoll(v.scope);
    }).catch(function (e) {
      dupeSetStatus("启动扫描失败：" + e.message);
      if (btn) btn.disabled = false;
    });
  }

  function dupeInit() {
    if (DUPE.initialized) {
      if (!DUPE.poll) dupeQuery();
      return;
    }
    DUPE.initialized = true;
    var v = dupeValues();
    dupeUpdateScopeControls();
    if (v.scope === "scene" || v.scope === "folder") { dupeQuery(); return; }
    pmFetch("/dupes/status?scope=" + encodeURIComponent(v.scope), undefined).then(function (s) {
      var j = s.job || {};
      if (j.status === "running") {
        dupePoll(v.scope);
      } else if (s.hashed) {
        dupeQuery();
      } else {
        dupeSetStatus("尚未计算哈希；点击「扫描并计算」开始（会缓存，后续很快）");
      }
    }).catch(function (e) {
      dupeSetStatus("重复检测服务不可用：" + e.message);
    });
  }

  // ---------- mount ----------
  function update() {
    enforceDefaultSort();
    var m = location.pathname.match(/^\/(images|scenes)\/(\d+)(?:$|\/)/);
    var old = document.getElementById("mh-sim-btn");
    if (!m) {
      if (old) old.remove();
    } else {
      var kind = m[1] === "images" ? "image" : "scene";
      if (old) old.onclick = function () { openSearch({ id: m[2], kind: kind }); };
      else {
        var b = document.createElement("button");
        b.id = "mh-sim-btn";
        b.textContent = "找相似";
        b.title = "在 MineHub 内查看相似图片";
        b.onclick = function () { openSearch({ id: m[2], kind: kind }); };
        document.body.appendChild(b);
      }
    }
    if (!document.getElementById("mh-search-btn") && document.body) {
      var g = document.createElement("button");
      g.id = "mh-search-btn";
      g.textContent = "MineHub 搜索";
      g.title = "在 MineHub 内搜索相似图片";
      g.onclick = function () { openSearch(null); };
      document.body.appendChild(g);
    }
    if (!document.getElementById("mh-pm-btn") && document.body) {
      var p = document.createElement("button");
      p.id = "mh-pm-btn";
      p.textContent = "QQ 缓存";
      p.title = "在 MineHub 内浏览和管理 QQ 图片/视频缓存";
      p.onclick = openPm;
      document.body.appendChild(p);
    }
  }

// ---------- Stash-native MineHub hub ----------
  var hubEl = null;
  var lastTranslate = 0;
  var updateScheduled = false;

  function ensureHubStyle() {
    if (document.getElementById("mh-hub-style")) return;
    var style = document.createElement("style");
    style.id = "mh-hub-style";
    style.textContent = [
      "#mh-hub{display:none;background:transparent;color:#f5f8fa;padding:8px 0 32px;min-height:calc(100vh - 80px)}",
      "#mh-hub.open{display:block}",
      "#mh-hub .mh-hub-head{display:flex;align-items:center;gap:12px;margin-bottom:14px}",
      "#mh-hub .mh-hub-head h2{margin:0;color:#f5f8fa}",
      "#mh-hub .mh-hub-head .mh-hub-status{color:#aab8c4;font-size:12px;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}",
      "#mh-hub .nav-tabs{border-bottom-color:#3b4a55}",
      "#mh-hub .nav-tabs .nav-link{color:#c4d0da;border:0;border-bottom:2px solid transparent;border-radius:0;padding:9px 14px}",
      "#mh-hub .nav-tabs .nav-link:hover{color:#fff;border-bottom-color:#5f6b76}",
      "#mh-hub .nav-tabs .nav-link.active{color:#48aff0;background:transparent;border-bottom-color:#48aff0}",
      "#mh-hub .mh-card-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:12px;align-content:start}",
      "#mh-hub .mh-card{background:#2c3e50;border:1px solid #3b4a55;border-radius:4px;overflow:hidden;min-height:0;position:relative}",
      "#mh-hub .mh-card.sel{border-color:#48aff0;box-shadow:0 0 0 2px #48aff0 inset}",
      "#mh-hub .mh-card-main{display:block;color:inherit;text-decoration:none}",
      "#mh-hub .mh-card-check-wrap{position:absolute;right:8px;top:8px;z-index:4;width:22px;height:22px;display:flex;align-items:center;justify-content:center;background:rgba(13,17,23,.72);border:2px solid #dbe4eb;border-radius:4px;cursor:pointer}",
      "#mh-hub .mh-card.sel .mh-card-check-wrap{background:#48aff0;border-color:#48aff0}",
      "#mh-hub .mh-card-check{position:absolute;inset:0;width:100%;height:100%;margin:0;opacity:0;cursor:pointer;z-index:2}",
      "#mh-hub .mh-card .mh-card-check-tick{display:none;padding:0;color:#15212b;font-size:16px;font-weight:700;line-height:1;pointer-events:none}",
      "#mh-hub .mh-card .mh-card-check:checked + .mh-card-check-tick{display:block}",
      "#mh-hub .mh-card:hover{border-color:#48aff0}",
      "#mh-hub .mh-card img{display:block;width:100%;height:170px;object-fit:cover;background:#1f2a33}",
      "#mh-hub .mh-card span{display:block;padding:7px 9px;color:#c4d0da;font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}",
      "#mh-hub .mh-card-preview{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);z-index:3;width:44px;height:44px;border-radius:50%;display:flex;align-items:center;justify-content:center;background:rgba(13,17,23,.8);border:1px solid rgba(255,255,255,.72);color:#fff;opacity:0;pointer-events:none;transition:opacity .12s}",
      "#mh-hub .mh-card:hover .mh-card-preview,#mh-hub .mh-card:focus-within .mh-card-preview{opacity:1;pointer-events:auto}",
      "#mh-hub .mh-card-preview:hover{background:#48aff0;color:#15212b}",
      "@media (hover:none){#mh-hub .mh-card-preview{opacity:1;pointer-events:auto}}",
      "#mh-hub #mh-regex-presets{display:none;flex-wrap:wrap;align-items:center;gap:6px;max-width:900px;margin-bottom:10px}",
      "#mh-hub #mh-regex-presets.open{display:flex}",
      "#mh-hub #mh-score-row{display:flex;flex-wrap:wrap;align-items:center;max-width:900px;margin-bottom:10px}",
      "#mh-hub #mh-score-row.mh-hidden{display:none}",
      "#mh-hub .mh-kind-label,#mh-hub .mh-mode-label{white-space:nowrap}",
      "#mh-hub .card{background:#2c3e50;border-color:#3b4a55}",
      "#mh-hub .form-control{background:#1f2a33;border-color:#4a5b69;color:#f5f8fa}",
      "#mh-hub .form-control:focus{background:#1f2a33;color:#fff;border-color:#48aff0;box-shadow:0 0 0 .15rem rgba(72,175,240,.25)}",
      "#mh-hub .btn-secondary{background:transparent;border-color:#f5f8fa;color:#f5f8fa}",
      "#mh-hub .btn-secondary:hover{background:#394b59;color:#fff}",
      "#mh-hub .btn-primary{background:#48aff0;border-color:#48aff0;color:#15212b}",
      "#mh-hub .btn-primary:hover{background:#2b95d6;border-color:#2b95d6;color:#fff}",
      "#mh-hub #mh-pm-side{width:auto;min-width:0;background:transparent;border-right:0;display:block}",
      "#mh-hub #mh-pm-chats{max-height:calc(100vh - 330px);overflow:auto;padding:2px 0}",
      "#mh-hub .mh-pm-chat{display:flex;gap:7px;align-items:flex-start;padding:4px 3px;border-radius:4px;cursor:pointer;color:#c4d0da}",
      "#mh-hub .mh-pm-chat:hover{background:#394b59}",
      "#mh-hub .mh-pm-chat span{word-break:break-all;font-size:12px}",
      "#mh-hub .mh-pm-chat em{color:#8b9aa6;font-style:normal;font-size:11px}",
      "#mh-hub .mh-pm-check{display:flex;align-items:center;gap:6px;color:#aab8c4;font-size:12px;padding:2px 0}",
      "#mh-hub #mh-pm-tools{background:transparent;border:0;padding:0 0 8px}",
      "#mh-hub #mh-pm-tools button{font-size:12px}",
      "#mh-hub #mh-pm-grid{padding:0;min-height:240px}",
      "#mh-hub .mh-pm-card{background:#2c3e50;border:1px solid #3b4a55;border-radius:4px;min-height:0;overflow:hidden;position:relative;cursor:pointer}",
      "#mh-hub .mh-pm-card.sel{border-color:#48aff0;box-shadow:0 0 0 1px #48aff0 inset}",
      "#mh-hub .mh-pm-card img{display:block;width:100%;height:150px;object-fit:cover;background:#1f2a33}",
      "#mh-hub .mh-pm-card .mh-pm-meta{padding:6px 7px;font-size:11px;color:#aab8c4;line-height:1.35}",
      "#mh-hub .mh-pm-card .mh-pm-name{color:#f5f8fa;font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}",
      "#mh-hub .mh-pm-card .mh-pm-sub{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}",
      "#mh-hub .mh-pm-card .mh-pm-tag{display:inline-block;margin-top:3px;padding:1px 5px;border-radius:3px;background:#394b59;color:#8ed0ff;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}",
      "#mh-hub .mh-pm-empty{grid-column:1/-1;color:#8b9aa6;text-align:center;padding:60px 10px}",
      "#mh-hub #mh-pm-pager{border:0;background:transparent;padding:8px 0}",
      "#mh-hub .mh-placeholder{max-width:760px;color:#aab8c4;line-height:1.7}",
      "#mh-hub .mh-empty-state{max-width:760px;margin-top:18px;padding:26px 28px;border:1px dashed #3b4a55;border-radius:4px;background:#24323c;color:#aab8c4;line-height:1.7}",
      "#mh-hub .mh-empty-state strong{display:block;color:#f5f8fa;font-size:15px;margin-bottom:6px}",
      "#mh-hub #mh-dupe-results{display:flex;flex-direction:column;gap:12px;max-width:1200px}",
      "#mh-hub .mh-dupe-group{background:#24323c;border:1px solid #3b4a55;border-radius:4px;padding:10px}",
      "#mh-hub .mh-dupe-rep{display:flex;gap:12px;align-items:flex-start}",
      "#mh-hub .mh-dupe-rep img{width:190px;height:130px;object-fit:cover;border-radius:2px;background:#1f2a33;flex:0 0 auto}",
      "#mh-hub .mh-dupe-rep-info{min-width:0;color:#c4d0da;font-size:12px;line-height:1.6}",
      "#mh-hub .mh-dupe-rep-info strong{display:block;color:#f5f8fa;font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}",
      "#mh-hub .mh-dupe-members{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:8px;margin-top:10px}",
      "#mh-hub .mh-dupe-member{background:#2c3e50;border:1px solid #3b4a55;border-radius:3px;overflow:hidden;min-width:0}",
      "#mh-hub .mh-dupe-member img{display:block;width:100%;height:100px;object-fit:cover;background:#1f2a33}",
      "#mh-hub .mh-dupe-member strong{display:block;padding:5px 6px 0;color:#f5f8fa;font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}",
      "#mh-hub .mh-dupe-member span{display:block;padding:3px 6px 5px;font-size:11px;color:#aab8c4;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}",
      "#mh-hub .mh-dupe-exact-row{display:flex;gap:8px;align-items:center;padding:3px 0;border-top:1px solid #33434f;font-size:12px;color:#c4d0da}",
      "#mh-hub .mh-dupe-exact-row:first-child{border-top:0}",
      "#mh-hub .mh-dupe-exact-row .path{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}",
      "#mh-hub #mh-dupe-similar-opts label,#mh-hub #mh-dupe-similar-opts span{white-space:nowrap}",
      "#mh-hub .mh-placeholder h4{color:#f5f8fa}",
      "#mh-hub .mh-preset{margin-left:5px;padding:2px 8px;border:1px solid #4a5b69;border-radius:4px;background:#26333f;color:#c4d0da;font-size:12px;cursor:pointer}",
      "#mh-hub .mh-preset:hover{border-color:#48aff0;color:#fff}",
      "#mh-hub .mh-preset.active{background:#48aff0;border-color:#48aff0;color:#15212b}",
      "#mh-gif-note{margin:4px 0 14px;padding:9px 12px;border-left:4px solid #48aff0;border-radius:4px;background:#24323c;color:#c4d0da;font-size:13px;line-height:1.6}",
      "#mh-gif-note strong{color:#f5f8fa}",
      "#mh-pm-preview{display:none;position:fixed;inset:0;z-index:2147483647;background:rgba(10,15,20,.92);align-items:center;justify-content:center}",
      "#mh-pm-preview.open{display:flex}",
      "#mh-pm-preview-box{max-width:94vw;max-height:94vh;display:flex;flex-direction:column;gap:8px;align-items:center}",
      "#mh-pm-preview-box img{max-width:94vw;max-height:84vh;object-fit:contain;background:#000;border-radius:4px}",
      "#mh-pm-preview-meta{color:#f5f8fa;font-size:13px;text-align:center;max-width:90vw;word-break:break-all}",
      "#mh-pm-preview-actions{display:flex;gap:8px}"
    ].join("");
    document.head.appendChild(style);
  }

  function ensureHub() {
    if (hubEl && document.body.contains(hubEl)) return hubEl;
    ensureHubStyle();
    var el = document.createElement("div");
    el.id = "mh-hub";
    el.innerHTML = `
      <div class="container-fluid">
        <div class="mh-hub-head">
          <h2>MineHub</h2>
          <span id="mh-hub-status" class="mh-hub-status"></span>
        </div>
        <ul id="mh-hub-tabs" class="nav nav-tabs mb-3">
          <li class="nav-item"><a href="#" class="nav-link active" data-mh-tab="search">搜索</a></li>
          <li class="nav-item"><a href="#" class="nav-link" data-mh-tab="qq">QQ 缓存</a></li>
          <li class="nav-item"><a href="#" class="nav-link" data-mh-tab="faces">人脸聚类</a></li>
          <li class="nav-item"><a href="#" class="nav-link" data-mh-tab="dupes">重复检测</a></li>
          <li class="nav-item"><a href="#" class="nav-link" data-mh-tab="settings">设置</a></li>
        </ul>
        <div id="mh-tab-search" class="mh-tab-pane">
          <div class="input-group mb-2" style="max-width:760px">
            <input id="mh-q" class="form-control" placeholder="中文/英文描述搜图，或输入图片/场景 ID">
            <div class="input-group-append"><button id="mh-go" class="btn btn-primary">搜索</button></div>
          </div>
          <div class="d-flex flex-wrap align-items-center mb-2" style="max-width:900px;gap:6px">
            <label for="mh-mode" class="small text-muted mb-0 mr-1 mh-mode-label">模式</label>
            <select id="mh-mode" class="form-control form-control-sm mr-2" style="width:122px">
              <option value="semantic">语义搜索</option>
              <option value="regex">正则 / 关键词</option>
            </select>
            <label for="mh-kind" class="small text-muted mb-0 mr-1 mh-kind-label">范围</label>
            <select id="mh-kind" class="form-control form-control-sm mr-2" style="width:92px">
              <option value="all">全部</option>
              <option value="image">图片</option>
              <option value="scene">场景</option>
            </select>
            <label for="mh-match" class="small text-muted mb-0 mr-1">多关键词</label>
            <select id="mh-match" class="form-control form-control-sm mr-2" style="width:92px">
              <option value="all">全部命中</option>
              <option value="any">任一命中</option>
            </select>
            <label id="mh-ignore-wrap" class="small text-muted mb-0 mr-2" style="display:none">
              <input id="mh-ignore-case" type="checkbox" checked> 不区分大小写
            </label>
            <span id="mh-sep-hint" class="small text-muted">分隔：； ; ， , 、 | 换行</span>
          </div>
          <div id="mh-score-row">
            <label for="mh-min-score" class="small text-muted mb-0 mr-2">相似度 ≥ <span id="mh-min-score-val">0.055</span></label>
            <input id="mh-min-score" type="range" min="0" max="0.5" step="0.005" value="0.055" class="custom-range flex-grow-1" style="min-width:220px">
            <span id="mh-score-presets" class="ml-2"></span>
          </div>
          <div id="mh-regex-presets">
            <span class="small text-muted mr-2">正则模板</span>
            <button type="button" class="mh-preset" data-regex="\.gif$">GIF</button>
            <button type="button" class="mh-preset" data-regex="\.(jpe?g|png|webp)$">静态图</button>
            <button type="button" class="mh-preset" data-regex="\.(mp4|webm|mov|mkv)$">视频</button>
            <button type="button" class="mh-preset" data-regex="\.null$">.null</button>
            <button type="button" class="mh-preset" data-regex="^[0-9a-f]{32}\.(jpg|png|gif)$">QQ 哈希名</button>
            <button type="button" class="mh-preset" data-regex="电脑|显示器|屏幕|笔记本">电脑相关</button>
            <button type="button" class="mh-preset" data-regex="动漫|二次元|anime">二次元</button>
            <button type="button" class="mh-preset" data-regex="qq|腾讯">QQ 标签</button>
          </div>
          <div class="d-flex flex-wrap align-items-center mb-2" style="max-width:900px">
            <label for="mh-top" class="small text-muted mb-0 mr-2">结果数</label>
            <input id="mh-top" type="number" min="1" max="100" step="1" value="24" class="form-control form-control-sm" style="width:76px">
            <span id="mh-top-presets" class="ml-2"></span>
            <span class="small text-muted ml-2">最多 100</span>
          </div>
          <div class="mb-2"><span id="mh-title" class="text-muted"></span></div>
          <div id="mh-status" class="text-muted mb-3"></div>
          <div id="mh-search-actions" class="flex-wrap align-items-center mb-3" style="display:none">
            <span id="mh-search-selected-count" class="text-muted mr-3">已选 0 个</span>
            <button id="mh-search-trash" type="button" class="btn btn-secondary btn-sm mr-2">放入回收站</button>
            <button id="mh-search-delete" type="button" class="btn btn-danger btn-sm mr-2">直接删除文件</button>
            <button id="mh-search-clear" type="button" class="btn btn-secondary btn-sm">取消选择</button>
          </div>
          <div id="mh-search-hint" class="mh-empty-state">
            <strong>搜索 MineHub 图库</strong>
            语义模式按画面含义查找；正则模式按文件名、路径、标签和 ID 匹配。多个关键词用 <code>；</code> <code>;</code> <code>，</code> <code>,</code> <code>、</code> 或换行分隔。
            <p class="small text-muted mb-0 mt-2">图片或场景卡片上的放大镜会用 Stash 原生页面预览；勾选后可批量放入回收站或永久删除。</p>
          </div>
          <div id="mh-results" class="mh-card-grid"></div>
        </div>
        <div id="mh-tab-qq" class="mh-tab-pane" style="display:none">
          <div class="card mb-2"><div class="card-body py-2">
            <div class="form-row align-items-center">
              <div class="col-auto mb-1"><select id="mh-pm-root" class="form-control form-control-sm" title="扫描目录"></select></div>
              <div class="col-auto mb-1"><button id="mh-pm-scan" class="btn btn-primary btn-sm">扫描</button></div>
              <div class="col-auto mb-1"><select id="mh-pm-kind" class="form-control form-control-sm"><option value="all">图片+视频</option><option value="image">仅图片</option><option value="video">仅视频</option></select></div>
              <div class="col-auto mb-1"><select id="mh-pm-scope" class="form-control form-control-sm"><option value="all">Ori+Thumb</option><option value="ori">仅 Ori</option><option value="thumb">仅 Thumb</option></select></div>
              <div class="col-auto mb-1"><input id="mh-pm-min" type="number" min="0" step="0.1" placeholder="最小 MB" class="form-control form-control-sm" style="width:90px"></div>
              <div class="col-auto mb-1"><input id="mh-pm-text" placeholder="文件名 / 子目录" class="form-control form-control-sm" style="width:150px"></div>
              <div class="col-auto mb-1"><select id="mh-pm-sort" class="form-control form-control-sm"><option value="size">按大小</option><option value="mtime">按时间</option><option value="name">按名称</option><option value="chat">按归属</option><option value="path">按路径</option></select></div>
              <div class="col-auto mb-1"><select id="mh-pm-dir" class="form-control form-control-sm"><option value="desc">降序</option><option value="asc">升序</option></select></div>
              <div class="col-auto mb-1"><select id="mh-pm-cat" class="form-control form-control-sm"><option value="all">全部分类</option><option value="nsfw">仅 NSFW</option><option value="safe">仅安全</option><option value="daily">日常</option><option value="screenshot">截图</option><option value="anime">二次元</option><option value="adult">成人</option><option value="sexy">性感</option><option value="sticker">表情包</option><option value="review">待复核</option><option value="other">其他</option></select></div>
              <div class="col-auto mb-1"><select id="mh-pm-level" class="form-control form-control-sm"><option value="all">全部等级</option><option value="safe">安全</option><option value="suggestive">擦边</option><option value="explicit">露骨</option></select></div>
              <div class="col-auto mb-1"><input id="mh-pm-tags" placeholder="标签(空格)" class="form-control form-control-sm" style="width:120px"></div>
              <div class="col-auto mb-1"><div class="form-check form-check-inline"><input id="mh-pm-only" type="checkbox" class="form-check-input"><label class="form-check-label" for="mh-pm-only">仅已打标</label></div></div>
              <div class="col-auto mb-1"><div class="form-check form-check-inline"><input id="mh-pm-review" type="checkbox" class="form-check-input"><label class="form-check-label" for="mh-pm-review">仅待复核</label></div></div>
              <div class="col-auto mb-1"><button id="mh-pm-labels" class="btn btn-secondary btn-sm">重载标签</button></div>
              <div class="col-auto mb-1"><button id="mh-pm-index" class="btn btn-secondary btn-sm">更新归属索引</button></div>
            </div>
          </div></div>
          <div class="row">
            <aside id="mh-pm-side" class="col-12 col-lg-3 mb-2">
              <div class="card"><div class="card-body py-2">
                <select id="mh-pm-chatmode" class="form-control form-control-sm mb-2"><option value="off">不过滤聊天</option><option value="include">仅显示勾选</option><option value="exclude">排除勾选</option></select>
                <input id="mh-pm-chatsearch" placeholder="搜索好友 / 群…" class="form-control form-control-sm mb-2">
                <div class="form-check"><input id="mh-pm-unknown" type="checkbox" class="form-check-input"><label class="form-check-label" for="mh-pm-unknown">显示无归属文件</label></div>
                <div class="form-check"><input id="mh-pm-mapped" type="checkbox" class="form-check-input"><label class="form-check-label" for="mh-pm-mapped">仅显示有归属</label></div>
                <div id="mh-pm-chats"></div>
              </div></div>
            </aside>
            <main class="col-12 col-lg-9">
              <div id="mh-pm-tools" class="d-flex flex-wrap align-items-center">
                <button id="mh-pm-all" class="btn btn-secondary btn-sm mr-1">全选本页</button>
                <button id="mh-pm-none" class="btn btn-secondary btn-sm mr-1">清空选择</button>
                <button id="mh-pm-move" class="btn btn-primary btn-sm mr-1">移动到…</button>
                <button id="mh-pm-del" class="btn btn-secondary btn-sm mr-1">移入回收站</button>
                <button id="mh-pm-open" class="btn btn-secondary btn-sm mr-1">系统打开</button>
                <span class="mh-pm-count text-muted ml-auto"></span>
              </div>
              <div id="mh-pm-grid" class="mh-card-grid"></div>
              <div id="mh-pm-pager" class="d-flex align-items-center justify-content-center my-2">
                <button id="mh-pm-prev" class="btn btn-secondary btn-sm mr-2">上一页</button>
                <span id="mh-pm-pageinfo" class="text-muted mr-2">-</span>
                <button id="mh-pm-next" class="btn btn-secondary btn-sm">下一页</button>
              </div>
            </main>
          </div>
        </div>
        <div id="mh-tab-faces" class="mh-tab-pane" style="display:none">
          <div class="mh-placeholder">
            <h4>人脸聚类</h4>
            <p>用 InsightFace 提取人脸特征，按相似度聚类后在这里按人物浏览；命名确认后可写入 MineHub 演员或标签。当前尚未运行，先保留入口。</p>
          </div>
        </div>
        <div id="mh-tab-dupes" class="mh-tab-pane" style="display:none">
          <div class="card mb-2"><div class="card-body py-2">
            <div class="form-row align-items-center">
              <div class="col-auto mb-1"><select id="mh-dupe-mode" class="form-control form-control-sm"><option value="similar">相似图片</option><option value="exact">完全相同文件</option></select></div>
              <div class="col-auto mb-1" id="mh-dupe-scope-wrap"><select id="mh-dupe-scope" class="form-control form-control-sm"><option value="library">MineHub 库</option><option value="qq">QQ 图片缓存</option><option value="folder">指定文件夹（图片+视频）</option><option value="scene">Stash 场景（视频 pHash）</option></select></div>
              <div class="col-auto mb-1" id="mh-dupe-folder-wrap" style="display:none"><input id="mh-dupe-root" class="form-control form-control-sm" placeholder="文件夹路径，例如 D:\\Tencent Files\\...\\Thumb" style="width:360px"></div>
              <div class="col-auto mb-1" id="mh-dupe-recursive-wrap" style="display:none"><div class="form-check form-check-inline"><input id="mh-dupe-recursive" type="checkbox" class="form-check-input" checked><label class="form-check-label" for="mh-dupe-recursive">含子文件夹</label></div></div>
              <div class="col-auto mb-1" id="mh-dupe-algo-wrap"><select id="mh-dupe-algo" class="form-control form-control-sm"><option value="phash">pHash DCT（推荐）</option><option value="dhash">dHash 梯度</option><option value="ahash">aHash 均值</option></select></div>
              <div class="col-auto mb-1" id="mh-dupe-scan-wrap"><button id="mh-dupe-scan" class="btn btn-primary btn-sm">扫描并计算</button></div>
              <div class="col-auto mb-1"><button id="mh-dupe-query" class="btn btn-secondary btn-sm">重新分组</button></div>
            </div>
            <div id="mh-dupe-similar-opts" class="d-flex align-items-center mt-2" style="max-width:760px">
              <label for="mh-dupe-threshold" class="small text-muted mb-0 mr-2">严格距离阈值 <span id="mh-dupe-threshold-val">10</span></label>
              <input id="mh-dupe-threshold" type="range" min="0" max="40" step="1" value="10" class="custom-range flex-grow-1">
              <span class="small text-muted ml-2">严格 0 · 宽松 40</span>
            </div>
            <div id="mh-dupe-status" class="small text-muted mt-2">选择范围后点击「扫描并计算」；调阈值只重新分组，不重算哈希。</div>
          </div></div>
          <div id="mh-dupe-hint" class="mh-empty-state">
            <strong>相似图片、视频与重复文件</strong>
            「指定文件夹」会递归扫描图片和视频；图片使用 256 位感知哈希，视频抽取 5 帧 pHash 并按最差帧距离比较。分组采用严格全连接：组内任意两张都必须低于阈值，避免只靠一张“代表图”把不相关内容串进来。阈值越小越严格；0 只接受哈希完全一致。完全相同文件直接读取 MineHub 账本里已有的 MD5。
          </div>
          <div id="mh-dupe-results"></div>
        </div>
        <div id="mh-tab-settings" class="mh-tab-pane" style="display:none">
          <div class="mh-placeholder">
            <h4>MineHub 服务</h4>
            <p>搜索、QQ 缓存和相似索引由 MineHub 同源网关提供，不再使用独立端口。标签重载、QQ 归属索引重建在「QQ 缓存」页操作。</p>
          </div>
        </div>
        <div id="mh-pm-preview">
          <div id="mh-pm-preview-box">
            <img id="mh-pm-preview-img" alt="">
            <div id="mh-pm-preview-meta"></div>
            <div id="mh-pm-preview-actions">
              <button id="mh-pm-preview-open" class="btn btn-secondary btn-sm">系统打开</button>
              <button id="mh-pm-preview-close" class="btn btn-primary btn-sm">关闭</button>
            </div>
          </div>
        </div>
      </div>`;
    var mount = document.querySelector(".main.container-fluid") || document.body;
    mount.appendChild(el);
    hubEl = el;

    document.getElementById("mh-hub-tabs").addEventListener("click", function (e) {
      var link = e.target.closest("[data-mh-tab]");
      if (!link) return;
      e.preventDefault();
      activateTab(link.dataset.mhTab);
    });
    document.getElementById("mh-pm-scan").onclick = pmScan;
    document.getElementById("mh-pm-labels").onclick = function () {
      pmFetch("/reload-labels", {}).then(function (j) {
        pmSetStatus("标签已重载：" + j.labels + " 条");
        pmQuery();
      }).catch(function (e) { pmSetStatus("重载标签失败：" + e.message); });
    };
    document.getElementById("mh-pm-index").onclick = pmBuildIndex;
    document.getElementById("mh-pm-all").onclick = function () {
      PM.records.forEach(function (r) { PM.selected[r.path] = true; });
      pmRenderSelection();
    };
    document.getElementById("mh-pm-none").onclick = function () {
      PM.selected = Object.create(null);
      pmRenderSelection();
    };
    document.getElementById("mh-pm-move").onclick = pmMove;
    document.getElementById("mh-pm-del").onclick = pmRecycle;
    document.getElementById("mh-pm-open").onclick = pmOpenSelected;
    document.getElementById("mh-pm-prev").onclick = function () { if (PM.page > 1) { PM.page--; pmQuery(); } };
    document.getElementById("mh-pm-next").onclick = function () { if (PM.page < PM.pages) { PM.page++; pmQuery(); } };
    document.getElementById("mh-pm-preview-close").onclick = function () {
      document.getElementById("mh-pm-preview").classList.remove("open");
    };
    document.getElementById("mh-pm-preview").addEventListener("click", function (e) {
      if (e.target.id === "mh-pm-preview") e.target.classList.remove("open");
    });
    document.getElementById("mh-go").onclick = searchText;
    document.getElementById("mh-q").onkeydown = function (e) { if (e.key === "Enter") searchText(); };
    document.getElementById("mh-mode").addEventListener("change", function () {
      updateModeUI();
      rerunWithOptions();
    });
    ["mh-kind", "mh-match", "mh-ignore-case"].forEach(function (id) {
      document.getElementById(id).addEventListener("change", rerunWithOptions);
    });
    var regexButtons = document.querySelectorAll("#mh-regex-presets [data-regex]");
    for (var ri = 0; ri < regexButtons.length; ri++) {
      regexButtons[ri].onclick = function () {
        var input = document.getElementById("mh-q");
        if (input) input.value = this.dataset.regex;
        searchText();
      };
    }
    document.getElementById("mh-min-score").addEventListener("input", function () {
      updateScoreLabel();
      renderScorePresets();
      rerunWithOptions();
    });
    document.getElementById("mh-top").addEventListener("input", function () {
      renderTopPresets();
      rerunWithOptions();
    });
    document.getElementById("mh-top").addEventListener("change", function () {
      setTopValue(topValue());
    });
    document.getElementById("mh-search-trash").onclick = function () { searchDelete("trash"); };
    document.getElementById("mh-search-delete").onclick = function () { searchDelete("delete"); };
    document.getElementById("mh-search-clear").onclick = clearSearchSelection;
    renderScorePresets();
    renderTopPresets();
    updateModeUI();
    updateSearchActions();
    document.getElementById("mh-dupe-mode").addEventListener("change", dupeToggleMode);
    document.getElementById("mh-dupe-scan").onclick = dupeScan;
    document.getElementById("mh-dupe-root").addEventListener("keydown", function (e) {
      if (e.key === "Enter") dupeScan();
    });
    document.getElementById("mh-dupe-query").onclick = dupeQuery;
    ["mh-dupe-scope", "mh-dupe-algo"].forEach(function (id) {
      document.getElementById(id).addEventListener("change", function () {
        dupeUpdateScopeControls();
        dupeQuery();
      });
    });
    document.getElementById("mh-dupe-threshold").addEventListener("input", function () {
      var label = document.getElementById("mh-dupe-threshold-val");
      if (label) label.textContent = pmValue("mh-dupe-threshold");
      clearTimeout(DUPE.timer);
      DUPE.timer = setTimeout(dupeQuery, 250);
    });
    document.getElementById("mh-pm-chatsearch").addEventListener("input", pmRenderChats);
    document.getElementById("mh-pm-chatmode").addEventListener("change", pmUpdateChatControls);
    ["mh-pm-kind", "mh-pm-scope", "mh-pm-sort", "mh-pm-dir", "mh-pm-cat", "mh-pm-level",
      "mh-pm-only", "mh-pm-review", "mh-pm-chatmode", "mh-pm-unknown", "mh-pm-mapped"].forEach(function (id) {
      var e = document.getElementById(id);
      if (e) e.addEventListener("change", function () { PM.page = 1; pmSchedule(); });
    });
    ["mh-pm-min", "mh-pm-tags", "mh-pm-text"].forEach(function (id) {
      var e = document.getElementById(id);
      if (e) e.addEventListener("input", function () { PM.page = 1; pmSchedule(); });
    });
    return el;
  }

  function activateTab(name) {
    var links = document.querySelectorAll("#mh-hub-tabs [data-mh-tab]");
    for (var i = 0; i < links.length; i++) links[i].classList.toggle("active", links[i].dataset.mhTab === name);
    ["search", "qq", "faces", "dupes", "settings"].forEach(function (t) {
      var p = document.getElementById("mh-tab-" + t);
      if (p) p.style.display = t === name ? "" : "none";
    });
    if (name === "qq") ensurePmLoaded();
    if (name === "dupes") dupeInit();
    if (name === "search") {
      var results = document.getElementById("mh-results");
      var hint = document.getElementById("mh-search-hint");
      if (hint && (!results || !results.children.length)) hint.style.display = "";
    }
  }

  function pageQuery() {
    var p = new URLSearchParams(location.search);
    var id = p.get("stash_id") || "";
    var kind = p.get("kind") || (id ? "image" : "all");
    return {
      id: id,
      kind: kind === "image" || kind === "scene" ? kind : "all",
      text: p.get("q") || p.get("text") || "",
      mode: p.get("mode") === "regex" ? "regex" : "semantic",
      match: p.get("match") === "any" ? "any" : "all",
      tab: p.get("tab") || "search"
    };
  }

  function runPageQuery() {
    var p = pageQuery();
    if (p.tab !== "search") {
      activateTab(p.tab);
      return;
    }
    activateTab("search");
    var title = document.getElementById("mh-title");
    var hint = document.getElementById("mh-search-hint");
    var input = document.getElementById("mh-q");
    var modeEl = document.getElementById("mh-mode");
    var kindEl = document.getElementById("mh-kind");
    var matchEl = document.getElementById("mh-match");
    if (modeEl) modeEl.value = p.id ? "semantic" : p.mode;
    if (kindEl) kindEl.value = p.kind;
    if (matchEl) matchEl.value = p.match;
    updateModeUI();
    if (p.id) {
      setScoreRange("image");
      if (title) title.textContent = "相似于 " + (p.kind === "scene" ? "场景" : "图片") + " #" + p.id;
      if (hint) hint.style.display = "none";
      doSearch({ stash_id: String(p.id), kind: p.kind, top: topValue(), min_score: scoreValue() });
    } else if (p.text) {
      if (input) input.value = p.text;
      if (title) title.textContent = p.mode === "regex" ? "MineHub 正则搜索" : "MineHub 搜索";
      if (hint) hint.style.display = "none";
      searchText();
    } else {
      setScoreRange("text");
      if (title) title.textContent = "";
      var results = document.getElementById("mh-results");
      if (hint && (!results || !results.children.length)) hint.style.display = "";
    }
  }

  function syncPage() {
    var onPage = location.pathname === PAGE_PATH;
    var navItem = document.getElementById("mh-nav-item");
    if (navItem) navItem.classList.toggle("active", onPage);
    if (!onPage) {
      if (hubEl) hubEl.classList.remove("open");
      return;
    }
    ensureHub();
    var main = document.querySelector(".main.container-fluid");
    if (main && hubEl.parentElement !== main) main.appendChild(hubEl);
    hubEl.classList.add("open");
    var raw = location.search || "";
    if (raw !== PAGE_QUERY) {
      PAGE_QUERY = raw;
      runPageQuery();
    }
  }

  function openHub(tab) {
    if (location.pathname !== PAGE_PATH) {
      var q = tab && tab !== "search" ? "?tab=" + encodeURIComponent(tab) : "";
      location.assign(PAGE_PATH + q);
      return;
    }
    syncPage();
    activateTab(tab || "search");
  }

  function openSearch(ctx) {
    var qs = new URLSearchParams();
    if (ctx && ctx.id) {
      qs.set("stash_id", String(ctx.id));
      qs.set("kind", ctx.kind || "image");
    }
    location.assign(PAGE_PATH + (qs.toString() ? "?" + qs.toString() : ""));
  }

  function ensurePmLoaded() {
    if (PM.loaded || PM.loading) return;
    PM.loading = true;
    pmSetStatus("加载配置…");
    Promise.all([pmFetch("/pm/config"), pmFetch("/pm/chats")]).then(function (res) {
      PM.cfg = res[0];
      PM.chats = res[1].chats || [];
      PM.loaded = true;
      pmRenderRoots();
      pmRenderChats();
      pmUpdateChatControls();
      pmSetStatus("配置已加载，选择目录后点击扫描");
    }).catch(function (e) {
      pmSetStatus("加载失败：" + e.message);
    }).finally(function () {
      PM.loading = false;
    });
  }

  function openPm() {
    openHub("qq");
    ensurePmLoaded();
  }

  function pmSetStatus(text) {
    setStatus(text);
    var el = document.getElementById("mh-hub-status");
    if (el) el.textContent = text || "";
  }

  function injectNavItem() {
    var nav = document.querySelector(".top-nav .navbar-nav");
    if (!nav || document.getElementById("mh-nav-item")) return;
    var item = document.createElement("div");
    item.id = "mh-nav-item";
    item.className = "col-4 col-sm-3 col-md-2 col-lg-auto nav-link";
    item.innerHTML = '<a href="/mh" class="minimal p-4 p-xl-2 d-flex d-xl-inline-block flex-column justify-content-between align-items-center btn btn-primary">' +
      '<svg data-prefix="fas" data-icon="magnifying-glass" class="svg-inline--fa fa-magnifying-glass fa-icon nav-menu-icon d-block d-xl-inline mb-2 mb-xl-0" role="img" viewBox="0 0 512 512" aria-hidden="true"><path fill="currentColor" d="M416 208c0 45.9-14.9 88.3-40 122.7L502.6 457.4c12.5 12.5 12.5 32.8 0 45.3s-32.8 12.5-45.3 0L330.7 376C296.3 401.1 253.9 416 208 416 93.1 416 0 322.9 0 208S93.1 0 208 0 416 93.1 416 208zM208 352a144 144 0 1 0 0-288 144 144 0 1 0 0 288z"></path></svg>' +
      '<span>MineHub</span></a>';
    item.querySelector("a").onclick = function (e) { e.preventDefault(); openHub("search"); };
    nav.appendChild(item);
  }

  function injectDetailButton() {
    var m = location.pathname.match(/^\/(images|scenes)\/(\d+)(?:$|\/)/);
    var bar = document.querySelector(".image-toolbar, .scene-toolbar");
    var old = document.getElementById("mh-detail-sim");
    if (!m || !bar) {
      if (old) old.remove();
      return;
    }
    var kind = m[1] === "images" ? "image" : "scene";
    if (old) {
      old.onclick = function () { openSearch({ id: m[2], kind: kind }); };
      return;
    }
    var b = document.createElement("button");
    b.id = "mh-detail-sim";
    b.type = "button";
    b.className = "minimal btn btn-secondary";
    b.title = "找相似";
    b.style.flex = "0 0 auto";
    b.style.whiteSpace = "nowrap";
    b.style.height = "36px";
    b.style.alignSelf = "center";
    b.style.padding = "0 10px";
    b.innerHTML = '<svg data-prefix="fas" data-icon="magnifying-glass" class="svg-inline--fa fa-magnifying-glass fa-icon" role="img" viewBox="0 0 512 512" aria-hidden="true"><path fill="currentColor" d="M416 208c0 45.9-14.9 88.3-40 122.7L502.6 457.4c12.5 12.5 12.5 32.8 0 45.3s-32.8 12.5-45.3 0L330.7 376C296.3 401.1 253.9 416 208 416 93.1 416 0 322.9 0 208S93.1 0 208 0 416 93.1 416 208zM208 352a144 144 0 1 0 0-288 144 144 0 1 0 0 288z"></path></svg><span class="ml-1">找相似</span>';
    b.onclick = function () { openSearch({ id: m[2], kind: kind }); };
    bar.appendChild(b);
  }

  function injectGifNote() {
    var m = location.pathname.match(/^\/images\/(\d+)(?:$|\/)/);
    var panel = document.querySelector(".file-info-panel");
    var note = document.getElementById("mh-gif-note");
    if (!m || !panel) {
      if (note) note.remove();
      if (!m) GIF_INFO = null;
      return;
    }
    var id = m[1];
    if (GIF_INFO && GIF_INFO.id === id) {
      if (!note) panel.insertBefore(GIF_INFO.node, panel.firstChild);
      return;
    }
    if (note) note.remove();
    GIF_INFO = { id: id, node: null };
    fetch(BASE + "/media/info?kind=image&id=" + encodeURIComponent(id))
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (j) {
        if (!GIF_INFO || GIF_INFO.id !== id) return;
        if (!j.is_gif || Number(j.frames) > 1) return;
        var body = document.querySelector(".file-info-panel");
        if (!body) return;
        var box = document.createElement("div");
        box.id = "mh-gif-note";
        box.innerHTML = "<strong>单帧 GIF</strong>：这个 GIF 只有一个画面，不是 MineHub 查看器故障。";
        GIF_INFO.node = box;
        body.insertBefore(box, body.firstChild);
      })
      .catch(function () {});
  }

  function installNativeSearchBridge() {
    var path = location.pathname.replace(/\/+$/, "");
    if (path !== "/images" && path !== "/scenes") return;
    var inputs = document.querySelectorAll(".search-term-input input, .sidebar-search-container input");
    for (var i = 0; i < inputs.length; i++) {
      var input = inputs[i];
      if (!input.dataset.mhSemanticBound) {
        input.dataset.mhSemanticBound = "1";
        input.addEventListener("keydown", function (e) {
          if (e.key !== "Enter" || e.isComposing || e.keyCode === 229) return;
          var text = e.currentTarget.value.trim();
          if (!text) return;
          var current = location.pathname.replace(/\/+$/, "");
          var targetKind = current === "/images" ? "image" : (current === "/scenes" ? "scene" : "");
          if (!targetKind) return;
          e.preventDefault();
          e.stopPropagation();
          e.stopImmediatePropagation();
          var qs = new URLSearchParams({ q: text, kind: targetKind });
          location.assign(PAGE_PATH + "?" + qs.toString());
        }, true);
      }
      input.placeholder = "搜索…（回车用 MineHub 语义搜索）";
      input.title = "回车使用 MineHub 语义搜索；多个关键词用；或,分隔";
    }
  }

  function translateExact() {
    var map = {"File(s) Size": "文件大小", "Production Date": "制作日期"};
    var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    var n;
    while ((n = walker.nextNode())) {
      var t = n.nodeValue;
      if (!t) continue;
      var key = t.trim();
      if (map[key] && t === key) n.nodeValue = map[key];
    }
    var ops = document.querySelectorAll('[title="Operations"]');
    for (var i = 0; i < ops.length; i++) ops[i].setAttribute("title", "操作");
  }

  function polish() {
    document.title = document.title.replace(/\bStash\b/g, "MineHub");
    var brands = document.querySelectorAll(".brand-link");
    for (var i = 0; i < brands.length; i++) {
      if (brands[i].textContent.trim() === "Stash") brands[i].textContent = "MineHub";
    }
    injectNavItem();
    injectDetailButton();
    injectGifNote();
    installNativeSearchBridge();
    syncPage();
    ["mh-search-btn", "mh-pm-btn", "mh-sim-btn"].forEach(function (id) {
      var e = document.getElementById(id);
      if (e) e.remove();
    });
    var now = Date.now();
    if (now - lastTranslate > 700) {
      lastTranslate = now;
      translateExact();
    }
  }

  function update() {
    if (updateScheduled) return;
    updateScheduled = true;
    setTimeout(function () {
      updateScheduled = false;
      enforceDefaultSort();
      polish();
    }, 40);
  }

  new MutationObserver(update).observe(document.documentElement, { childList: true, subtree: true });
  window.addEventListener("popstate", update);
  window.addEventListener("hashchange", update);
  setInterval(update, 1000);
  update();
})();
