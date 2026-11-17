(function () {
  "use strict";

  var BASE = "/mh/api";
  var busy = false;
  var LAST_SEARCH = null;
  var QUEUED_SEARCH = null;
  var scoreTimer = null;
  var SCORE_KIND = "text";
  var SCORE_PRESETS = { text: [0.03, 0.055, 0.08, 0.12, 0.18], image: [0.65, 0.75, 0.82, 0.90, 0.95] };
  var DEFAULT_TOP = 24;
  var SIMILAR_TOP = 48;
  var TOP_PRESETS = [24, 48, 100];
  var PAGE_PATH = "/mh";
  var PAGE_QUERY = null;
  var GIF_INFO = null;
  var GIF_TIMELINE = null;
  var SEARCH_ITEMS = Object.create(null);
  var SEARCH_ORDER = [];
  var SEARCH_SELECTED = Object.create(null);
  var SEARCH_DELETED = Object.create(null);
  var SEARCH_BUSY = false;
  var SOURCE_SEQ = 0;
  var SIMILAR_SVG = '<svg data-prefix="fas" data-icon="magnifying-glass" class="svg-inline--fa fa-magnifying-glass fa-icon" role="img" viewBox="0 0 512 512" aria-hidden="true"><path fill="currentColor" d="M416 208c0 45.9-14.9 88.3-40 122.7L502.6 457.4c12.5 12.5 12.5 32.8 0 45.3s-32.8 12.5-45.3 0L330.7 376C296.3 401.1 253.9 416 208 416 93.1 416 0 322.9 0 208S93.1 0 208 0 416 93.1 416 208zM208 352a144 144 0 1 0 0-288 144 144 0 1 0 0 288z"></path></svg>';
  var WALL_PREVIEW_SVG = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12z"></path><circle cx="12" cy="12" r="3"></circle></svg>';
  var WALL_PLAY_SVG = '<svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor" aria-hidden="true"><path d="M7 4.5v15l13-7.5z"></path></svg>';
  var MEDIA_VIEW = { items: [], index: 0, open: false };
  var INLINE_MODE_LABELS = { name: "名称", feature: "特征" };
  var INLINE_MODE_HINTS = {
    name: "标题或文件名，按 Enter 搜索…",
    feature: "描述画面或关键词，按 Enter 搜索…"
  };
  var INLINE_SIMILARITY_OPTIONS = [
    { value: 0, label: "相似度 不限" },
    { value: 0.03, label: "相似度 ≥ 0.030（宽松）" },
    { value: 0.055, label: "相似度 ≥ 0.055（默认）" },
    { value: 0.08, label: "相似度 ≥ 0.080（较严）" },
    { value: 0.12, label: "相似度 ≥ 0.120（严格）" },
    { value: 0.18, label: "相似度 ≥ 0.180（很严）" }
  ];
  var INLINE_ALL_FIELDS = ["title", "path", "basename", "tags", "id"];
  var INLINE_CLEAR_BOUND = false;
  var MAP = {
    points: [], groups: [], loaded: false, loading: false, highlight: null,
    hover: -1, screen: null, view: { zoom: 1, ox: 0, oy: 0 },
    drag: null, frame: 0, bound: false
  };
  var MAP_COLORS = [
    { hex: "#ff6b6b", rgb: "255,107,107" },
    { hex: "#ffb454", rgb: "255,180,84" },
    { hex: "#b388ff", rgb: "179,136,255" },
    { hex: "#58a6ff", rgb: "88,166,255" },
    { hex: "#5ed6a0", rgb: "94,214,160" },
    { hex: "#8b9aa6", rgb: "139,154,166" }
  ];
  var INLINE = {
    modeBar: null, scoreBar: null, input: null, path: "", kind: "", query: "", mode: "",
    minScore: 0.055, seq: 0, controller: null, active: false, searching: false, error: "",
    nativeImages: [], nativeScenes: [], listeners: [],
    patchInstalled: false, revision: 0, emptySet: new Set(), noop: function () {},
    pageSize: 100, offset: 0, hasMore: false, loadingMore: false, moreController: null,
    moreError: "", seen: Object.create(null), scrollBound: false, regex: false
  };

  function storedInlineMode() {
    try {
      var mode = localStorage.getItem("mh_inline_mode");
      if (mode === "semantic" || mode === "keyword" || mode === "regex") mode = "feature";
      return INLINE_MODE_LABELS[mode] ? mode : "feature";
    } catch (e) {
      return "feature";
    }
  }
  function storedInlineRegex() {
    try {
      if (localStorage.getItem("mh_inline_regex") === "1") return true;
      return localStorage.getItem("mh_inline_mode") === "regex";
    } catch (e) {
      return false;
    }
  }
  function storedInlineMinScore() {
    try {
      var saved = localStorage.getItem("mh_inline_min_score");
      if (saved === null || saved === "") return 0.055;
      var raw = Number(saved);
      for (var i = 0; i < INLINE_SIMILARITY_OPTIONS.length; i++) {
        if (INLINE_SIMILARITY_OPTIONS[i].value === raw) return raw;
      }
    } catch (e) {}
    return 0.055;
  }
  INLINE.mode = storedInlineMode();
  INLINE.minScore = storedInlineMinScore();
  INLINE.regex = storedInlineRegex();

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
    indexTimer: null,
    dupePoll: null,
    dupeGroups: []
  };

  var NATIVE_SELECTION = { image: new Set(), scene: new Set() };
  var FOLDER = {
    path: "F:\\MineHubData\\safe",
    records: [],
    selected: Object.create(null),
    page: 1,
    pages: 1,
    total: 0,
    loaded: false,
    loading: false,
    initialized: false,
    seq: 0,
    anchor: -1,
    dragBound: false,
    suppressClick: false,
    drag: null
  };

  var LIST_DEFAULTS = { path: "", applied: false };
  var NINE = {
    folder: "F:\\MineHubData\\review\\qwen3vltest9pic",
    paths: [],
    cells: [],
    initialized: false,
    running: false
  };

  function listPath() {
    var path = location.pathname || "";
    while (path.length > 1 && path.charAt(path.length - 1) === "/") {
      path = path.slice(0, -1);
    }
    return path;
  }

  function ensureSortUi() {
    var bar = document.querySelector(".filtered-list-toolbar .sort-by-select");
    if (!bar) return;
    var toggle = bar.querySelector(".dropdown-toggle");
    if (!toggle) return;
    var label = (toggle.textContent || "").trim();
    var isSize = label === "文件大小" || label.toLowerCase().indexOf("file") >= 0;
    if (!isSize) {
      toggle.click();
      setTimeout(function () {
        var option = document.querySelector('a.sort-by-option[data-value="filesize"]');
        if (option) {
          option.click();
          setTimeout(ensureSortUi, 200);
        }
      }, 80);
      return;
    }
    var buttons = bar.querySelectorAll(":scope > button");
    for (var i = 0; i < buttons.length; i++) {
      var icon = buttons[i].querySelector('svg[data-icon="caret-up"], svg[data-icon="caret-down"]');
      if (icon && icon.getAttribute("data-icon") === "caret-up") {
        buttons[i].click();
        return;
      }
    }
  }

  function ensureWallUi() {
    if (document.querySelector(".wall-item")) return;
    var button = document.querySelector('button[title="预览墙"], button[title="Wall"], button[title*="墙"]');
    if (button) button.click();
  }

  function applyListDefaults() {
    var path = listPath();
    if (path !== "/images" && path !== "/scenes") {
      LIST_DEFAULTS.path = "";
      LIST_DEFAULTS.applied = false;
      return;
    }
    if (LIST_DEFAULTS.path !== path) {
      LIST_DEFAULTS.path = path;
      LIST_DEFAULTS.applied = false;
    }
    if (LIST_DEFAULTS.applied) return;
    LIST_DEFAULTS.applied = true;
    var params = new URLSearchParams(location.search || "");
    var changed = false;
    if (!params.has("sortby")) {
      params.set("sortby", "filesize");
      params.set("sortdir", "desc");
      changed = true;
    }
    if (!params.has("disp")) {
      params.set("disp", "2");
      changed = true;
    }
    if (!params.has("perPage")) {
      params.set("perPage", "200");
      changed = true;
    }
    if (!changed) return;
    var url = path + "?" + params.toString();
    try {
      history.replaceState(history.state, "", url);
      window.dispatchEvent(new PopStateEvent("popstate", { state: history.state }));
    } catch (e) {}
    setTimeout(function () {
      if (listPath() !== path) return;
      ensureWallUi();
      ensureSortUi();
    }, 700);
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
      ".mh-inline-modes .btn{font-size:.875rem;padding:.375rem .55rem}",
      ".mh-inline-modes .mh-inline-regex.active{background:#8957e5!important;border-color:#a371f7!important;color:#fff!important}",
      ".mh-inline-score{width:auto;min-width:10rem;font-size:.875rem;padding:.375rem .5rem}",
      ".mh-native-input-hidden{display:none!important}",
      ".mh-inline-input-box{display:flex;flex:1 1 auto;align-items:center;gap:6px;min-width:220px}",
      ".mh-inline-input{flex:1 1 auto;min-width:0}",
      ".mh-inline-clear{flex:0 0 auto;background:#26333f;color:#cbd6df;border:1px solid #40515e;border-radius:6px;padding:6px 9px;cursor:pointer}",
      ".mh-inline-native{display:none!important}",
      ".image-card.grid-card .card-section-title .TruncatedText{display:block!important;white-space:nowrap!important;overflow:hidden!important;text-overflow:ellipsis!important;-webkit-line-clamp:1!important}",
      ".mh-feature-pop{position:fixed;z-index:2147483645;width:320px;max-height:72vh;overflow:auto;background:#172027;color:#dbe4eb;border:1px solid #3b4a55;border-radius:8px;box-shadow:0 14px 40px rgba(0,0,0,.55);padding:10px 12px;font:12px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}",
      ".mh-feature-pop h6{margin:2px 0 6px;color:#f5f8fa;font-size:12px;letter-spacing:.04em}",
      ".mh-feature-pop h6 span{color:#7f919f;font-weight:400;margin-left:6px}",
      ".mh-feature-chips{display:flex;flex-wrap:wrap;gap:5px;margin-bottom:9px}",
      ".mh-feature-chip{display:inline-block;padding:2px 6px;border-radius:4px;background:#23313d;color:#9fc2e0;font-size:11px;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}",
      ".mh-feature-chip.sem{background:#1e465f;color:#9fe0ff}",
      ".mh-feature-empty{color:#7f919f;font-size:11px;margin-bottom:8px}",
      ".mh-feature-foot{display:flex;justify-content:space-between;align-items:center;border-top:1px solid #2b3944;padding-top:7px;margin-top:2px}",
      ".mh-feature-foot a{color:#8ab4ff;text-decoration:none}",
      ".mh-native-search-active .card-check,.mh-native-search-active .wall-item-check{display:none!important}",
      ".mh-native-search-active .sort-by-select,.mh-native-search-active .page-size-selector{display:none!important}",
      ".mh-native-search-active .pagination-footer-container{display:none!important}",
      ".grid-card .card-controls{left:.5rem!important;right:auto!important}",
      ".wall-item{position:relative!important}",
      ".wall-item-check{left:.5rem!important;right:auto!important}",
      ".mh-wall-preview{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);z-index:40;width:38px;height:38px;display:flex;align-items:center;justify-content:center;padding:0;border:1px solid rgba(255,255,255,.7);border-radius:50%;background:rgba(13,17,23,.72);color:#fff;cursor:pointer;opacity:0;transition:opacity .12s}",
      ".wall-item:hover .mh-wall-preview{opacity:1}",
      ".mh-wall-preview svg{width:18px;height:18px;pointer-events:none}",
      ".mh-image-sim{position:absolute;right:8px;top:8px;z-index:20;width:28px;height:28px;display:flex;align-items:center;justify-content:center;padding:0;border:1px solid rgba(255,255,255,.6);border-radius:4px;background:rgba(13,17,23,.78);color:#fff;cursor:pointer;opacity:.9;z-index:60}",
      ".mh-image-sim:hover{background:#48aff0;border-color:#48aff0;color:#15212b}",
      ".mh-image-sim svg{width:14px;height:14px;pointer-events:none}",
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
      "#mh-pm-preview-actions button{background:#26333f;color:#fff;border:1px solid #4a5b69;border-radius:6px;padding:7px 12px;cursor:pointer}",
      "#mh-pm-dupe{display:none;position:fixed;inset:0;z-index:2147483647;background:rgba(0,0,0,.86);align-items:center;justify-content:center}",
      "#mh-pm-dupe.open{display:flex}",
      "#mh-pm-dupe-box{width:min(96vw,1180px);height:min(90vh,900px);display:flex;flex-direction:column;background:#111a21;border:1px solid #3b4a57;border-radius:10px;overflow:hidden}",
      "#mh-pm-dupe-head{display:flex;align-items:center;gap:12px;padding:10px 14px;border-bottom:1px solid #2b3944;color:#f0f5f8}",
      "#mh-pm-dupe-head strong{font-size:15px}",
      "#mh-pm-dupe-status{flex:1;color:#9fb0bd;font-size:12px}",
      "#mh-pm-dupe-head button{background:transparent;border:0;color:#cbd6df;font-size:22px;cursor:pointer}",
      "#mh-pm-dupe-tools{display:flex;flex-wrap:wrap;gap:6px;padding:8px 14px;border-bottom:1px solid #2b3944;background:#141d25}",
      "#mh-pm-dupe-tools button{background:#26333f;color:#e2e9ef;border:1px solid #3b4a57;border-radius:6px;padding:6px 10px;cursor:pointer;font-size:12px}",
      "#mh-pm-dupe-tools button.blue{background:#1f6feb;border-color:#1f6feb;color:#fff}",
      "#mh-pm-dupe-tools button.green{background:#238636;border-color:#2ea043;color:#fff}",
      "#mh-pm-dupe-tools button.red{background:#8b2f2f;border-color:#a44141;color:#fff}",
      "#mh-pm-dupe-note{padding:8px 14px 0;color:#9fb0bd;font-size:12px}",
      "#mh-pm-dupe-results{flex:1;overflow:auto;padding:12px 14px;display:flex;flex-direction:column;gap:12px}",
      ".mh-pm-dupe-group{background:#1a252e;border:1px solid #34434f;border-radius:8px;padding:10px}",
      ".mh-pm-dupe-group-head{display:flex;align-items:center;gap:10px;color:#dbe4eb;font-size:12px;margin-bottom:8px}",
      ".mh-pm-dupe-group-head strong{font-size:13px}",
      ".mh-pm-dupe-group-head button{background:#26333f;color:#e2e9ef;border:1px solid #4a5b69;border-radius:5px;padding:4px 8px;cursor:pointer;font-size:11px;margin-left:auto}",
      ".mh-pm-dupe-members{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:8px}",
      ".mh-pm-dupe-member{background:#0f161c;border:1px solid #2d3b47;border-radius:6px;overflow:hidden;min-width:0}",
      ".mh-pm-dupe-member img{display:block;width:100%;height:92px;object-fit:cover;background:#0a0f13}",
      ".mh-pm-dupe-member span{display:block;padding:4px 6px;color:#aab8c4;font-size:10px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}",
      ".mh-pm-dupe-member strong{display:block;padding:5px 6px 0;color:#dbe4eb;font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}",
      "#mh-media-viewer{display:none;position:fixed;inset:0;z-index:2147483647;background:rgba(3,6,9,.95);color:#fff;font:13px/1.4 system-ui,-apple-system,Segoe UI,sans-serif}",
      "#mh-media-viewer.open{display:flex;flex-direction:column}",
      "#mh-mv-stage{position:relative;flex:1 1 auto;min-height:0;width:100%;display:flex;align-items:center;justify-content:center;padding:34px 68px 6px;box-sizing:border-box}",
      "#mh-mv-stage img,#mh-mv-stage video{display:block;max-width:100%;max-height:100%;width:auto;height:auto;object-fit:contain;background:#000;border-radius:4px}",
      "#mh-mv-stage video{outline:none}",
      "#mh-mv-caption{flex:0 0 auto;display:flex;align-items:center;justify-content:center;gap:10px;max-width:92vw;padding:4px 8px 14px;color:#cfd8df;font-size:12px}",
      "#mh-mv-title{max-width:72vw;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}",
      "#mh-mv-count{flex:0 0 auto;color:#8b9aa6}",
      "#mh-mv-close{position:absolute;right:14px;top:10px;z-index:3;width:42px;height:42px;border:0;border-radius:50%;background:rgba(20,28,35,.7);color:#e6edf3;font-size:28px;line-height:1;cursor:pointer}",
      "#mh-mv-close:hover{background:#30363d}",
      "#mh-mv-prev,#mh-mv-next{position:absolute;top:50%;transform:translateY(-50%);z-index:3;width:46px;height:46px;display:flex;align-items:center;justify-content:center;padding:0;border:1px solid rgba(255,255,255,.28);border-radius:50%;background:rgba(20,28,35,.75);color:#fff;font-size:30px;line-height:1;cursor:pointer}",
      "#mh-mv-prev{left:10px}",
      "#mh-mv-next{right:10px}",
      "#mh-mv-prev:hover,#mh-mv-next:hover{background:#30363d}",
      "#mh-mv-prev:disabled,#mh-mv-next:disabled{display:none}",
      ".mh-gif-canvas{position:absolute;z-index:12;display:none;pointer-events:none;background:#000}",
      ".mh-gif-timeline{position:absolute;left:0;right:0;bottom:0;z-index:20;display:flex;align-items:center;gap:8px;padding:8px 10px;background:linear-gradient(180deg,rgba(0,0,0,0),rgba(0,0,0,.78));color:#fff;font:12px/1.2 system-ui,-apple-system,Segoe UI,sans-serif}",
      ".mh-gif-timeline button{flex:0 0 auto;width:26px;height:26px;padding:0;border:1px solid rgba(255,255,255,.42);border-radius:50%;background:rgba(20,28,35,.8);color:#fff;font-size:11px;line-height:1;cursor:pointer}",
      ".mh-gif-timeline input[type=range]{flex:1 1 auto;min-width:80px;accent-color:#58a6ff;cursor:pointer}",
      ".mh-gif-timeline .mh-gif-count{flex:0 0 auto;color:#e6edf3;font-variant-numeric:tabular-nums}",
      ".mh-training-move{display:inline-flex;align-items:center;gap:4px;white-space:nowrap}",
      ".mh-training-move svg{width:13px;height:13px;pointer-events:none}",
      "#mh-folder-status{color:#9fb0bd}",
      "#mh-folder-grid{min-height:180px;position:relative;user-select:none;-webkit-user-select:none}",
      ".mh-folder-card{position:relative;background:#11181d;border:1px solid #33414b;border-radius:8px;overflow:hidden;min-height:120px;cursor:pointer;user-select:none;-webkit-user-select:none}",
      ".mh-folder-card.sel{border-color:#58a6ff;box-shadow:0 0 0 1px #58a6ff inset}",
      ".mh-folder-card.sel img{opacity:.82}",
      ".mh-folder-card img{display:block;width:100%;height:150px;object-fit:cover;background:#0b1014;pointer-events:none;-webkit-user-drag:none}",
      ".mh-folder-card .mh-folder-chk{position:absolute;left:6px;top:6px;z-index:3;width:17px;height:17px;cursor:pointer}",
      ".mh-folder-card .mh-folder-meta{padding:6px 8px;font-size:11px;color:#9fb0bd;line-height:1.35}",
      ".mh-folder-card .mh-folder-name{color:#dbe4eb;font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}",
      ".mh-folder-card .mh-folder-sub{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}",
      ".mh-folder-video-tile{height:150px;display:flex;align-items:center;justify-content:center;flex-direction:column;gap:4px;background:#0b1014;color:#9fc2e0;font-size:12px}",
      ".mh-folder-video-tile b{font-size:20px;color:#58a6ff}",
      ".mh-folder-empty{grid-column:1/-1;color:#8394a2;text-align:center;padding:60px 10px}",
      ".mh-folder-marquee{position:fixed;z-index:2147483646;border:1px solid #58a6ff;background:rgba(88,166,255,.16);pointer-events:none}",
      "#mh-nine-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px;max-width:960px}",
      ".mh-nine-cell{position:relative;aspect-ratio:1/1;background:#0f161c;border:2px solid #33414b;border-radius:7px;overflow:hidden}",
      ".mh-nine-cell img{display:block;width:100%;height:100%;object-fit:cover;background:#0a0f13}",
      ".mh-nine-cell.keep{border-color:#3fb950;box-shadow:0 0 0 1px #3fb950 inset}",
      ".mh-nine-cell.excluded{opacity:.52}",
      ".mh-nine-pos{position:absolute;left:6px;top:6px;padding:2px 5px;border-radius:4px;background:rgba(0,0,0,.72);color:#fff;font-size:11px}",
      ".mh-nine-verdict{position:absolute;right:6px;bottom:6px;max-width:calc(100% - 12px);padding:2px 5px;border-radius:4px;background:rgba(0,0,0,.75);color:#dbe4eb;font-size:11px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}",
      ".mh-nine-cell.keep .mh-nine-verdict{color:#7ee787}",
      ".mh-nine-cell.excluded .mh-nine-verdict{color:#9fb0bd}"
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

  function setScoreValue(value, skipRerun) {
    var el = document.getElementById("mh-min-score");
    if (!el) return;
    var min = parseFloat(el.min);
    var max = parseFloat(el.max);
    var v = Math.max(min, Math.min(max, Number(value)));
    if (!Number.isFinite(v)) return;
    el.value = String(v);
    updateScoreLabel();
    renderScorePresets();
    if (!skipRerun) rerunWithOptions();
  }

  function lowerImagePreset(value) {
    var current = Number(value);
    if (!Number.isFinite(current)) return null;
    var lower = null;
    SCORE_PRESETS.image.forEach(function (v) {
      if (v < current - 0.0001) lower = v;
    });
    return lower;
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
    var n = el ? parseInt(el.value, 10) : DEFAULT_TOP;
    return Number.isFinite(n) ? Math.max(1, Math.min(100, n)) : DEFAULT_TOP;
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
    if (!Number.isFinite(n)) n = DEFAULT_TOP;
    el.value = String(Math.max(1, Math.min(100, n)));
    renderTopPresets();
    rerunWithOptions();
  }

  function regexEnabled() {
    var el = document.getElementById("mh-regex");
    return !!(el && el.checked);
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
    var regex = regexEnabled();
    var scoreRow = document.getElementById("mh-score-row");
    var presets = document.getElementById("mh-regex-presets");
    var ignore = document.getElementById("mh-ignore-wrap");
    var input = document.getElementById("mh-q");
    var sep = document.getElementById("mh-sep-hint");
    if (scoreRow) scoreRow.classList.toggle("mh-hidden", false);
    if (presets) presets.classList.toggle("open", regex);
    if (ignore) ignore.style.display = regex ? "" : "none";
    if (input) {
      input.placeholder = regex
        ? "正则表达式；同时参与语义和关键词匹配"
        : "描述画面或关键词；多个词用；或,分隔";
      input.title = regex
        ? "输入按正则表达式解释，作用于文件名、路径、标签、ID，并提取可读词做语义匹配"
        : "同时匹配 SigLIP2 语义和文件名/路径/标签关键词";
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
    delete next.auto_relaxed;
    if (LAST_SEARCH.stash_id) {
      next.min_score = scoreValue();
    } else {
      next.kind = currentKind();
      next.match = currentMatch();
      next.mode = "hybrid";
      next.fields = ["title", "path", "basename", "tags", "id"];
      next.min_score = scoreValue();
      var regex = regexEnabled();
      if (regex) {
        next.regex = true;
        next.ignore_case = !document.getElementById("mh-ignore-case") ||
          document.getElementById("mh-ignore-case").checked;
      } else {
        delete next.regex;
        delete next.ignore_case;
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
    hideSource();
    var hint = document.getElementById("mh-search-hint");
    if (hint) hint.style.display = "none";
    var regex = regexEnabled();
    var payload = {
      mode: "hybrid",
      text: text,
      top: topValue(),
      kind: currentKind(),
      match: currentMatch(),
      fields: ["title", "path", "basename", "tags", "id"]
    };
    if (regex) {
      payload.regex = true;
      payload.ignore_case = !document.getElementById("mh-ignore-case") ||
        document.getElementById("mh-ignore-case").checked;
    }
    setScoreRange("text");
    payload.min_score = scoreValue();
    document.getElementById("mh-title").textContent =
      regex ? "MineHub 特征搜索（正则）" : "MineHub 特征搜索";
    doSearch(payload);
  }

  function cardCaption(item, payload) {
    var label = item.kind === "scene" ? "场景" : "图片";
    var score = Number(item.score);
    if (payload.regex || payload.mode === "regex" || item.score == null || !Number.isFinite(score)) {
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

  function hideSource() {
    SOURCE_SEQ++;
    var box = document.getElementById("mh-source");
    if (box) box.hidden = true;
    var img = document.getElementById("mh-source-img");
    if (img) img.removeAttribute("src");
    var chips = document.getElementById("mh-source-chips");
    if (chips) chips.textContent = "";
  }

  function showSource(kind, stashId) {
    var box = document.getElementById("mh-source");
    if (!box) return;
    var seq = ++SOURCE_SEQ;
    var img = document.getElementById("mh-source-img");
    var link = document.getElementById("mh-source-link");
    var page = document.getElementById("mh-source-page");
    var name = document.getElementById("mh-source-name");
    var sub = document.getElementById("mh-source-sub");
    var chips = document.getElementById("mh-source-chips");
    var label = kind === "scene" ? "场景" : "图片";
    box.hidden = false;
    if (img) img.removeAttribute("src");
    if (name) name.textContent = "相似于 " + label + " #" + stashId;
    if (sub) sub.textContent = "正在读取原图…";
    if (chips) chips.textContent = "";
    if (page) {
      page.href = (kind === "scene" ? "/scenes/" : "/images/") + stashId;
      page.textContent = "打开" + label + "详情";
    }
    fetch(BASE + "/media/features?kind=" + encodeURIComponent(kind) +
      "&id=" + encodeURIComponent(stashId)).then(function (response) {
      return response.json().then(function (body) {
        if (!response.ok) throw new Error(body.error || ("HTTP " + response.status));
        return body;
      });
    }).then(function (data) {
      if (seq !== SOURCE_SEQ) return;
      var url = relativeMediaUrl(data.image_url || data.thumbnail_url);
      if (img) {
        img.src = url;
        img.alt = data.title || (label + " #" + stashId);
      }
      if (link) link.href = data.page_url || ((kind === "scene" ? "/scenes/" : "/images/") + stashId);
      if (name) {
        name.textContent = "相似于 " + label + " #" + stashId +
          (data.title ? " · " + data.title : "");
      }
      if (sub) sub.textContent = "原图预览 · 相似结果按向量距离排序";
      if (chips) {
        chips.textContent = "";
        (data.semantic || []).slice(0, 3).forEach(function (term) {
          var chip = document.createElement("span");
          chip.className = "mh-source-chip sem";
          chip.textContent = term.label;
          chips.appendChild(chip);
        });
        (data.keywords || []).slice(0, 6).forEach(function (tag) {
          var chip = document.createElement("span");
          chip.className = "mh-source-chip";
          chip.textContent = tag;
          chips.appendChild(chip);
        });
      }
    }).catch(function (error) {
      if (seq !== SOURCE_SEQ) return;
      if (sub) sub.textContent = "读取原图失败：" + error.message;
    });
  }

  function relativeMediaUrl(value) {
    if (!value) return "";
    if (value.indexOf("data:") === 0 || value.indexOf("blob:") === 0) return value;
    try {
      var url = new URL(value, location.origin);
      return url.pathname + url.search;
    } catch (e) {
      return value;
    }
  }

  function previewTitle(kind, id, title) {
    return (kind === "scene" ? "场景" : "图片") + " #" + id + (title ? " · " + title : "");
  }

  function imagePreviewItem(row, item) {
    var paths = (row && row.paths) || {};
    var image = relativeMediaUrl(paths.image) || relativeMediaUrl(item.thumbnail_url);
    if (!image) return null;
    return {
      kind: "image",
      id: String((row && row.id) || item.stash_id),
      title: (row && row.title) || item.title || baseName(item.source_path) || "",
      image: image,
      video: "",
      page_url: item.page_url || ("/images/" + ((row && row.id) || item.stash_id))
    };
  }

  function scenePreviewItem(row, item) {
    var id = String((row && row.id) || (item && item.stash_id) || "");
    if (!id) return null;
    var paths = (row && row.paths) || {};
    var preview = relativeMediaUrl(paths.preview) || ("/scene/" + id + "/preview");
    var stream = relativeMediaUrl(paths.stream) || ("/scene/" + id + "/stream");
    return {
      kind: "scene",
      id: id,
      title: (row && row.title) || (item && item.title) || "",
      image: relativeMediaUrl(paths.screenshot) || (item && item.thumbnail_url) || ("/scene/" + id + "/screenshot"),
      video: preview,
      fallbackVideo: stream,
      page_url: (item && item.page_url) || ("/scenes/" + id)
    };
  }

  function ensureMediaViewer() {
    if (document.getElementById("mh-media-viewer")) return;
    ensureStyle();
    var root = document.createElement("div");
    root.id = "mh-media-viewer";
    root.innerHTML =
      '<button type="button" id="mh-mv-close" title="关闭">×</button>' +
      '<button type="button" id="mh-mv-prev" title="上一个">‹</button>' +
      '<button type="button" id="mh-mv-next" title="下一个">›</button>' +
      '<div id="mh-mv-stage"><img id="mh-mv-img" alt=""><video id="mh-mv-video" controls playsinline preload="metadata"></video></div>' +
      '<div id="mh-mv-caption"><span id="mh-mv-title"></span><span id="mh-mv-count"></span></div>';
    document.body.appendChild(root);
    root.addEventListener("click", function (event) {
      if (event.target === root) closeMediaViewer();
    });
    var stage = document.getElementById("mh-mv-stage");
    stage.addEventListener("click", function (event) {
      if (event.target === stage) closeMediaViewer();
    });
    document.getElementById("mh-mv-close").onclick = closeMediaViewer;
    document.getElementById("mh-mv-prev").onclick = function () { stepMediaViewer(-1); };
    document.getElementById("mh-mv-next").onclick = function () { stepMediaViewer(1); };
    var video = document.getElementById("mh-mv-video");
    video.addEventListener("error", function () {
      var item = MEDIA_VIEW.items[MEDIA_VIEW.index];
      if (!item || !item.fallbackVideo || video.dataset.mhFallback === "1") return;
      video.dataset.mhFallback = "1";
      video.src = item.fallbackVideo;
      video.load();
      var playing = video.play();
      if (playing && playing.catch) playing.catch(function () {});
    });
    document.addEventListener("keydown", function (event) {
      if (!MEDIA_VIEW.open) return;
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        closeMediaViewer();
        return;
      }
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      if (document.activeElement && document.activeElement.tagName === "VIDEO") return;
      event.preventDefault();
      event.stopPropagation();
      stepMediaViewer(event.key === "ArrowLeft" ? -1 : 1);
    }, true);
  }

  function renderMediaViewer() {
    var root = document.getElementById("mh-media-viewer");
    if (!root) return;
    var items = MEDIA_VIEW.items;
    if (!items.length) {
      closeMediaViewer();
      return;
    }
    var index = Math.max(0, Math.min(MEDIA_VIEW.index, items.length - 1));
    MEDIA_VIEW.index = index;
    var item = items[index];
    var img = document.getElementById("mh-mv-img");
    var video = document.getElementById("mh-mv-video");
    var hasVideo = !!(item.video || item.kind === "scene");
    img.style.display = hasVideo ? "none" : "block";
    video.style.display = hasVideo ? "block" : "none";
    if (hasVideo) {
      img.removeAttribute("src");
      delete video.dataset.mhFallback;
      video.pause();
      video.poster = item.image || "";
      video.src = item.video || item.fallbackVideo || "";
      video.load();
      var playing = video.play();
      if (playing && playing.catch) playing.catch(function () {});
    } else {
      video.pause();
      video.removeAttribute("src");
      video.removeAttribute("poster");
      delete video.dataset.mhFallback;
      video.load();
      img.src = item.image;
      img.alt = item.title || "";
    }
    document.getElementById("mh-mv-title").textContent = previewTitle(item.kind, item.id, item.title);
    document.getElementById("mh-mv-count").textContent = (index + 1) + " / " + items.length;
    document.getElementById("mh-mv-prev").disabled = index <= 0;
    document.getElementById("mh-mv-next").disabled = index >= items.length - 1;
  }

  function openMediaViewer(items, index) {
    if (!items || !items.length) return;
    ensureMediaViewer();
    MEDIA_VIEW.items = items.slice();
    MEDIA_VIEW.index = Math.max(0, Math.min(Number(index) || 0, items.length - 1));
    MEDIA_VIEW.open = true;
    document.getElementById("mh-media-viewer").classList.add("open");
    renderMediaViewer();
  }

  function stepMediaViewer(delta) {
    if (!MEDIA_VIEW.open) return;
    var next = MEDIA_VIEW.index + delta;
    if (next < 0 || next >= MEDIA_VIEW.items.length) return;
    MEDIA_VIEW.index = next;
    renderMediaViewer();
  }

  function closeMediaViewer() {
    MEDIA_VIEW.open = false;
    var root = document.getElementById("mh-media-viewer");
    if (root) root.classList.remove("open");
    var video = document.getElementById("mh-mv-video");
    if (video) {
      video.pause();
      video.removeAttribute("src");
      video.removeAttribute("poster");
      video.load();
    }
    var img = document.getElementById("mh-mv-img");
    if (img) img.removeAttribute("src");
  }

  function openSearchPreview(item) {
    var key = item.kind + "|" + String(item.stash_id);
    var entries = [];
    SEARCH_ORDER.forEach(function (itemKey) {
      var candidate = SEARCH_ITEMS[itemKey];
      if (candidate && !SEARCH_DELETED[itemKey]) entries.push(candidate);
    });
    if (!entries.length) {
      window.open(item.page_url, "_blank", "noopener");
      return;
    }
    var imageIds = [];
    var sceneIds = [];
    entries.forEach(function (candidate) {
      if (candidate.kind === "scene") sceneIds.push(String(candidate.stash_id));
      else imageIds.push(String(candidate.stash_id));
    });
    var varDefs = [];
    var fields = [];
    if (imageIds.length) {
      varDefs.push("$imageIds:[ID!]!");
      fields.push("findImages(ids:$imageIds){images{id title paths{image thumbnail preview}}}");
    }
    if (sceneIds.length) {
      varDefs.push("$sceneIds:[ID!]!");
      fields.push("findScenes(ids:$sceneIds){scenes{id title paths{screenshot preview stream}}}");
    }
    var variables = {};
    if (imageIds.length) variables.imageIds = imageIds;
    if (sceneIds.length) variables.sceneIds = sceneIds;
    setStatus("正在打开预览…");
    fetch("/graphql", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        query: "query(" + varDefs.join(",") + "){" + fields.join(" ") + "}",
        variables: variables
      })
    }).then(function (r) {
      return r.json().then(function (body) {
        if (!r.ok || body.errors) throw new Error((body.errors && body.errors[0] && body.errors[0].message) || ("HTTP " + r.status));
        return body;
      });
    }).then(function (body) {
      var data = body.data || {};
      var byKey = Object.create(null);
      ((data.findImages || {}).images || []).forEach(function (row) {
        byKey["image|" + String(row.id)] = row;
      });
      ((data.findScenes || {}).scenes || []).forEach(function (row) {
        byKey["scene|" + String(row.id)] = row;
      });
      var items = [];
      var initialIndex = 0;
      entries.forEach(function (candidate) {
        var candidateKey = candidate.kind + "|" + String(candidate.stash_id);
        var row = byKey[candidateKey];
        var preview = candidate.kind === "scene" ? scenePreviewItem(row, candidate) : imagePreviewItem(row, candidate);
        if (!preview) return;
        if (candidateKey === key) initialIndex = items.length;
        items.push(preview);
      });
      if (!items.length) {
        setStatus("没有可预览的媒体");
        window.open(item.page_url, "_blank", "noopener");
        return;
      }
      openMediaViewer(items, initialIndex);
      setStatus("预览中：← → 切换，Esc 关闭；点击卡片其他区域进入详情页");
    }).catch(function (e) {
      setStatus("打开预览失败：" + e.message);
    });
  }

  function inlineContext() {
    var path = location.pathname.replace(/\/+$/, "");
    if (path !== "/images" && path !== "/scenes") return null;
    var toolbar = document.querySelector(".filtered-list-toolbar");
    if (!toolbar || !toolbar.closest(".item-list-container")) return null;
    var root = toolbar.parentElement;
    if (!root) return null;
    return {
      path: path,
      toolbar: toolbar,
      root: root,
      kind: path === "/images" ? "image" : "scene"
    };
  }

  function inlineMode() {
    return INLINE_MODE_LABELS[INLINE.mode] ? INLINE.mode : "feature";
  }

  function inlineHintText() {
    if (INLINE.regex) return "正则表达式，作用于名称/特征；按 Enter 搜索…";
    return INLINE_MODE_HINTS[inlineMode()];
  }

  function inlineTitleText() {
    return "MineHub " + INLINE_MODE_LABELS[inlineMode()] + (INLINE.regex ? "正则" : "") +
      "搜索；输入后按 Enter 搜索；多个关键词用 ；，、。 或 . \\ 分隔";
  }

  function setInlineMode(mode) {
    if (!INLINE_MODE_LABELS[mode]) return;
    INLINE.mode = mode;
    try { localStorage.setItem("mh_inline_mode", mode); } catch (e) {}
    updateInlineModeBar();
    updateInlineInputHints();
    if (!INLINE.active) return;
    var ctx = inlineContext();
    if (!ctx) return;
    var input = INLINE.input && INLINE.input.isConnected
      ? INLINE.input
      : inlineSearchInput(ctx);
    var text = input ? input.value.trim() : "";
    if (text) runInlineSearch(input, text, ctx.kind);
  }

  function setInlineRegex(enabled) {
    INLINE.regex = !!enabled;
    try { localStorage.setItem("mh_inline_regex", INLINE.regex ? "1" : "0"); } catch (e) {}
    updateInlineModeBar();
    updateInlineInputHints();
    if (!INLINE.active) return;
    var ctx = inlineContext();
    if (!ctx) return;
    var input = INLINE.input && INLINE.input.isConnected
      ? INLINE.input
      : inlineSearchInput(ctx);
    var text = input ? input.value.trim() : "";
    if (text) runInlineSearch(input, text, ctx.kind);
  }

  function setInlineMinScore(value) {
    var score = Number(value);
    var allowed = false;
    for (var i = 0; i < INLINE_SIMILARITY_OPTIONS.length; i++) {
      if (INLINE_SIMILARITY_OPTIONS[i].value === score) {
        allowed = true;
        break;
      }
    }
    if (!allowed) return;
    INLINE.minScore = score;
    try { localStorage.setItem("mh_inline_min_score", String(score)); } catch (e) {}
    updateInlineModeBar();
    if (!INLINE.active) return;
    var ctx = inlineContext();
    if (!ctx) return;
    var input = INLINE.input && INLINE.input.isConnected
      ? INLINE.input
      : inlineSearchInput(ctx);
    var text = input ? input.value.trim() : "";
    if (text) runInlineSearch(input, text, ctx.kind);
  }

  function updateInlineModeBar() {
    var buttons = document.querySelectorAll(".mh-inline-modes [data-mh-mode]");
    for (var i = 0; i < buttons.length; i++) {
      var active = buttons[i].getAttribute("data-mh-mode") === inlineMode();
      buttons[i].classList.toggle("active", active);
      buttons[i].setAttribute("aria-pressed", active ? "true" : "false");
    }
    var regex = document.querySelector(".mh-inline-modes [data-mh-regex]");
    if (regex) {
      regex.classList.toggle("active", INLINE.regex);
      regex.setAttribute("aria-pressed", INLINE.regex ? "true" : "false");
      regex.title = INLINE.regex
        ? "正则已启用：输入按正则表达式解释，作用于名称/特征"
        : "启用正则：把输入当作正则表达式，作用于名称/特征";
    }
    var score = document.querySelector(".mh-inline-score");
    if (score) {
      score.value = String(INLINE.minScore);
      score.style.display = inlineMode() === "feature" ? "" : "none";
    }
  }

  function updateInlineInputHints() {
    var inputs = document.querySelectorAll(
      ".filtered-list-toolbar .search-term-input input, .sidebar-search-container input"
    );
    for (var i = 0; i < inputs.length; i++) {
      inputs[i].placeholder = inlineHintText();
      inputs[i].title = inlineTitleText();
    }
  }

  function inlineSearchInput(ctx) {
    var toolbar = (ctx && ctx.toolbar) || document.querySelector(".filtered-list-toolbar");
    if (!toolbar) return null;
    return toolbar.querySelector(".mh-inline-input") ||
      toolbar.querySelector(".search-term-input input");
  }

  function bindInlineInput(input) {
    if (!input || input.dataset.mhInlineBound) return;
    input.dataset.mhInlineBound = "1";
    input.dataset.mhSemanticBound = "1";
    input.addEventListener("keydown", function (e) {
      if (e.key === "Escape") {
        closeInlineSearch();
        return;
      }
      if (e.key !== "Enter" || e.isComposing || e.keyCode === 229) return;
      var text = e.currentTarget.value.trim();
      var current = location.pathname.replace(/\/+$/, "");
      var targetKind = current === "/images" ? "image" : (current === "/scenes" ? "scene" : "");
      if (!targetKind) return;
      e.preventDefault();
      e.stopPropagation();
      e.stopImmediatePropagation();
      if (!text) {
        closeInlineSearch();
        return;
      }
      runInlineSearch(e.currentTarget, text, targetKind);
    });
    input.addEventListener("input", function (e) {
      if (INLINE.active && !e.currentTarget.value.trim()) closeInlineSearch();
    });
  }

  function installInlineInput(ctx) {
    var wrap = ctx.toolbar.querySelector(".search-term-input");
    if (!wrap) return null;
    var existing = wrap.querySelector(".mh-inline-input");
    if (existing) {
      bindInlineInput(existing);
      return existing;
    }
    var native = wrap.querySelector("input");
    if (native) native.classList.add("mh-native-input-hidden");
    var nativeClear = wrap.querySelector(".clearable-text-field-clear");
    if (nativeClear) nativeClear.classList.add("mh-native-input-hidden");
    var box = document.createElement("div");
    box.className = "mh-inline-input-box";
    box.innerHTML = '<input type="text" class="form-control mh-inline-input" spellcheck="false" autocomplete="off">' +
      '<button type="button" class="mh-inline-clear" title="清空并返回原生列表">×</button>';
    wrap.appendChild(box);
    var input = box.querySelector(".mh-inline-input");
    var clear = box.querySelector(".mh-inline-clear");
    input.placeholder = inlineHintText();
    input.title = inlineTitleText();
    bindInlineInput(input);
    clear.addEventListener("click", function (e) {
      e.preventDefault();
      input.value = "";
      closeInlineSearch();
      input.focus();
    });
    return input;
  }

  function installInlineModeBar(ctx) {
    var toolbar = ctx.toolbar;
    var search = toolbar.querySelector(".search-term-input");
    var bar = toolbar.querySelector(".mh-inline-modes");
    if (!bar) {
      bar = document.createElement("div");
      bar.className = "btn-group mh-inline-modes";
      bar.setAttribute("role", "group");
      bar.setAttribute("aria-label", "MineHub 搜索方式");
      bar.innerHTML = '<button type="button" class="btn btn-secondary" data-mh-mode="name" title="标题或文件名，字面匹配">名称</button>' +
        '<button type="button" class="btn btn-secondary" data-mh-mode="feature" title="同时按画面语义和文件名、路径、标签匹配">特征</button>' +
        '<button type="button" class="btn btn-secondary mh-inline-regex" data-mh-regex="1" title="启用正则：把输入当作正则表达式，作用于名称/特征">.* 正则</button>';
      bar.addEventListener("click", function (e) {
        var regex = e.target.closest("[data-mh-regex]");
        if (regex) {
          e.preventDefault();
          setInlineRegex(!INLINE.regex);
          return;
        }
        var button = e.target.closest("[data-mh-mode]");
        if (!button) return;
        e.preventDefault();
        setInlineMode(button.getAttribute("data-mh-mode"));
      });
    }
    if (search && bar.previousElementSibling !== search) {
      toolbar.insertBefore(bar, search.nextSibling);
    } else if (!bar.parentElement) {
      toolbar.insertBefore(bar, toolbar.firstChild);
    }
    var score = toolbar.querySelector(".mh-inline-score");
    if (!score) {
      score = document.createElement("select");
      score.className = "form-control form-control-sm mh-inline-score";
      score.title = "特征搜索的最低语义相似度；关键词/标签命中仍会保留";
      score.setAttribute("aria-label", "语义相似度筛选");
      var options = "";
      for (var i = 0; i < INLINE_SIMILARITY_OPTIONS.length; i++) {
        var option = INLINE_SIMILARITY_OPTIONS[i];
        options += '<option value="' + option.value + '">' + option.label + "</option>";
      }
      score.innerHTML = options;
      score.addEventListener("change", function (e) {
        setInlineMinScore(e.target.value);
      });
    }
    if (score.previousElementSibling !== bar) {
      toolbar.insertBefore(score, bar.nextSibling);
    }
    INLINE.modeBar = bar;
    INLINE.scoreBar = score;
    updateInlineModeBar();
  }

  function useInlineRefresh() {
    var React = window.PluginApi && window.PluginApi.React;
    var pair = React.useState(0);
    var force = pair[1];
    var renderRevision = INLINE.revision;
    var seenRevision = React.useRef(renderRevision);
    seenRevision.current = renderRevision;
    React.useEffect(function () {
      var listener = function () {
        force(function (value) { return value + 1; });
      };
      INLINE.listeners.push(listener);
      if (seenRevision.current !== INLINE.revision) listener();
      return function () {
        var index = INLINE.listeners.indexOf(listener);
        if (index >= 0) INLINE.listeners.splice(index, 1);
      };
    }, [force]);
  }

  function notifyInline() {
    INLINE.revision++;
    var listeners = INLINE.listeners.slice();
    for (var i = 0; i < listeners.length; i++) {
      try { listeners[i](); } catch (e) {}
    }
  }

  function inlineNativeCount() {
    return INLINE.kind === "scene" ? INLINE.nativeScenes.length : INLINE.nativeImages.length;
  }

  function inlineListMetadata() {
    if (INLINE.searching) return "搜索中…";
    if (INLINE.error) return INLINE.error;
    var mode = inlineMode();
    var suffix = mode === "feature"
      ? " · " + (INLINE.regex ? "语义+正则关键词" : "语义+关键词") +
        " · 语义 ≥ " + INLINE.minScore.toFixed(3)
      : (INLINE.regex ? " · 标题/文件名正则" : " · 标题/文件名匹配");
    var loaded = inlineNativeCount();
    var progress = INLINE.loadingMore ? " · 正在加载更多…"
      : (INLINE.moreError ? " · " + INLINE.moreError + "，继续下滑重试"
        : (INLINE.hasMore ? " · 已加载 " + loaded + " 项 · 向下滑动加载更多"
          : " · 已全部加载 " + loaded + " 项"));
    return "MineHub · " + INLINE_MODE_LABELS[mode] + " · “" +
      INLINE.query + "”" + suffix + progress;
  }

  function callWithProps(thisArg, argsObject, props) {
    var args = Array.prototype.slice.call(argsObject);
    var next = args.pop();
    if (props) args[0] = Object.assign({}, args[0] || {}, props);
    return next.apply(thisArg, args);
  }

  function captureNativeSelection(kind, props) {
    if (!props || props.selectedIds == null) return;
    var raw = props.selectedIds;
    var values = raw instanceof Set ? Array.from(raw)
      : Array.isArray(raw) ? raw
      : Object.keys(raw || {});
    NATIVE_SELECTION[kind] = new Set(values.map(function (v) { return String(v); }));
  }

  function installNativeListPatches() {
    if (INLINE.patchInstalled) return;
    var api = window.PluginApi;
    if (!api || !api.patch || !api.React) return;
    function imageProps() {
      return {
        images: INLINE.nativeImages,
        selectedIds: INLINE.emptySet,
        onSelectChange: INLINE.noop,
        pageCount: 1,
        totalCount: INLINE.nativeImages.length
      };
    }
    function sceneProps() {
      return {
        scenes: INLINE.nativeScenes,
        selectedIds: INLINE.emptySet,
        onSelectChange: INLINE.noop
      };
    }
    api.patch.before("ImageList", function () {
      var args = Array.prototype.slice.call(arguments);
      captureNativeSelection("image", args[0]);
      if (INLINE.active && INLINE.kind === "image") {
        args[0] = Object.assign({}, args[0] || {}, imageProps());
      }
      return args;
    });
    api.patch.before("SceneList", function () {
      var args = Array.prototype.slice.call(arguments);
      captureNativeSelection("scene", args[0]);
      if (INLINE.active && INLINE.kind === "scene") {
        args[0] = Object.assign({}, args[0] || {}, sceneProps());
      }
      return args;
    });
    api.patch.instead("FilteredImageList", function () {
      useInlineRefresh();
      return callWithProps(this, arguments, null);
    });
    api.patch.instead("FilteredSceneList", function () {
      useInlineRefresh();
      return callWithProps(this, arguments, null);
    });
    api.patch.instead("PaginationIndex", function () {
      useInlineRefresh();
      if (INLINE.active) {
        var total = inlineNativeCount();
        return callWithProps(this, arguments, {
          itemsPerPage: Math.max(1, total),
          currentPage: 1,
          totalItems: total,
          metadataByline: inlineListMetadata()
        });
      }
      return callWithProps(this, arguments, null);
    });
    INLINE.patchInstalled = true;
  }

  function normalizePaths(paths) {
    var out = {};
    Object.keys(paths || {}).forEach(function (key) {
      out[key] = relativeMediaUrl(paths[key]);
    });
    return out;
  }

  function normalizeFile(file) {
    var out = Object.assign({}, file);
    out.path = relativeMediaUrl(out.path);
    out.fingerprints = out.fingerprints || [];
    return out;
  }

  function normalizeStudio(studio) {
    if (!studio) return null;
    return Object.assign({}, studio, { image_path: relativeMediaUrl(studio.image_path) });
  }

  function normalizePerformers(performers) {
    return (performers || []).map(function (performer) {
      return Object.assign({}, performer, { image_path: relativeMediaUrl(performer.image_path) });
    });
  }

  function fallbackNativeImage(item) {
    var src = relativeMediaUrl(item.thumbnail_url);
    return {
      id: String(item.stash_id),
      title: item.title || baseName(item.source_path) || "",
      code: "",
      date: null,
      urls: [],
      details: item.tags || null,
      photographer: null,
      rating100: null,
      organized: false,
      o_counter: 0,
      paths: { thumbnail: src, preview: "", image: src },
      galleries: [],
      studio: null,
      tags: [],
      performers: [],
      visual_files: [{
        __typename: "ImageFile",
        id: String(item.stash_id),
        path: item.source_path || "",
        size: 0,
        mod_time: "",
        width: 320,
        height: 200,
        fingerprints: []
      }]
    };
  }

  function nativeImageFromRow(row, item) {
    if (!row) return fallbackNativeImage(item);
    var paths = normalizePaths(row.paths || {});
    var thumb = paths.thumbnail || relativeMediaUrl(item.thumbnail_url);
    paths.thumbnail = thumb;
    paths.image = paths.image || thumb;
    var files = (row.visual_files || []).map(normalizeFile);
    if (!files.length) {
      files = [{
        __typename: "ImageFile",
        id: String(row.id),
        path: item.source_path || "",
        size: 0,
        mod_time: "",
        width: 320,
        height: 200,
        fingerprints: []
      }];
    }
    return Object.assign({}, row, {
      id: String(row.id),
      title: row.title || item.title || baseName(item.source_path) || "",
      paths: paths,
      galleries: row.galleries || [],
      studio: normalizeStudio(row.studio),
      tags: row.tags || [],
      performers: normalizePerformers(row.performers),
      visual_files: files
    });
  }

  function hydrateNativeImages(rows) {
    var images = rows.filter(function (item) { return item.kind === "image"; });
    if (!images.length) return Promise.resolve([]);
    var ids = images.map(function (item) { return String(item.stash_id); });
    var query = "query($ids:[ID!]!){findImages(ids:$ids){images{id title code date urls details photographer rating100 organized o_counter paths{thumbnail preview image} galleries{id title} studio{id name image_path} tags{id name} performers{id name gender favorite image_path} visual_files{__typename ... on BaseFile{id path size mod_time fingerprints{type value}} ... on ImageFile{width height} ... on VideoFile{width height duration video_codec audio_codec}}}}}";
    return fetch("/graphql", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ query: query, variables: { ids: ids } })
    }).then(function (response) {
      return response.json().then(function (body) {
        if (!response.ok || body.errors) {
          throw new Error((body.errors && body.errors[0] && body.errors[0].message) ||
            ("HTTP " + response.status));
        }
        return body;
      });
    }).then(function (body) {
      var rowsById = Object.create(null);
      (((body.data || {}).findImages || {}).images || []).forEach(function (row) {
        rowsById[String(row.id)] = row;
      });
      return images.map(function (item) {
        return nativeImageFromRow(rowsById[String(item.stash_id)], item);
      });
    }).catch(function () {
      return images.map(fallbackNativeImage);
    });
  }

  function fallbackNativeScene(item) {
    var shot = relativeMediaUrl(item.thumbnail_url);
    return {
      id: String(item.stash_id),
      title: item.title || baseName(item.source_path) || "",
      code: "",
      details: item.tags || "",
      director: "",
      urls: [],
      date: null,
      production_date: null,
      rating100: null,
      o_counter: 0,
      organized: false,
      interactive: false,
      interactive_speed: null,
      resume_time: null,
      play_duration: null,
      play_count: null,
      files: [],
      paths: {
        screenshot: shot, preview: "", stream: "", webp: "", vtt: "", sprite: "",
        funscript: "", interactive_heatmap: "", caption: ""
      },
      scene_markers: [],
      galleries: [],
      studio: null,
      groups: [],
      tags: [],
      performers: [],
      stash_ids: []
    };
  }

  function nativeSceneFromRow(row, item) {
    if (!row) return fallbackNativeScene(item);
    var paths = normalizePaths(row.paths || {});
    paths.screenshot = paths.screenshot || relativeMediaUrl(item.thumbnail_url);
    var groups = (row.groups || []).map(function (entry) {
      var group = Object.assign({}, entry.group || {});
      group.front_image_path = relativeMediaUrl(group.front_image_path);
      return Object.assign({}, entry, { group: group });
    });
    return Object.assign({}, row, {
      id: String(row.id),
      title: row.title || item.title || baseName(item.source_path) || "",
      files: (row.files || []).map(normalizeFile),
      paths: paths,
      scene_markers: row.scene_markers || [],
      galleries: row.galleries || [],
      studio: normalizeStudio(row.studio),
      groups: groups,
      tags: row.tags || [],
      performers: normalizePerformers(row.performers),
      stash_ids: row.stash_ids || []
    });
  }

  function hydrateNativeScenes(rows) {
    var scenes = rows.filter(function (item) { return item.kind === "scene"; });
    if (!scenes.length) return Promise.resolve([]);
    var ids = scenes.map(function (item) { return String(item.stash_id); });
    var query = "query($ids:[ID!]!){findScenes(ids:$ids){scenes{id title code details director urls date production_date rating100 o_counter organized interactive interactive_speed resume_time play_duration play_count files{__typename ... on BaseFile{id path size mod_time fingerprints{type value}} ... on VideoFile{width height duration video_codec audio_codec}} paths{screenshot preview stream webp vtt sprite funscript interactive_heatmap caption} scene_markers{id title seconds primary_tag{id name}} galleries{id title} studio{id name image_path} groups{group{id name front_image_path} scene_index} tags{id name} performers{id name disambiguation gender favorite image_path} stash_ids{endpoint stash_id updated_at}}}}";
    return fetch("/graphql", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ query: query, variables: { ids: ids } })
    }).then(function (response) {
      return response.json().then(function (body) {
        if (!response.ok || body.errors) {
          throw new Error((body.errors && body.errors[0] && body.errors[0].message) ||
            ("HTTP " + response.status));
        }
        return body;
      });
    }).then(function (body) {
      var rowsById = Object.create(null);
      (((body.data || {}).findScenes || {}).scenes || []).forEach(function (row) {
        rowsById[String(row.id)] = row;
      });
      return scenes.map(function (item) {
        return nativeSceneFromRow(rowsById[String(item.stash_id)], item);
      });
    }).catch(function () {
      return scenes.map(fallbackNativeScene);
    });
  }

  function closeInlineSearch() {
    INLINE.seq++;
    if (INLINE.controller) {
      INLINE.controller.abort();
      INLINE.controller = null;
    }
    if (INLINE.moreController) {
      INLINE.moreController.abort();
      INLINE.moreController = null;
    }
    INLINE.input = null;
    INLINE.path = "";
    INLINE.kind = "";
    INLINE.query = "";
    INLINE.active = false;
    INLINE.searching = false;
    INLINE.error = "";
    INLINE.nativeImages = [];
    INLINE.nativeScenes = [];
    INLINE.offset = 0;
    INLINE.hasMore = false;
    INLINE.loadingMore = false;
    INLINE.moreError = "";
    INLINE.seen = Object.create(null);
    document.body.classList.remove("mh-native-search-active");
    notifyInline();
  }

  function inlinePayload(text, kind, mode, offset) {
    var payload = {
      text: text, top: INLINE.pageSize, offset: offset || 0, kind: kind, match: "all"
    };
    if (mode === "feature") {
      payload.mode = "hybrid";
      payload.min_score = INLINE.minScore;
      payload.fields = INLINE_ALL_FIELDS.slice();
      if (INLINE.regex) {
        payload.regex = true;
        payload.ignore_case = true;
      }
    } else if (INLINE.regex) {
      payload.mode = "regex";
      payload.ignore_case = true;
      payload.fields = ["title", "basename"];
    } else {
      payload.mode = "literal";
      payload.ignore_case = true;
      payload.fields = ["title", "basename"];
    }
    return payload;
  }

  function loadInlinePage(seq, controller, mode, append) {
    var timer = setTimeout(function () { controller.abort(); }, 30000);
    fetch(BASE + "/search", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(inlinePayload(INLINE.query, INLINE.kind, mode, INLINE.offset)),
      signal: controller.signal
    }).then(function (r) {
      return r.json().then(function (j) {
        if (!r.ok) throw new Error(j.error || ("HTTP " + r.status));
        return j;
      });
    }).then(function (j) {
      clearTimeout(timer);
      if (seq !== INLINE.seq || !INLINE.active) return;
      var raw = j.results || [];
      INLINE.offset += raw.length;
      INLINE.hasMore = raw.length >= INLINE.pageSize;
      var rows = [];
      for (var i = 0; i < raw.length; i++) {
        var item = raw[i];
        if (item.kind !== INLINE.kind) continue;
        var key = item.kind + "|" + String(item.stash_id);
        if (SEARCH_DELETED[key] || INLINE.seen[key]) continue;
        INLINE.seen[key] = true;
        rows.push(item);
      }
      if (!rows.length) {
        if (append) INLINE.loadingMore = false;
        else INLINE.searching = false;
        notifyInline();
        return;
      }
      var hydrate = INLINE.kind === "scene" ? hydrateNativeScenes : hydrateNativeImages;
      return hydrate(rows).then(function (nativeRows) {
        if (seq !== INLINE.seq || !INLINE.active) return;
        if (INLINE.kind === "scene") {
          INLINE.nativeScenes = INLINE.nativeScenes.concat(nativeRows);
        } else {
          INLINE.nativeImages = INLINE.nativeImages.concat(nativeRows);
        }
        if (append) {
          INLINE.loadingMore = false;
          INLINE.moreError = "";
          if (INLINE.moreController === controller) INLINE.moreController = null;
        } else {
          INLINE.searching = false;
          if (INLINE.controller === controller) INLINE.controller = null;
        }
        notifyInline();
      });
    }).catch(function (e) {
      clearTimeout(timer);
      if (seq !== INLINE.seq || !INLINE.active) return;
      if (append) {
        INLINE.loadingMore = false;
        INLINE.moreError = "加载更多失败：" + e.message;
        if (INLINE.moreController === controller) INLINE.moreController = null;
      } else {
        INLINE.searching = false;
        INLINE.error = "搜索失败：" + e.message;
        if (INLINE.controller === controller) INLINE.controller = null;
      }
      notifyInline();
    });
  }

  function runInlineSearch(input, text, kind) {
    var ctx = inlineContext();
    if (!ctx) return;
    var mode = inlineMode();
    if (INLINE.controller) INLINE.controller.abort();
    if (INLINE.moreController) INLINE.moreController.abort();
    INLINE.input = input;
    INLINE.path = ctx.path;
    INLINE.kind = kind || ctx.kind;
    INLINE.query = text;
    INLINE.active = true;
    INLINE.searching = true;
    INLINE.error = "";
    INLINE.offset = 0;
    INLINE.hasMore = false;
    INLINE.loadingMore = false;
    INLINE.moreError = "";
    INLINE.seen = Object.create(null);
    INLINE.nativeImages = [];
    INLINE.nativeScenes = [];
    document.body.classList.add("mh-native-search-active");
    ensureInlineScroll();
    notifyInline();
    var controller = new AbortController();
    INLINE.controller = controller;
    var seq = ++INLINE.seq;
    loadInlinePage(seq, controller, mode, false);
  }

  function inlineScrollElement(target) {
    if (!target || target === window || target === document) {
      return document.scrollingElement || document.documentElement;
    }
    if (target.nodeType === 9) return document.scrollingElement || document.documentElement;
    return target;
  }

  function inlineNearBottom(target) {
    var el = inlineScrollElement(target);
    if (!el) return false;
    if (el === document.scrollingElement || el === document.documentElement || el === document.body) {
      return window.innerHeight + window.pageYOffset >= el.scrollHeight - 800;
    }
    return el.scrollTop + el.clientHeight >= el.scrollHeight - 800;
  }

  function inlineLoadMore() {
    if (!INLINE.active || INLINE.searching || INLINE.loadingMore || !INLINE.hasMore) return;
    var ctx = inlineContext();
    if (!ctx || ctx.kind !== INLINE.kind) return;
    if (INLINE.moreController) INLINE.moreController.abort();
    var controller = new AbortController();
    INLINE.moreController = controller;
    INLINE.loadingMore = true;
    INLINE.moreError = "";
    notifyInline();
    loadInlinePage(INLINE.seq, controller, inlineMode(), true);
  }

  function onInlineScroll(event) {
    if (!INLINE.active || INLINE.searching || INLINE.loadingMore || !INLINE.hasMore) return;
    if (!inlineNearBottom(event.target)) return;
    inlineLoadMore();
  }

  function ensureInlineScroll() {
    if (INLINE.scrollBound) return;
    INLINE.scrollBound = true;
    window.addEventListener("scroll", onInlineScroll, { passive: true, capture: true });
  }

  function doSearch(payload) {
    LAST_SEARCH = payload;
    if (busy) { QUEUED_SEARCH = payload; return; }
    busy = true;
    SEARCH_ITEMS = Object.create(null);
    SEARCH_ORDER = [];
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
      if (payload.stash_id && !rows.length && !payload.auto_relaxed) {
        var currentScore = Number(payload.min_score);
        var lower = lowerImagePreset(currentScore);
        if (lower !== null) {
          setScoreRange("image");
          setScoreValue(lower, true);
          var relaxed = Object.assign({}, payload, { min_score: lower, auto_relaxed: true });
          setStatus("相似度 ≥ " + currentScore.toFixed(3) + " 没有结果，已自动降至 ≥ " +
            lower.toFixed(3) + " 重试…");
          LAST_SEARCH = relaxed;
          QUEUED_SEARCH = relaxed;
          return;
        }
      }
      var cutoff = Number(payload.min_score);
      var isRegex = !!payload.regex || payload.mode === "regex";
      var cutoffText = isRegex ? " · 特征+正则" :
        (payload.mode === "hybrid" ? " · 特征" :
          (Number.isFinite(cutoff) ? " · 相似度 ≥ " + cutoff.toFixed(3) : ""));
      var kindText = payload.kind === "image" ? " · 仅图片" :
        (payload.kind === "scene" ? " · 仅场景" : "");
      var relaxText = payload.auto_relaxed ? " · 已自动降档" : "";
      setStatus(rows.length ? ("共 " + rows.length + " 个结果" + cutoffText + kindText + relaxText) :
        ("没有找到结果" + cutoffText + kindText + relaxText));
      rows.forEach(function (x) {
        var key = x.kind + "|" + x.stash_id;
        SEARCH_ITEMS[key] = x;
        SEARCH_ORDER.push(key);
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
        preview.title = x.kind === "scene" ? "预览视频" : "预览图片";
        preview.setAttribute("aria-label", preview.title);
        preview.onclick = function (ev) {
          ev.preventDefault();
          ev.stopPropagation();
          openSearchPreview(x);
        };
        preview.innerHTML = x.kind === "scene" ? WALL_PLAY_SVG : WALL_PREVIEW_SVG;
        card.appendChild(preview);
        if (x.kind === "image") {
          var sim = document.createElement("button");
          sim.type = "button";
          sim.className = "mh-card-sim";
          sim.title = "查找相似图片";
          sim.setAttribute("aria-label", "查找相似图片");
          sim.innerHTML = SIMILAR_SVG;
          sim.onclick = function (ev) {
            ev.preventDefault();
            ev.stopPropagation();
            openSearch({ id: x.stash_id, kind: x.kind });
          };
          card.appendChild(sim);
        }
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
      '<label class="mh-pm-check"><input id="mh-pm-groups" type="checkbox">仅群聊内容</label>' +
      '<input id="mh-pm-chatsearch" placeholder="搜索好友 / 群…">' +
      '<label class="mh-pm-check"><input id="mh-pm-unknown" type="checkbox">显示无归属文件</label>' +
      '<label class="mh-pm-check"><input id="mh-pm-mapped" type="checkbox">仅显示有归属</label>' +
      '</div><div id="mh-pm-chats"></div>' +
      '</aside>' +
      '<main id="mh-pm-main">' +
      '<div id="mh-pm-tools">' +
      '<button id="mh-pm-all">全选本页</button><button id="mh-pm-none">清空选择</button>' +
      '<button id="mh-pm-move" class="blue">移动到…</button><button id="mh-pm-library" class="blue">移到 library</button>' +
      '<button id="mh-pm-dupe-open" class="gray">查重 QQ</button><button id="mh-pm-del" class="red">移入回收站</button>' +
      '<button id="mh-pm-open">系统打开</button>' +
      '<span class="mh-pm-count"></span>' +
      '</div><div id="mh-pm-grid"><div class="mh-pm-empty">选择目录后点击「扫描」。</div></div>' +
      '<div id="mh-pm-pager"><button id="mh-pm-prev">上一页</button><span id="mh-pm-pageinfo">-</span><button id="mh-pm-next">下一页</button></div>' +
      '</main></div></div>' +
      '<div id="mh-pm-preview"><div id="mh-pm-preview-box"><img id="mh-pm-preview-img" alt="">' +
      '<div id="mh-pm-preview-meta"></div><div id="mh-pm-preview-actions">' +
      '<button id="mh-pm-preview-open">系统打开</button><button id="mh-pm-preview-close">关闭</button>' +
      '</div></div></div>' +
      '<div id="mh-pm-dupe"><div id="mh-pm-dupe-box">' +
      '<div id="mh-pm-dupe-head"><strong>QQ 重复检测</strong><span id="mh-pm-dupe-status"></span><button id="mh-pm-dupe-x">×</button></div>' +
      '<div id="mh-pm-dupe-tools"><button id="mh-pm-dupe-scan" class="blue">扫描并计算</button>' +
      '<button id="mh-pm-dupe-select" class="green">选中所有重复项</button>' +
      '<button id="mh-pm-dupe-recycle" class="red">移入回收站</button>' +
      '<button id="mh-pm-dupe-library" class="blue">移到 library</button>' +
      '<button id="mh-pm-dupe-close">关闭</button></div>' +
      '<div id="mh-pm-dupe-note" class="small text-muted"></div>' +
      '<div id="mh-pm-dupe-results"></div>' +
      '</div></div>';
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
    document.getElementById("mh-pm-library").onclick = pmLibrary;
    document.getElementById("mh-pm-dupe-open").onclick = pmDupeOpen;
    document.getElementById("mh-pm-del").onclick = pmRecycle;
    document.getElementById("mh-pm-open").onclick = pmOpenSelected;
    document.getElementById("mh-pm-dupe-x").onclick = pmDupeClose;
    document.getElementById("mh-pm-dupe-close").onclick = pmDupeClose;
    document.getElementById("mh-pm-dupe-scan").onclick = pmDupeScan;
    document.getElementById("mh-pm-dupe-select").onclick = pmDupeSelectAll;
    document.getElementById("mh-pm-dupe-recycle").onclick = function () { pmDupeClose(); pmRecycle(); };
    document.getElementById("mh-pm-dupe-library").onclick = function () { pmDupeClose(); pmLibrary(); };
    document.getElementById("mh-pm-dupe").addEventListener("click", function (e) {
      if (e.target.id === "mh-pm-dupe") pmDupeClose();
    });
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
      "mh-pm-groups", "mh-pm-unknown", "mh-pm-mapped"];
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
    document.getElementById("mh-pm-groups").addEventListener("change", pmRenderChats);
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
    var groupsOnly = document.getElementById("mh-pm-groups");
    host.textContent = "";
    PM.chats.forEach(function (c) {
      if (groupsOnly && groupsOnly.checked && c.kind !== "group") return;
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
      only_groups: !!document.getElementById("mh-pm-groups").checked,
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

  function pmLibrary() {
    var paths = Object.keys(PM.selected).filter(function (k) { return k.indexOf("chat:") !== 0; });
    if (!paths.length) { pmSetStatus("请先选择文件"); return; }
    if (!confirm("将 " + paths.length + " 个文件按分类/月份移入 MineHub library？")) return;
    pmSetStatus("正在移入 library…");
    pmFetch("/pm/library", { paths: paths }).then(function (j) {
      PM.selected = Object.create(null);
      var msg = "已移入 library " + (j.moved || []).length + " 个文件";
      if (j.scan_job) msg += "；Stash 扫描任务 " + j.scan_job;
      if (j.errors && j.errors.length) msg += "；失败 " + j.errors.length + " 个：" + j.errors.slice(0, 3).join("；");
      pmSetStatus(msg);
      pmQuery();
    }).catch(function (e) { pmSetStatus("移入 library 失败：" + e.message); });
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

  function pmDupeStatus(text) {
    var el = document.getElementById("mh-pm-dupe-status");
    if (el) el.textContent = text || "";
    var note = document.getElementById("mh-pm-dupe-note");
    if (note) note.textContent = document.getElementById("mh-pm-groups").checked
      ? "当前只统计群聊内容中的重复项；每组保留第一张，其余加入选择。" : "当前统计全部 QQ 图片缓存；每组保留第一张，其余加入选择。";
  }

  function pmDupeOpen() {
    var box = document.getElementById("mh-pm-dupe");
    if (!box) return;
    box.classList.add("open");
    pmDupeStatus("读取 QQ 查重状态…");
    pmFetch("/dupes/status?scope=qq").then(function (s) {
      if (s.job && s.job.status === "running") {
        pmDupePoll();
      } else if (s.hashed) {
        pmDupeLoad();
      } else {
        pmDupeStatus("尚未计算 QQ 哈希；点击「扫描并计算」");
      }
    }).catch(function (e) { pmDupeStatus("读取状态失败：" + e.message); });
  }

  function pmDupeClose() {
    if (PM.dupePoll) clearTimeout(PM.dupePoll);
    PM.dupePoll = null;
    var box = document.getElementById("mh-pm-dupe");
    if (box) box.classList.remove("open");
  }

  function pmDupeScan() {
    if (PM.dupePoll) clearTimeout(PM.dupePoll);
    PM.dupePoll = null;
    pmDupeStatus("QQ 哈希扫描启动…");
    pmFetch("/dupes/scan", {
      scope: "qq", algo: "phash", threshold: 10,
      only_groups: !!document.getElementById("mh-pm-groups").checked
    }).then(function (job) {
      if (job && job.status === "error") throw new Error(job.error || "扫描失败");
      pmDupePoll();
    }).catch(function (e) { pmDupeStatus("启动失败：" + e.message); });
  }

  function pmDupePoll() {
    pmFetch("/dupes/status?scope=qq").then(function (s) {
      var job = s.job || {};
      if (job.status === "running") {
        pmDupeStatus("扫描哈希：" + (job.done || 0) + " / " + (job.total || 0) + " · 已存 " + (s.hashed || 0));
        PM.dupePoll = setTimeout(pmDupePoll, 1500);
        return;
      }
      if (job.status === "error") {
        pmDupeStatus("扫描失败：" + (job.error || "未知错误"));
        return;
      }
      pmDupeStatus("哈希完成：" + (s.hashed || 0) + " 张，错误 " + (s.errors || 0) + "；正在分组…");
      pmDupeLoad();
    }).catch(function (e) {
      pmDupeStatus("查询扫描状态失败：" + e.message);
      PM.dupePoll = setTimeout(pmDupePoll, 2000);
    });
  }

  function pmDupeLoad() {
    pmDupeStatus("正在分组…");
    pmFetch("/dupes/groups", {
      scope: "qq", algo: "phash", threshold: 10,
      limit: document.getElementById("mh-pm-groups").checked ? 0 : 100,
      only_groups: !!document.getElementById("mh-pm-groups").checked
    }).then(function (data) {
      PM.dupeGroups = data.groups || [];
      pmDupeRender(data);
    }).catch(function (e) { pmDupeStatus("分组失败：" + e.message); });
  }

  function pmDupeRender(data) {
    var host = document.getElementById("mh-pm-dupe-results");
    if (!host) return;
    host.textContent = "";
    PM.dupeGroups = data.groups || [];
    PM.dupeTotal = data.total_groups || PM.dupeGroups.length;
    var selectAll = document.getElementById("mh-pm-dupe-select");
    if (selectAll) selectAll.textContent = PM.dupeTotal > PM.dupeGroups.length
      ? "选中已显示重复项" : "选中所有重复项";
    if (!PM.dupeGroups.length) {
      var empty = document.createElement("div");
      empty.className = "mh-pm-empty";
      empty.textContent = "没有找到重复项";
      host.appendChild(empty);
      pmDupeStatus("共 0 组 / 0 个文件");
      return;
    }
    PM.dupeGroups.forEach(function (group, index) {
      var wrap = document.createElement("div");
      wrap.className = "mh-pm-dupe-group";
      var head = document.createElement("div");
      head.className = "mh-pm-dupe-group-head";
      var title = document.createElement("strong");
      title.textContent = "第 " + (index + 1) + " 组";
      var info = document.createElement("span");
      info.textContent = group.count + " 个 · " + fmtSize(group.total_size);
      var pick = document.createElement("button");
      pick.type = "button";
      pick.textContent = "选中重复项（保留第一张）";
      pick.onclick = function () { pmDupeSelectGroup(index); };
      head.appendChild(title);
      head.appendChild(info);
      head.appendChild(pick);
      wrap.appendChild(head);
      var members = document.createElement("div");
      members.className = "mh-pm-dupe-members";
      var all = [group.representative].concat(group.members || []);
      all.forEach(function (member, mi) {
        var card = document.createElement("div");
        card.className = "mh-pm-dupe-member";
        var img = document.createElement("img");
        img.loading = "lazy";
        img.decoding = "async";
        img.alt = "";
        img.src = pmThumb(member.path, 240);
        var name = document.createElement("strong");
        name.textContent = mi === 0 ? "保留 · " + (member.name || "") : (member.name || "");
        var sub = document.createElement("span");
        sub.textContent = fmtSize(member.size) + (member.distance != null ? " · d" + member.distance : "");
        card.appendChild(img);
        card.appendChild(name);
        card.appendChild(sub);
        members.appendChild(card);
      });
      wrap.appendChild(members);
      host.appendChild(wrap);
    });
    pmDupeStatus("找到 " + data.total_groups + " 组 / " + data.total_files + " 个文件");
  }

  function pmDupeSelectGroup(index) {
    var group = PM.dupeGroups[index];
    if (!group) return;
    (group.members || []).forEach(function (member) {
      if (member.path) PM.selected[member.path] = true;
    });
    pmRenderGrid();
    pmRenderSelection();
    pmDupeStatus("已选择第 " + (index + 1) + " 组的重复项（保留第一张）");
  }

  function pmDupeSelectAll() {
    var count = 0;
    PM.dupeGroups.forEach(function (group) {
      (group.members || []).forEach(function (member) {
        if (member.path) { PM.selected[member.path] = true; count++; }
      });
    });
    pmRenderGrid();
    pmRenderSelection();
    pmDupeStatus("已选择 " + count + " 个重复项" +
      (PM.dupeTotal > PM.dupeGroups.length ? "（已显示范围）" : "（全部）") +
      "（每组保留第一张）");
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

  // ---------- folder browser ----------
  function folderSetStatus(text) {
    var el = document.getElementById("mh-folder-status");
    if (el) el.textContent = text || "";
  }

  function folderInit() {
    if (FOLDER.initialized) return;
    FOLDER.initialized = true;
    var input = document.getElementById("mh-folder-path");
    if (!input || !input.value.trim()) {
      if (input) input.value = FOLDER.path;
    }
    folderBindDrag();
    folderLoad();
  }

  function folderThumb(rec, size) {
    return BASE + "/folder/thumb?size=" + encodeURIComponent(size || 320) +
      "&path=" + encodeURIComponent(rec.path);
  }

  function folderLoad() {
    var input = document.getElementById("mh-folder-path");
    var path = input ? input.value.trim() : "";
    if (!path) { folderSetStatus("请输入文件夹路径"); return; }
    folderCancelDrag();
    FOLDER.anchor = -1;
    FOLDER.suppressClick = false;
    var recursive = document.getElementById("mh-folder-recursive");
    var kind = document.getElementById("mh-folder-kind");
    var seq = ++FOLDER.seq;
    FOLDER.loading = true;
    folderSetStatus("读取中…");
    fetch(BASE + "/folder/list", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        path: path,
        recursive: !recursive || recursive.checked,
        kind: kind ? kind.value : "all",
        page: FOLDER.page,
        per_page: 120
      })
    }).then(function (r) {
      return r.json().then(function (j) {
        if (!r.ok) throw new Error(j.error || ("HTTP " + r.status));
        return j;
      });
    }).then(function (j) {
      if (seq !== FOLDER.seq) return;
      FOLDER.path = j.path;
      FOLDER.records = j.files || [];
      FOLDER.page = j.page || 1;
      FOLDER.pages = j.pages || 1;
      FOLDER.total = j.total || 0;
      FOLDER.loading = false;
      folderRender();
      folderSetStatus("共 " + FOLDER.total + " 个媒体 · 第 " + FOLDER.page + " / " + FOLDER.pages + " 页");
    }).catch(function (e) {
      if (seq !== FOLDER.seq) return;
      FOLDER.loading = false;
      folderSetStatus("读取失败：" + e.message);
    });
  }

  function folderRender() {
    var grid = document.getElementById("mh-folder-grid");
    if (!grid) return;
    grid.textContent = "";
    if (!FOLDER.records.length) {
      var empty = document.createElement("div");
      empty.className = "mh-folder-empty";
      empty.textContent = "文件夹里没有可显示的图片或视频";
      grid.appendChild(empty);
      folderRenderSelection();
      folderRenderPager();
      return;
    }
    FOLDER.records.forEach(function (rec) {
      var card = document.createElement("div");
      card.className = "mh-folder-card" + (FOLDER.selected[rec.path] ? " sel" : "");
      card.title = rec.path;
      card.__mhRec = rec;
      var chk = document.createElement("input");
      chk.type = "checkbox";
      chk.className = "mh-folder-chk";
      chk.checked = !!FOLDER.selected[rec.path];
      chk.addEventListener("click", function (e) { e.stopPropagation(); });
      chk.addEventListener("change", function () {
        folderToggle(rec, chk.checked);
        FOLDER.anchor = FOLDER.records.indexOf(rec);
        folderSyncCards();
      });
      card.appendChild(chk);
      if (rec.kind === "image") {
        var img = document.createElement("img");
        img.loading = "lazy";
        img.decoding = "async";
        img.alt = "";
        img.draggable = false;
        img.src = folderThumb(rec, 320);
        card.appendChild(img);
      } else {
        var tile = document.createElement("div");
        tile.className = "mh-folder-video-tile";
        tile.innerHTML = "<b>▶</b><span>视频</span>";
        card.appendChild(tile);
      }
      var meta = document.createElement("div");
      meta.className = "mh-folder-meta";
      var name = document.createElement("div");
      name.className = "mh-folder-name";
      name.textContent = rec.name;
      var sub = document.createElement("div");
      sub.className = "mh-folder-sub";
      sub.textContent = fmtSize(rec.size) + " · " + (rec.kind === "video" ? "视频" : "图片");
      meta.appendChild(name);
      meta.appendChild(sub);
      card.appendChild(meta);
      card.addEventListener("click", function (ev) {
        if (FOLDER.suppressClick) {
          FOLDER.suppressClick = false;
          return;
        }
        var index = FOLDER.records.indexOf(rec);
        if (ev.shiftKey && FOLDER.anchor >= 0) {
          folderSetRange(FOLDER.anchor, index, !FOLDER.selected[rec.path]);
        } else {
          folderToggle(rec, !FOLDER.selected[rec.path]);
          FOLDER.anchor = index;
        }
        folderSyncCards();
      });
      grid.appendChild(card);
    });
    folderRenderSelection();
    folderRenderPager();
  }

  function folderToggle(rec, on) {
    if (on) FOLDER.selected[rec.path] = rec;
    else delete FOLDER.selected[rec.path];
  }

  function folderSetRange(from, to, on) {
    if (from < 0 || to < 0 || from >= FOLDER.records.length || to >= FOLDER.records.length) return;
    var start = Math.min(from, to);
    var end = Math.max(from, to);
    for (var i = start; i <= end; i++) folderToggle(FOLDER.records[i], on);
  }

  function folderSyncCards() {
    var grid = document.getElementById("mh-folder-grid");
    if (grid) {
      Array.prototype.forEach.call(grid.querySelectorAll(".mh-folder-card"), function (card) {
        var rec = card.__mhRec;
        if (!rec) return;
        var on = !!FOLDER.selected[rec.path];
        card.classList.toggle("sel", on);
        var chk = card.querySelector(".mh-folder-chk");
        if (chk) chk.checked = on;
      });
    }
    folderRenderSelection();
  }

  function folderBindDrag() {
    var grid = document.getElementById("mh-folder-grid");
    if (!grid || FOLDER.dragBound) return;
    FOLDER.dragBound = true;
    grid.addEventListener("pointerdown", function (ev) {
      if (ev.button !== 0) return;
      if (ev.target.closest && ev.target.closest("input,button,a,textarea,select")) return;
      folderCancelDrag();
      FOLDER.drag = {
        startX: ev.clientX,
        startY: ev.clientY,
        base: Object.assign(Object.create(null), FOLDER.selected),
        moved: false,
        marquee: null
      };
      document.addEventListener("pointermove", folderDragMove, { passive: false });
      document.addEventListener("pointerup", folderDragEnd);
      document.addEventListener("pointercancel", folderCancelDrag);
    });
  }

  function folderDragMove(ev) {
    var drag = FOLDER.drag;
    if (!drag) return;
    var dx = ev.clientX - drag.startX;
    var dy = ev.clientY - drag.startY;
    if (!drag.moved && Math.abs(dx) < 5 && Math.abs(dy) < 5) return;
    drag.moved = true;
    ev.preventDefault();
    if (!drag.marquee) {
      drag.marquee = document.createElement("div");
      drag.marquee.className = "mh-folder-marquee";
      document.body.appendChild(drag.marquee);
    }
    var x1 = Math.min(drag.startX, ev.clientX);
    var y1 = Math.min(drag.startY, ev.clientY);
    var x2 = Math.max(drag.startX, ev.clientX);
    var y2 = Math.max(drag.startY, ev.clientY);
    drag.marquee.style.left = x1 + "px";
    drag.marquee.style.top = y1 + "px";
    drag.marquee.style.width = (x2 - x1) + "px";
    drag.marquee.style.height = (y2 - y1) + "px";
    FOLDER.selected = Object.assign(Object.create(null), drag.base);
    var grid = document.getElementById("mh-folder-grid");
    if (grid) {
      Array.prototype.forEach.call(grid.querySelectorAll(".mh-folder-card"), function (card) {
        var rect = card.getBoundingClientRect();
        if (rect.left < x2 && rect.right > x1 && rect.top < y2 && rect.bottom > y1 && card.__mhRec) {
          folderToggle(card.__mhRec, true);
        }
      });
    }
    folderSyncCards();
  }

  function folderDragEnd() {
    var drag = FOLDER.drag;
    if (!drag) return;
    var moved = drag.moved;
    if (drag.marquee && drag.marquee.parentNode) drag.marquee.parentNode.removeChild(drag.marquee);
    FOLDER.drag = null;
    document.removeEventListener("pointermove", folderDragMove);
    document.removeEventListener("pointerup", folderDragEnd);
    document.removeEventListener("pointercancel", folderCancelDrag);
    if (moved) {
      FOLDER.suppressClick = true;
      setTimeout(function () { FOLDER.suppressClick = false; }, 0);
      folderRenderSelection();
    }
  }

  function folderCancelDrag() {
    var drag = FOLDER.drag;
    if (drag && drag.marquee && drag.marquee.parentNode) drag.marquee.parentNode.removeChild(drag.marquee);
    FOLDER.drag = null;
    document.removeEventListener("pointermove", folderDragMove);
    document.removeEventListener("pointerup", folderDragEnd);
    document.removeEventListener("pointercancel", folderCancelDrag);
  }

  function folderRenderPager() {
    var info = document.getElementById("mh-folder-pageinfo");
    if (info) info.textContent = "第 " + FOLDER.page + " / " + FOLDER.pages + " 页";
    var prev = document.getElementById("mh-folder-prev");
    var next = document.getElementById("mh-folder-next");
    if (prev) prev.disabled = FOLDER.page <= 1;
    if (next) next.disabled = FOLDER.page >= FOLDER.pages;
  }

  function folderRenderSelection() {
    var count = Object.keys(FOLDER.selected).length;
    var label = document.getElementById("mh-folder-count");
    if (label) label.textContent = "已选 " + count + " 个";
    ["mh-folder-to-library", "mh-folder-to-embedding", "mh-folder-none"].forEach(function (id) {
      var e = document.getElementById(id);
      if (e) e.disabled = !count;
    });
  }

  function folderSelectAll() {
    folderCancelDrag();
    FOLDER.records.forEach(function (rec) { FOLDER.selected[rec.path] = rec; });
    FOLDER.anchor = -1;
    folderRender();
  }

  function folderClear() {
    folderCancelDrag();
    FOLDER.selected = Object.create(null);
    FOLDER.anchor = -1;
    folderRender();
  }

  function folderMove(dest) {
    var paths = Object.keys(FOLDER.selected);
    if (!paths.length) return;
    var label = dest === "library" ? "library" : "embeddingsafedata";
    if (!window.confirm("将 " + paths.length + " 个文件移动到 " + label + "？")) return;
    folderSetStatus("移动中…");
    fetch(BASE + "/folder/move", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ paths: paths, dest: dest })
    }).then(function (r) {
      return r.json().then(function (j) {
        if (!r.ok) throw new Error(j.error || ("HTTP " + r.status));
        return j;
      });
    }).then(function (j) {
      FOLDER.selected = Object.create(null);
      var msg = "已移动 " + (j.moved || []).length + " 个文件到 " + (j.dest || label);
      if (j.elapsed_s != null) msg += "（" + j.elapsed_s + "s）";
      if (j.stash_destroyed) msg += "；已移除 " + j.stash_destroyed + " 个 Stash 记录";
      if (j.scan_job) msg += "；Stash 扫描任务 " + j.scan_job;
      if (j.errors && j.errors.length) msg += "；失败 " + j.errors.length + " 个：" + j.errors.slice(0, 2).join("；");
      folderSetStatus(msg);
      setTimeout(folderLoad, 250);
    }).catch(function (e) {
      folderSetStatus("移动失败：" + e.message);
    });
  }

  // ---------- nine-cell Qwen review ----------
  function nineSetStatus(text) {
    var el = document.getElementById("mh-nine-status");
    if (el) el.textContent = text || "";
  }

  function nineInit() {
    if (NINE.initialized) return;
    NINE.initialized = true;
    var input = document.getElementById("mh-nine-folder");
    if (input && input.value.trim()) NINE.folder = input.value.trim();
    nineLoad();
  }

  function nineLoad() {
    var input = document.getElementById("mh-nine-folder");
    var folder = input ? input.value.trim() : NINE.folder;
    if (!folder) { nineSetStatus("请输入文件夹路径"); return; }
    NINE.folder = folder;
    NINE.cells = [];
    nineSetStatus("读取九张图片…");
    pmFetch("/nine/list", { folder: folder }).then(function (j) {
      NINE.paths = j.paths || [];
      NINE.cells = [];
      nineRender();
      var btn = document.getElementById("mh-nine-library");
      if (btn) btn.disabled = true;
      nineSetStatus("已读取 " + NINE.paths.length + " 张；点击「让模型判定」");
    }).catch(function (e) { nineSetStatus("读取失败：" + e.message); });
  }

  function nineRender() {
    var grid = document.getElementById("mh-nine-grid");
    if (!grid) return;
    grid.textContent = "";
    if (!NINE.paths.length) {
      var empty = document.createElement("div");
      empty.className = "mh-folder-empty";
      empty.textContent = "文件夹里没有可显示的图片";
      grid.appendChild(empty);
      return;
    }
    var byIndex = {};
    (NINE.cells || []).forEach(function (cell) { byIndex[cell.index] = cell; });
    NINE.paths.forEach(function (path, index) {
      var row = Math.floor(index / 3) + 1;
      var col = index % 3 + 1;
      var cellInfo = byIndex[index + 1];
      var cell = document.createElement("div");
      cell.className = "mh-nine-cell";
      if (cellInfo) cell.className += cellInfo.keep ? " keep" : " excluded";
      var img = document.createElement("img");
      img.loading = "eager";
      img.decoding = "async";
      img.alt = "";
      img.src = BASE + "/folder/thumb?size=480&path=" + encodeURIComponent(path);
      var pos = document.createElement("span");
      pos.className = "mh-nine-pos";
      pos.textContent = "第" + row + "行 第" + col + "列";
      cell.appendChild(img);
      cell.appendChild(pos);
      if (cellInfo) {
        var verdict = document.createElement("span");
        verdict.className = "mh-nine-verdict";
        verdict.textContent = (cellInfo.keep ? "保留 · " : "排除 · ") + cellInfo.level;
        cell.appendChild(verdict);
      }
      grid.appendChild(cell);
    });
  }

  function nineRun() {
    if (NINE.running) return;
    var input = document.getElementById("mh-nine-folder");
    var folder = input ? input.value.trim() : NINE.folder;
    if (!folder) { nineSetStatus("请输入文件夹路径"); return; }
    var model = pmValue("mh-nine-model") || "huihui";
    NINE.running = true;
    var btn = document.getElementById("mh-nine-run");
    if (btn) btn.disabled = true;
    nineSetStatus("本地模型并发判定 9 张中（每张独立上下文）…");
    pmFetch("/nine/scan", { folder: folder, model: model }).then(function (j) {
      NINE.cells = j.cells || [];
      nineRender();
      var keep = NINE.cells.filter(function (c) { return c.keep; });
      var positions = keep.map(function (c) { return "第" + c.row + "行第" + c.col + "列"; });
      var lib = document.getElementById("mh-nine-library");
      if (lib) lib.disabled = !keep.length;
      nineSetStatus("判定完成：保留 " + keep.length + " 张" +
        (positions.length ? "（" + positions.join("、") + "）" : "") +
        " · " + (j.elapsed_s || 0) + "s");
    }).catch(function (e) {
      nineSetStatus("判定失败：" + e.message);
    }).finally(function () {
      NINE.running = false;
      if (btn) btn.disabled = false;
    });
  }

  function nineLibrary() {
    var paths = (NINE.cells || []).filter(function (c) { return c.keep; }).map(function (c) { return c.path; });
    if (!paths.length) { nineSetStatus("没有保留项"); return; }
    if (!confirm("将 " + paths.length + " 张保留项移到 library？")) return;
    nineSetStatus("正在移入 library…");
    pmFetch("/pm/library", { paths: paths }).then(function (j) {
      var msg = "已移入 library " + (j.moved || []).length + " 张";
      if (j.scan_job) msg += "；Stash 扫描任务 " + j.scan_job;
      if (j.errors && j.errors.length) msg += "；失败 " + j.errors.length + " 个";
      nineSetStatus(msg);
      setTimeout(nineLoad, 300);
    }).catch(function (e) { nineSetStatus("移入 library 失败：" + e.message); });
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

  // ---------- face clustering ----------
  var FACES = {
    initialized: false, poll: null, page: 1, perPage: 24, total: 0, pages: 1,
    valuesLoaded: false, wasRunning: false
  };

  function faceSetStatus(text, danger) {
    var el = document.getElementById("mh-face-status");
    if (!el) return;
    el.textContent = text || "";
    el.className = "small mt-2 " + (danger ? "text-danger" : "text-muted");
  }

  function faceValues() {
    var force = document.getElementById("mh-face-force");
    return {
      force: !!(force && force.checked),
      threshold: Number(pmValue("mh-face-threshold") || 0.6),
      min_images: Math.max(1, Math.min(100, Number(pmValue("mh-face-min") || 3))),
      prefix: (pmValue("mh-face-prefix") || "人物").trim() || "人物"
    };
  }

  function faceSetRefreshing(running) {
    ["mh-face-scan", "mh-face-recluster", "mh-face-apply"].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.disabled = !!running;
    });
  }

  function faceTaskLabel(stage) {
    var labels = {
      starting: "准备中", enumerating: "读取图片", loading: "加载模型",
      scanning: "人脸扫描", clustering: "聚类", done: "完成", error: "失败"
    };
    return labels[stage] || stage || "处理中";
  }

  function faceRenderStatus(s) {
    var counts = s.counts || {};
    var task = s.task || {};
    if (!FACES.valuesLoaded) {
      FACES.valuesLoaded = true;
      var threshold = document.getElementById("mh-face-threshold");
      var minImages = document.getElementById("mh-face-min");
      if (threshold) threshold.value = String(s.threshold || 0.6);
      if (minImages) minImages.value = String(s.min_images || 3);
      var label = document.getElementById("mh-face-threshold-val");
      if (label) label.textContent = Number(s.threshold || 0.6).toFixed(2);
    }
    var parts = [];
    if (!s.model_ready) parts.push("人脸模型未下载（首次扫描自动下载）");
    else if (s.device) parts.push("人脸引擎 " + String(s.device).toUpperCase());
    parts.push("图片 " + (counts.images_done || 0) + "/" + (counts.images || 0));
    parts.push("人脸 " + (counts.faces || 0));
    parts.push("可用聚类 " + (counts.clusters_eligible || 0) + "（≥" + (s.min_images || 3) + " 张图）");
    parts.push("已写入演员 " + (counts.clusters_applied || 0));
    if (task.running) {
      parts.unshift(task.message || (faceTaskLabel(task.stage) +
        (task.total ? " " + task.done + "/" + task.total : "")));
      faceSetStatus(parts.join(" · "));
      faceSetRefreshing(true);
    } else {
      if (task.stage === "error" && task.error) parts.push("错误：" + task.error);
      faceSetStatus(parts.join(" · "), task.stage === "error");
      faceSetRefreshing(false);
    }
    var bar = document.getElementById("mh-face-progress");
    if (bar) {
      var percent = 0;
      if (task.running && task.total > 0) percent = Math.min(100, (task.done / task.total) * 100);
      else if (!task.running && counts.images) percent = 100;
      bar.style.width = percent.toFixed(1) + "%";
      bar.className = "progress-bar" + (task.stage === "error" ? " bg-danger" : "");
    }
  }

  function faceLoadStatus(loadClusters) {
    var values = faceValues();
    return pmFetch("/faces/status?min_images=" + encodeURIComponent(values.min_images)).then(function (s) {
      var wasRunning = FACES.wasRunning;
      FACES.wasRunning = !!(s.task && s.task.running);
      faceRenderStatus(s);
      if (s.task && s.task.running) {
        facePoll();
      } else if (FACES.poll) {
        clearInterval(FACES.poll);
        FACES.poll = null;
        faceLoadClusters();
      } else if (loadClusters || (wasRunning && !s.task.running)) {
        faceLoadClusters();
      }
      return s;
    }).catch(function (e) {
      faceSetStatus("人脸服务不可用：" + e.message, true);
      if (FACES.poll) {
        clearInterval(FACES.poll);
        FACES.poll = null;
      }
    });
  }

  function facePoll() {
    if (FACES.poll) return;
    FACES.poll = setInterval(function () { faceLoadStatus(false); }, 1200);
  }

  function faceCardEl(tag, className, text) {
    var el = document.createElement(tag);
    if (className) el.className = className;
    if (text !== undefined) el.textContent = text;
    return el;
  }

  function faceRenderClusters(data) {
    var host = document.getElementById("mh-face-grid");
    var hint = document.getElementById("mh-face-hint");
    if (!host) return;
    host.textContent = "";
    var clusters = data.clusters || [];
    FACES.total = Number(data.total || 0);
    FACES.page = Number(data.page || 1);
    FACES.perPage = Number(data.per_page || 24);
    FACES.pages = Math.max(1, Math.ceil(FACES.total / FACES.perPage));
    if (hint) hint.style.display = FACES.total ? "none" : "";
    var pager = document.getElementById("mh-face-pager");
    if (pager) pager.style.display = FACES.total > FACES.perPage ? "flex" : "none";
    var info = document.getElementById("mh-face-pageinfo");
    if (info) info.textContent = FACES.total ? (FACES.page + " / " + FACES.pages + " · " + FACES.total + " 个聚类") : "-";
    clusters.forEach(function (cluster) {
      var card = faceCardEl("div", "mh-face-card");
      var image = document.createElement("img");
      image.loading = "lazy";
      image.alt = "人物聚类";
      if (cluster.thumb_url) image.src = cluster.thumb_url;
      image.title = "查看该人物的图片";
      image.onclick = function () { faceOpenDetail(cluster.id); };
      card.appendChild(image);
      var body = faceCardEl("div", "mh-face-card-body");
      body.appendChild(faceCardEl("div", "mh-face-card-title",
        cluster.name || "未命名聚类（写入后自动命名）"));
      body.appendChild(faceCardEl("div", "mh-face-card-meta",
        cluster.image_count + " 张图片 · " + cluster.size + " 张人脸"));
      body.appendChild(faceCardEl("div", "mh-face-card-meta",
        cluster.performer_id ? "演员 #" + cluster.performer_id : "尚未写入演员"));
      var actions = faceCardEl("div", "mh-face-card-actions");
      var detail = faceCardEl("button", "btn btn-secondary btn-sm", "查看图片");
      detail.type = "button";
      detail.onclick = function () { faceOpenDetail(cluster.id); };
      actions.appendChild(detail);
      body.appendChild(actions);
      card.appendChild(body);
      host.appendChild(card);
    });
  }

  function faceLoadClusters() {
    var values = faceValues();
    return pmFetch("/faces/clusters?page=" + FACES.page + "&per_page=" + FACES.perPage +
      "&min_images=" + encodeURIComponent(values.min_images)).then(function (data) {
      faceRenderClusters(data);
    }).catch(function (e) {
      faceSetStatus("读取聚类失败：" + e.message, true);
    });
  }

  function faceOpenDetail(clusterId) {
    var panel = document.getElementById("mh-face-detail");
    var host = document.getElementById("mh-face-detail-images");
    var title = document.getElementById("mh-face-detail-title");
    if (!host || !panel) return;
    host.textContent = "";
    panel.style.display = "";
    if (title) title.textContent = "人物聚类 #" + clusterId + " · 读取中…";
    pmFetch("/faces/cluster?id=" + encodeURIComponent(clusterId) + "&limit=80").then(function (data) {
      var cluster = data.cluster || {};
      if (title) {
        title.textContent = "人物聚类 #" + cluster.id + " · " + (cluster.image_count || 0) +
          " 张图片 · " + (cluster.size || 0) + " 张人脸" +
          (cluster.performer_id ? " · 演员 #" + cluster.performer_id : "");
      }
      var images = data.images || [];
      if (images.length) {
        images.forEach(function (item) {
          var link = document.createElement("a");
          link.href = item.page_url || ("/images/" + item.stash_id);
          link.target = "_blank";
          link.rel = "noreferrer";
          var img = document.createElement("img");
          img.loading = "lazy";
          if (item.thumbnail_url) img.src = item.thumbnail_url;
          link.appendChild(img);
          link.appendChild(faceCardEl("span", "", item.title || ("图片 #" + item.stash_id)));
          host.appendChild(link);
        });
      } else {
        (data.faces || []).forEach(function (face) {
          var link = document.createElement("a");
          link.href = face.thumb_url;
          link.target = "_blank";
          link.rel = "noreferrer";
          var img = document.createElement("img");
          img.loading = "lazy";
          img.src = face.thumb_url;
          link.appendChild(img);
          link.appendChild(faceCardEl("span", "", "人脸 #" + face.id));
          host.appendChild(link);
        });
      }
      panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }).catch(function (e) {
      if (title) title.textContent = "读取人物聚类失败：" + e.message;
    });
  }

  function faceScan() {
    var values = faceValues();
    faceSetStatus("正在启动人脸扫描…");
    faceSetRefreshing(true);
    pmFetch("/faces/scan", { force: values.force, limit: 0 }).then(function () {
      FACES.wasRunning = true;
      facePoll();
    }).catch(function (e) {
      faceSetStatus("启动扫描失败：" + e.message, true);
      faceSetRefreshing(false);
    });
  }

  function faceRecluster() {
    var values = faceValues();
    faceSetStatus("正在重新聚类…");
    faceSetRefreshing(true);
    pmFetch("/faces/cluster", { threshold: values.threshold, min_images: values.min_images }).then(function () {
      FACES.wasRunning = true;
      facePoll();
    }).catch(function (e) {
      faceSetStatus("重新聚类失败：" + e.message, true);
      faceSetRefreshing(false);
    });
  }

  function faceApply() {
    var values = faceValues();
    var message = "将为至少 " + values.min_images + " 张图片的 " + (FACES.total || 0) +
      " 个聚类创建/更新演员，并把图片写入演员。不会移动或删除媒体文件。继续？";
    if (!window.confirm(message)) return;
    faceSetStatus("正在写入演员…");
    faceSetRefreshing(true);
    pmFetch("/faces/apply", { min_images: values.min_images, prefix: values.prefix }).then(function (j) {
      faceSetStatus("演员写入完成：新建 " + j.created + " 个，更新 " + j.updated +
        " 个，关联 " + j.images + " 张图片" + (j.warnings ? "，警告 " + j.warnings : ""));
      faceLoadStatus(false);
      faceLoadClusters();
    }).catch(function (e) {
      faceSetStatus("写入演员失败：" + e.message, true);
      faceSetRefreshing(false);
    });
  }

  function faceInit() {
    FACES.initialized = true;
    faceLoadStatus(true);
  }

  function settingsRenderStatus(s) {
    var el = document.getElementById("mh-settings-status");
    if (!el) return;
    var checks = s.checks || {};
    var overrides = s.overrides || {};
    var parts = [
      "资料库：" + (checks.media_exists ? "存在" : "不存在") + (checks.media_writable ? "，可写" : "，不可写"),
      "模型目录：" + (checks.models_exists ? "存在" : "不存在"),
      "QQ 根目录：" + (checks.qq_exists ? "存在" : "不存在")
    ];
    var env = [];
    if (overrides.media_root) env.push("资料库");
    if (overrides.models_root) env.push("模型目录");
    if (overrides.qq_base) env.push("QQ 根目录");
    if (env.length) parts.push("环境变量覆盖：" + env.join(" / "));
    el.textContent = parts.join(" · ");
    el.className = "small mb-2 " + (checks.media_writable ? "text-muted" : "text-danger");
  }

  function settingsLoad() {
    var el = document.getElementById("mh-settings-status");
    if (el) el.textContent = "读取中…";
    pmFetch("/settings").then(function (s) {
      var media = document.getElementById("mh-settings-media-root");
      var models = document.getElementById("mh-settings-models-root");
      var qq = document.getElementById("mh-settings-qq-base");
      if (media) media.value = s.media_root || "";
      if (models) models.value = s.models_root || "";
      if (qq) qq.value = s.qq_base || "";
      settingsRenderStatus(s);
    }).catch(function (e) {
      if (el) {
        el.textContent = "读取设置失败：" + e.message;
        el.className = "small text-danger mb-2";
      }
    });
  }

  function settingsSave() {
    var el = document.getElementById("mh-settings-status");
    var button = document.getElementById("mh-settings-save");
    var payload = {
      media_root: pmValue("mh-settings-media-root"),
      models_root: pmValue("mh-settings-models-root"),
      qq_base: pmValue("mh-settings-qq-base")
    };
    if (button) {
      button.disabled = true;
      button.textContent = "保存中…";
    }
    pmFetch("/settings", payload).then(function (r) {
      settingsRenderStatus(r.settings || {});
      if (el) {
        el.textContent = r.restart_required
          ? "已保存。需要重启 MineHub 后生效；现有文件不会自动移动。"
          : "已保存；当前生效路径未变化。";
        el.className = "small mb-2 text-success";
      }
    }).catch(function (e) {
      if (el) {
        el.textContent = "保存失败：" + e.message;
        el.className = "small text-danger mb-2";
      }
    }).then(function () {
      if (button) {
        button.disabled = false;
        button.textContent = "保存设置";
      }
    });
  }

  // ---------- mount ----------
  function update() {
    applyListDefaults();
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
      "#mh-hub .mh-card-check-wrap{position:absolute;left:8px;top:8px;right:auto;z-index:4;width:22px;height:22px;display:flex;align-items:center;justify-content:center;background:rgba(13,17,23,.72);border:2px solid #dbe4eb;border-radius:4px;cursor:pointer}",
      "#mh-hub .mh-card.sel .mh-card-check-wrap{background:#48aff0;border-color:#48aff0}",
      "#mh-hub .mh-card-check{position:absolute;inset:0;width:100%;height:100%;margin:0;opacity:0;cursor:pointer;z-index:2}",
      "#mh-hub .mh-card .mh-card-check-tick{display:none;padding:0;color:#15212b;font-size:16px;font-weight:700;line-height:1;pointer-events:none}",
      "#mh-hub .mh-card .mh-card-check:checked + .mh-card-check-tick{display:block}",
      "#mh-hub .mh-card-sim{position:absolute;right:8px;top:8px;z-index:5;width:28px;height:28px;display:flex;align-items:center;justify-content:center;padding:0;border:1px solid rgba(255,255,255,.6);border-radius:4px;background:rgba(13,17,23,.78);color:#fff;cursor:pointer;opacity:.9;z-index:60}",
      "#mh-hub .mh-card-sim:hover{background:#48aff0;border-color:#48aff0;color:#15212b}",
      "#mh-hub .mh-card-sim svg{width:14px;height:14px;pointer-events:none}",
      "#mh-hub .mh-source{display:flex;gap:14px;align-items:flex-start;max-width:900px;margin:0 0 14px;padding:10px;border:1px solid #3b4a55;border-radius:6px;background:#24323c}",
      "#mh-hub .mh-source[hidden]{display:none}",
      "#mh-hub .mh-source img{display:block;max-width:min(420px,48vw);max-height:320px;object-fit:contain;background:#0b1015;border-radius:4px}",
      "#mh-hub .mh-source-meta{min-width:0;flex:1;color:#aab8c4;font-size:12px;line-height:1.6}",
      "#mh-hub .mh-source-meta strong{display:block;color:#f5f8fa;font-size:15px;margin-bottom:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}",
      "#mh-hub .mh-source-meta a{color:#8ab4ff;text-decoration:none}",
      "#mh-hub .mh-source-chips{display:flex;flex-wrap:wrap;gap:5px;margin-top:8px}",
      "#mh-hub .mh-source-chip{display:inline-block;padding:2px 6px;border-radius:4px;background:#23313d;color:#9fc2e0;font-size:11px;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}",
      "#mh-hub .mh-source-chip.sem{background:#1e465f;color:#9fe0ff}",
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
      "#mh-hub .mh-face-card{background:#2c3e50;border:1px solid #3b4a55;border-radius:4px;overflow:hidden;min-width:0}",
      "#mh-hub .mh-face-card img{display:block;width:100%;height:170px;object-fit:cover;object-position:center;background:#1f2a33;cursor:pointer}",
      "#mh-hub .mh-face-card-body{padding:7px 8px 8px;min-width:0}",
      "#mh-hub .mh-face-card-title{color:#f5f8fa;font-size:13px;line-height:1.4;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}",
      "#mh-hub .mh-face-card-meta{color:#aab8c4;font-size:11px;line-height:1.7}",
      "#mh-hub .mh-face-card-actions{display:flex;gap:5px;margin-top:5px}",
      "#mh-hub .mh-face-detail-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:8px}",
      "#mh-hub .mh-face-detail-grid a{display:block;border:1px solid #3b4a55;border-radius:3px;overflow:hidden;background:#1f2a33;color:#c4d0da;text-decoration:none}",
      "#mh-hub .mh-face-detail-grid img{display:block;width:100%;height:110px;object-fit:cover;background:#1f2a33}",
      "#mh-hub .mh-face-detail-grid span{display:block;padding:4px 6px;font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}",
      "#mh-hub .mh-placeholder h4{color:#f5f8fa}",
      "#mh-hub .mh-preset{margin-left:5px;padding:2px 8px;border:1px solid #4a5b69;border-radius:4px;background:#26333f;color:#c4d0da;font-size:12px;cursor:pointer}",
      "#mh-hub .mh-preset:hover{border-color:#48aff0;color:#fff}",
      "#mh-hub .mh-preset.active{background:#48aff0;border-color:#48aff0;color:#15212b}",
      "#mh-hub #mh-map-shell{position:relative;background:radial-gradient(circle at 50% 45%,#1b2a36 0%,#10171e 62%,#0b1015 100%);border:1px solid #33434f;border-radius:6px;overflow:hidden}",
      "#mh-hub #mh-map-canvas{display:block;width:100%;height:min(68vh,720px);cursor:crosshair}",
      "#mh-hub #mh-map-tip{display:none;position:absolute;z-index:5;width:236px;padding:7px;background:rgba(10,16,22,.96);border:1px solid #4a5b69;border-radius:6px;box-shadow:0 10px 30px rgba(0,0,0,.55);pointer-events:none;color:#dbe4eb;font-size:11px;line-height:1.45}",
      "#mh-hub #mh-map-tip img{display:block;width:100%;height:150px;object-fit:contain;background:#070b0f;border-radius:3px;margin-bottom:5px}",
      "#mh-hub #mh-map-tip strong{display:block;color:#f5f8fa;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}",
      "#mh-hub #mh-map-tip span{display:block;color:#9fb0bd;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}",
      "#mh-hub .mh-map-legend{display:flex;flex-wrap:wrap;gap:12px;align-items:center}",
      "#mh-hub .mh-map-legend i{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:4px;vertical-align:-1px}",
      "#mh-hub .mh-map-help{color:#8fa2b2;font-size:11px}",
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

  function mapColor(group, alpha) {
    var color = MAP_COLORS[group] || MAP_COLORS[MAP_COLORS.length - 1];
    return "rgba(" + color.rgb + "," + alpha + ")";
  }

  function mapLegend() {
    var box = document.getElementById("mh-map-legend");
    if (!box || box.children.length) return;
    var groups = MAP.groups.length ? MAP.groups : ["成人", "性感", "二次元", "截图/文字", "日常", "其他"];
    groups.forEach(function (name, index) {
      var item = document.createElement("span");
      var dot = document.createElement("i");
      dot.style.background = MAP_COLORS[index] ? MAP_COLORS[index].hex : "#8b9aa6";
      item.appendChild(dot);
      item.appendChild(document.createTextNode(name));
      box.appendChild(item);
    });
  }

  function mapTooltip(point) {
    var tip = document.getElementById("mh-map-tip");
    if (!tip) return;
    tip.textContent = "";
    var image = document.createElement("img");
    image.alt = "";
    image.src = point.kind === "scene"
      ? "/scene/" + point.id + "/screenshot"
      : "/image/" + point.id + "/thumbnail";
    var title = document.createElement("strong");
    title.textContent = point.title || (point.kind === "scene" ? "场景" : "图片") + " #" + point.id;
    var tags = document.createElement("span");
    tags.textContent = point.tags || "无标签";
    tip.append(image, title, tags);
  }

  function mapDraw() {
    var canvas = document.getElementById("mh-map-canvas");
    if (!canvas) return;
    var rect = canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    var dpr = window.devicePixelRatio || 1;
    var width = Math.round(rect.width * dpr);
    var height = Math.round(rect.height * dpr);
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width;
      canvas.height = height;
    }
    var ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, rect.width, rect.height);
    var cx = rect.width / 2;
    var cy = rect.height / 2;
    var scale = Math.min(rect.width, rect.height) * 0.45;
    for (var ring = 1; ring <= 3; ring++) {
      ctx.beginPath();
      ctx.strokeStyle = "rgba(88,166,255," + (0.045 / ring) + ")";
      ctx.arc(cx, cy, scale * ring / 3, 0, Math.PI * 2);
      ctx.stroke();
    }
    var points = MAP.points;
    if (!points.length) return;
    if (!MAP.screen || MAP.screen.length !== points.length * 2) {
      MAP.screen = new Float32Array(points.length * 2);
    }
    var zoom = MAP.view.zoom;
    var ox = MAP.view.ox;
    var oy = MAP.view.oy;
    for (var i = 0; i < points.length; i++) {
      var point = points[i];
      var sx = cx + (point.x * zoom + ox) * scale;
      var sy = cy + (-point.y * zoom + oy) * scale;
      MAP.screen[i * 2] = sx;
      MAP.screen[i * 2 + 1] = sy;
    }
    var highlight = MAP.highlight;
    var alpha = highlight ? 0.14 : 0.62;
    for (var group = 0; group < MAP_COLORS.length; group++) {
      ctx.fillStyle = mapColor(group, alpha);
      for (var j = 0; j < points.length; j++) {
        if (points[j].g !== group) continue;
        var gx = MAP.screen[j * 2];
        var gy = MAP.screen[j * 2 + 1];
        if (gx < -4 || gy < -4 || gx > rect.width + 4 || gy > rect.height + 4) continue;
        ctx.fillRect(gx - 1.1, gy - 1.1, 2.2, 2.2);
      }
    }
    if (highlight) {
      ctx.fillStyle = "rgba(130,220,255,.96)";
      for (var k = 0; k < points.length; k++) {
        if (!highlight[points[k].kind + "|" + points[k].id]) continue;
        var hx = MAP.screen[k * 2];
        var hy = MAP.screen[k * 2 + 1];
        ctx.beginPath();
        ctx.arc(hx, hy, 2.8, 0, Math.PI * 2);
        ctx.fill();
      }
    }
    if (MAP.hover >= 0 && MAP.hover < points.length) {
      var vx = MAP.screen[MAP.hover * 2];
      var vy = MAP.screen[MAP.hover * 2 + 1];
      ctx.beginPath();
      ctx.strokeStyle = "#ffffff";
      ctx.lineWidth = 1.4;
      ctx.arc(vx, vy, 6, 0, Math.PI * 2);
      ctx.stroke();
      ctx.beginPath();
      ctx.strokeStyle = "rgba(255,255,255,.25)";
      ctx.arc(vx, vy, 12, 0, Math.PI * 2);
      ctx.stroke();
    }
  }

  function mapHideTip() {
    var tip = document.getElementById("mh-map-tip");
    if (tip) tip.style.display = "none";
    MAP.hover = -1;
  }

  function mapShowTip(index, clientX, clientY) {
    var canvas = document.getElementById("mh-map-canvas");
    var tip = document.getElementById("mh-map-tip");
    if (!canvas || !tip || index < 0) return;
    var point = MAP.points[index];
    if (!point) return;
    if (MAP.hover !== index) {
      MAP.hover = index;
      mapTooltip(point);
      mapDraw();
    }
    var rect = canvas.getBoundingClientRect();
    tip.style.display = "block";
    var left = clientX - rect.left + 16;
    var top = clientY - rect.top + 14;
    if (left + 250 > rect.width) left = Math.max(6, left - 270);
    if (top + 240 > rect.height) top = Math.max(6, top - 250);
    tip.style.left = left + "px";
    tip.style.top = top + "px";
  }

  function mapNearest(clientX, clientY) {
    var canvas = document.getElementById("mh-map-canvas");
    if (!canvas || !MAP.screen) return -1;
    var rect = canvas.getBoundingClientRect();
    var x = clientX - rect.left;
    var y = clientY - rect.top;
    var best = -1;
    var bestDistance = 110;
    var highlight = MAP.highlight;
    for (var i = 0; i < MAP.points.length; i++) {
      var point = MAP.points[i];
      if (highlight && !highlight[point.kind + "|" + point.id]) continue;
      var dx = MAP.screen[i * 2] - x;
      var dy = MAP.screen[i * 2 + 1] - y;
      var distance = dx * dx + dy * dy;
      if (distance < bestDistance) {
        bestDistance = distance;
        best = i;
      }
    }
    return best;
  }

  function mapLoad() {
    if (MAP.loading) return;
    MAP.loading = true;
    var status = document.getElementById("mh-map-status");
    if (status) status.textContent = "正在计算二维语义投影…";
    fetch(BASE + "/semantic/map").then(function (response) {
      return response.json().then(function (body) {
        if (!response.ok) throw new Error(body.error || ("HTTP " + response.status));
        return body;
      });
    }).then(function (data) {
      MAP.points = data.points || [];
      MAP.groups = data.groups || [];
      MAP.loaded = true;
      mapLegend();
      if (status) {
        status.textContent = MAP.points.length + " 个点 · " + (data.dim || 0) +
          " 维 · 每点一张图片/场景";
      }
      mapDraw();
    }).catch(function (error) {
      if (status) status.textContent = "语义投影失败：" + error.message;
    }).finally(function () {
      MAP.loading = false;
    });
  }

  function mapReset() {
    MAP.view = { zoom: 1, ox: 0, oy: 0 };
    MAP.highlight = null;
    mapHideTip();
    var input = document.getElementById("mh-map-q");
    if (input) input.value = "";
    var status = document.getElementById("mh-map-status");
    if (status) status.textContent = MAP.points.length + " 个点 · 视图已重置";
    mapDraw();
  }

  function mapHighlight() {
    var input = document.getElementById("mh-map-q");
    var status = document.getElementById("mh-map-status");
    var text = input ? input.value.trim() : "";
    if (!text) {
      MAP.highlight = null;
      if (status) status.textContent = "请输入描述后高亮";
      mapDraw();
      return;
    }
    if (status) status.textContent = "正在搜索相似语义…";
    fetch(BASE + "/search", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        text: text, mode: "hybrid", min_score: 0.055, kind: "all", match: "all",
        fields: INLINE_ALL_FIELDS.slice(), top: 100
      })
    }).then(function (response) {
      return response.json().then(function (body) {
        if (!response.ok) throw new Error(body.error || ("HTTP " + response.status));
        return body;
      });
    }).then(function (body) {
      var rows = body.results || [];
      var highlight = Object.create(null);
      rows.forEach(function (row) {
        highlight[row.kind + "|" + row.stash_id] = true;
      });
      MAP.highlight = highlight;
      if (status) {
        status.textContent = rows.length
          ? "已高亮 " + rows.length + " 个语义相近结果（Top 100）· 仅高亮点可选中"
          : "没有找到相近结果";
      }
      mapDraw();
    }).catch(function (error) {
      if (status) status.textContent = "高亮失败：" + error.message;
    });
  }

  function mapBind() {
    if (MAP.bound) return;
    MAP.bound = true;
    var canvas = document.getElementById("mh-map-canvas");
    if (!canvas) return;
    canvas.addEventListener("pointerdown", function (e) {
      if (e.button !== 0) return;
      MAP.drag = {
        x: e.clientX, y: e.clientY, ox: MAP.view.ox, oy: MAP.view.oy, moved: false
      };
      canvas.setPointerCapture(e.pointerId);
    });
    canvas.addEventListener("pointermove", function (e) {
      if (MAP.drag) {
        var dx = e.clientX - MAP.drag.x;
        var dy = e.clientY - MAP.drag.y;
        var rect = canvas.getBoundingClientRect();
        var scale = Math.max(1, Math.min(rect.width, rect.height) * 0.45);
        if (Math.abs(dx) + Math.abs(dy) > 3) MAP.drag.moved = true;
        MAP.view.ox = MAP.drag.ox + dx / scale;
        MAP.view.oy = MAP.drag.oy + dy / scale;
        mapHideTip();
        mapDraw();
        return;
      }
      var index = mapNearest(e.clientX, e.clientY);
      if (index >= 0) {
        mapShowTip(index, e.clientX, e.clientY);
      } else if (MAP.hover >= 0) {
        mapHideTip();
        var tip = document.getElementById("mh-map-tip");
        if (tip) tip.style.display = "none";
        mapDraw();
      }
    });
    canvas.addEventListener("pointerup", function (e) {
      if (!MAP.drag) return;
      var moved = MAP.drag.moved;
      MAP.drag = null;
      if (moved) {
        MAP.suppressClick = Date.now() + 220;
        return;
      }
      var index = mapNearest(e.clientX, e.clientY);
      if (index >= 0) {
        var point = MAP.points[index];
        navigateTo((point.kind === "scene" ? "/scenes/" : "/images/") + point.id);
      }
    });
    canvas.addEventListener("pointerleave", function () {
      MAP.drag = null;
      mapHideTip();
      var tip = document.getElementById("mh-map-tip");
      if (tip) tip.style.display = "none";
      mapDraw();
    });
    canvas.addEventListener("wheel", function (e) {
      e.preventDefault();
      var factor = Math.exp(-e.deltaY * 0.0012);
      MAP.view.zoom = Math.max(0.35, Math.min(9, MAP.view.zoom * factor));
      mapHideTip();
      mapDraw();
    }, { passive: false });
    window.addEventListener("resize", function () {
      var pane = document.getElementById("mh-tab-map");
      if (pane && pane.style.display !== "none") mapDraw();
    });
  }

  function mapInit() {
    mapLegend();
    mapBind();
    if (!MAP.loaded) mapLoad();
    else requestAnimationFrame(mapDraw);
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
          <li class="nav-item"><a href="#" class="nav-link" data-mh-tab="map">语义星图</a></li>
          <li class="nav-item"><a href="#" class="nav-link" data-mh-tab="qq">QQ 缓存</a></li>
          <li class="nav-item"><a href="#" class="nav-link" data-mh-tab="faces">人脸聚类</a></li>
          <li class="nav-item"><a href="#" class="nav-link" data-mh-tab="dupes">重复检测</a></li>
          <li class="nav-item"><a href="#" class="nav-link" data-mh-tab="folder">文件夹</a></li>
          <li class="nav-item"><a href="#" class="nav-link" data-mh-tab="nine">九宫格</a></li>
          <li class="nav-item"><a href="#" class="nav-link" data-mh-tab="settings">设置</a></li>
        </ul>
        <div id="mh-tab-search" class="mh-tab-pane">
          <div class="input-group mb-2" style="max-width:760px">
            <input id="mh-q" class="form-control" placeholder="中文/英文描述搜图，或输入图片/场景 ID">
            <div class="input-group-append"><button id="mh-go" class="btn btn-primary">搜索</button></div>
          </div>
          <div class="d-flex flex-wrap align-items-center mb-2" style="max-width:900px;gap:6px">
            <label for="mh-mode" class="small text-muted mb-0 mr-1 mh-mode-label">模式</label>
            <span class="mr-2" style="color:#f5f8fa">特征</span>
            <label class="small text-muted mb-0 mr-2"><input id="mh-regex" type="checkbox"> 正则</label>
            <select id="mh-mode" class="form-control form-control-sm mr-2" style="display:none">
              <option value="feature">特征搜索</option>
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
          <div id="mh-source" class="mh-source" hidden>
            <a id="mh-source-link" href="#" target="_blank" rel="noopener"><img id="mh-source-img" alt=""></a>
            <div class="mh-source-meta">
              <strong id="mh-source-name"></strong>
              <div id="mh-source-sub"></div>
              <div id="mh-source-chips" class="mh-source-chips"></div>
              <div class="mt-2"><a id="mh-source-page" href="#" target="_blank" rel="noopener"></a></div>
            </div>
          </div>
          <div id="mh-status" class="text-muted mb-3"></div>
          <div id="mh-search-actions" class="flex-wrap align-items-center mb-3" style="display:none">
            <span id="mh-search-selected-count" class="text-muted mr-3">已选 0 个</span>
            <button id="mh-search-trash" type="button" class="btn btn-secondary btn-sm mr-2">放入回收站</button>
            <button id="mh-search-delete" type="button" class="btn btn-danger btn-sm mr-2">直接删除文件</button>
            <button id="mh-search-clear" type="button" class="btn btn-secondary btn-sm">取消选择</button>
          </div>
          <div id="mh-search-hint" class="mh-empty-state">
            <strong>搜索 MineHub 图库</strong>
            特征模式同时按画面语义、文件名、路径、标签和 ID 匹配；正则模式只做表达式匹配。多个关键词用 <code>；</code> <code>;</code> <code>，</code> <code>,</code> <code>、</code> 或换行分隔。
            <p class="small text-muted mb-0 mt-2">图片卡片上的放大镜会打开 Stash 原生灯箱预览；点击图片边缘或名称进入详情页。场景放大镜仍打开 Stash 原生页面。勾选后可批量放入回收站或永久删除。</p>
          </div>
          <div id="mh-results" class="mh-card-grid"></div>
        </div>
        <div id="mh-tab-map" class="mh-tab-pane" style="display:none">
          <div class="card mb-2"><div class="card-body py-2">
            <div class="d-flex flex-wrap align-items-center" style="gap:8px">
              <input id="mh-map-q" class="form-control form-control-sm" style="width:300px" placeholder="输入描述，高亮语义相近的图片">
              <button id="mh-map-go" class="btn btn-primary btn-sm">高亮相似</button>
              <button id="mh-map-reset" class="btn btn-secondary btn-sm">重置视图</button>
              <span id="mh-map-status" class="small text-muted">首次打开需要计算二维投影…</span>
            </div>
            <div class="mt-2 d-flex flex-wrap align-items-center" style="gap:14px">
              <div id="mh-map-legend" class="mh-map-legend"></div>
              <span class="mh-map-help">每个点是一张图片/场景 · 滚轮缩放 · 拖拽平移 · 悬停看缩略图 · 点击打开详情</span>
            </div>
          </div></div>
          <div id="mh-map-shell">
            <canvas id="mh-map-canvas"></canvas>
            <div id="mh-map-tip"></div>
          </div>
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
                <div class="form-check"><input id="mh-pm-groups" type="checkbox" class="form-check-input"><label class="form-check-label" for="mh-pm-groups">仅群聊内容</label></div>
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
                <button id="mh-pm-library" class="btn btn-success btn-sm mr-1">移到 library</button>
                <button id="mh-pm-dupe-open" class="btn btn-secondary btn-sm mr-1">查重 QQ</button>
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
          <div class="card mb-2"><div class="card-body py-2">
            <div class="d-flex flex-wrap align-items-center" style="gap:8px">
              <button id="mh-face-scan" class="btn btn-primary btn-sm">扫描人脸</button>
              <div class="form-check form-check-inline mb-0">
                <input id="mh-face-force" type="checkbox" class="form-check-input">
                <label class="form-check-label" for="mh-face-force">强制重扫</label>
              </div>
              <button id="mh-face-recluster" class="btn btn-secondary btn-sm">重新聚类</button>
              <label for="mh-face-threshold" class="small text-muted mb-0">相似度 <span id="mh-face-threshold-val">0.60</span></label>
              <input id="mh-face-threshold" type="range" min="0.30" max="0.75" step="0.01" value="0.60" class="custom-range" style="width:150px">
              <label for="mh-face-min" class="small text-muted mb-0">最少图片</label>
              <input id="mh-face-min" type="number" min="1" max="100" value="3" class="form-control form-control-sm" style="width:72px">
              <label for="mh-face-prefix" class="small text-muted mb-0">演员名前缀</label>
              <input id="mh-face-prefix" class="form-control form-control-sm" value="人物" style="width:110px">
              <button id="mh-face-apply" class="btn btn-success btn-sm">写入演员</button>
            </div>
            <div class="progress mt-2" style="height:6px"><div id="mh-face-progress" class="progress-bar" style="width:0%"></div></div>
            <div id="mh-face-status" class="small text-muted mt-2">读取人脸服务状态…</div>
          </div></div>
          <div id="mh-face-hint" class="mh-empty-state">
            <strong>按人物聚类照片</strong>
            使用 InsightFace 检测人脸并提取特征，按余弦相似度聚类；只会处理 Stash 图片（GIF 取首帧），不会修改原始文件。调整阈值后可重新聚类，确认后再批量创建演员并把图片写入演员。
          </div>
          <div id="mh-face-grid" class="mh-card-grid"></div>
          <div id="mh-face-pager" class="d-flex align-items-center justify-content-center my-2" style="display:none">
            <button id="mh-face-prev" class="btn btn-secondary btn-sm mr-2">上一页</button>
            <span id="mh-face-pageinfo" class="text-muted mr-2">-</span>
            <button id="mh-face-next" class="btn btn-secondary btn-sm">下一页</button>
          </div>
          <div id="mh-face-detail" class="card mt-3" style="display:none">
            <div class="card-body">
              <div class="d-flex align-items-center mb-2">
                <strong id="mh-face-detail-title" class="mr-auto">人物聚类</strong>
                <button id="mh-face-detail-close" class="btn btn-secondary btn-sm">关闭</button>
              </div>
              <div id="mh-face-detail-images" class="mh-face-detail-grid"></div>
            </div>
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
        <div id="mh-tab-folder" class="mh-tab-pane" style="display:none">
          <div class="card mb-2"><div class="card-body py-2">
            <div class="d-flex flex-wrap align-items-center" style="gap:8px">
              <label class="small text-muted mb-0">文件夹</label>
              <input id="mh-folder-path" class="form-control form-control-sm" value="F:\\MineHubData\\safe" spellcheck="false" style="min-width:300px;flex:1 1 360px">
              <label class="small text-muted mb-0"><input id="mh-folder-recursive" type="checkbox" checked> 含子文件夹</label>
              <select id="mh-folder-kind" class="form-control form-control-sm" style="width:100px">
                <option value="all">图片+视频</option><option value="image">仅图片</option><option value="video">仅视频</option>
              </select>
              <button id="mh-folder-load" class="btn btn-primary btn-sm">浏览</button>
              <button id="mh-folder-refresh" class="btn btn-secondary btn-sm">刷新</button>
            </div>
            <div id="mh-folder-status" class="small mt-2">点击图片即选中；Shift 连选，按住左键拖拽框选。只能访问 F:\\MineHubData 内的媒体。</div>
          </div></div>
          <div class="d-flex flex-wrap align-items-center mb-2" style="gap:6px">
            <span id="mh-folder-count" class="text-muted mr-2">已选 0 个</span>
            <button id="mh-folder-all" class="btn btn-secondary btn-sm">全选本页</button>
            <button id="mh-folder-none" class="btn btn-secondary btn-sm">取消选择</button>
            <button id="mh-folder-to-library" class="btn btn-success btn-sm">移到 library</button>
            <button id="mh-folder-to-embedding" class="btn btn-primary btn-sm">移到 embeddingsafedata</button>
            <span class="small text-muted" style="margin-left:auto">点击图片即选中 · Shift 连选 · 左键拖拽框选</span>
          </div>
          <div id="mh-folder-grid" class="mh-card-grid">
            <div class="mh-folder-empty">输入路径后浏览文件夹。</div>
          </div>
          <div id="mh-folder-pager" class="d-flex align-items-center justify-content-center my-2">
            <button id="mh-folder-prev" class="btn btn-secondary btn-sm mr-2">上一页</button>
            <span id="mh-folder-pageinfo" class="text-muted mr-2">-</span>
            <button id="mh-folder-next" class="btn btn-secondary btn-sm">下一页</button>
          </div>
        </div>
        <div id="mh-tab-nine" class="mh-tab-pane" style="display:none">
          <div class="card mb-2"><div class="card-body py-2">
            <div class="d-flex flex-wrap align-items-center" style="gap:8px">
              <label class="small text-muted mb-0">文件夹</label>
              <input id="mh-nine-folder" class="form-control form-control-sm" value="F:\\MineHubData\\review\\qwen3vltest9pic" spellcheck="false" style="min-width:320px;flex:1 1 380px">
              <select id="mh-nine-model" class="form-control form-control-sm" style="width:150px">
                <option value="huihui">Huihui</option>
                <option value="nsfw">NSFW Caption</option>
              </select>
              <button id="mh-nine-load" class="btn btn-secondary btn-sm">读取 9 张</button>
              <button id="mh-nine-run" class="btn btn-primary btn-sm">让模型判定</button>
              <button id="mh-nine-library" class="btn btn-success btn-sm" disabled>保留项移到 library</button>
            </div>
            <div id="mh-nine-status" class="small text-muted mt-2">按文件名顺序读取九张图；本地 Qwen3-VL 每张独立并发判定，不拼接、不串图。</div>
          </div></div>
          <div id="mh-nine-grid"></div>
        </div>
        <div id="mh-tab-settings" class="mh-tab-pane" style="display:none">
          <div class="card mb-2"><div class="card-body">
            <h4>数据目录</h4>
            <p class="small text-muted">路径保存到项目 <code>data/settings.json</code>。环境变量优先于这里的设置；保存后需要重启 MineHub 才会应用。</p>
            <div class="form-group mb-2">
              <label for="mh-settings-media-root" class="mb-1">资料库根目录</label>
              <input id="mh-settings-media-root" class="form-control form-control-sm" spellcheck="false" placeholder="例如 F:\\MineHubData">
              <small class="form-text text-muted">存放 library、review、cache、qq_thumbs、safe 和 Stash 生成文件。</small>
            </div>
            <div class="form-group mb-2">
              <label for="mh-settings-models-root" class="mb-1">模型目录</label>
              <input id="mh-settings-models-root" class="form-control form-control-sm" spellcheck="false" placeholder="例如 F:\\MineHubData\\models">
              <small class="form-text text-muted">SigLIP2、Qwen3-VL 等模型所在目录；可以和资料库分开放在不同磁盘。</small>
            </div>
            <div class="form-group mb-2">
              <label for="mh-settings-qq-base" class="mb-1">QQ 数据根目录</label>
              <input id="mh-settings-qq-base" class="form-control form-control-sm" spellcheck="false" placeholder="例如 D:\\Tencent Files">
              <small class="form-text text-muted">用于可选的 QQ 缓存扫描和归属索引；留空时使用默认路径。</small>
            </div>
            <div id="mh-settings-status" class="small text-muted mb-2"></div>
            <button id="mh-settings-save" class="btn btn-primary btn-sm">保存设置</button>
            <button id="mh-settings-reload" class="btn btn-secondary btn-sm">重新读取</button>
            <div class="alert alert-warning mt-3 mb-0 small">保存只切换路径，不会自动移动现有文件。修改资料库或模型目录后，请关闭托盘中的 MineHub，再用项目根目录的一键启动脚本重新启动。</div>
          </div></div>
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
        <div id="mh-pm-dupe">
          <div id="mh-pm-dupe-box">
            <div id="mh-pm-dupe-head"><strong>QQ 重复检测</strong><span id="mh-pm-dupe-status"></span><button id="mh-pm-dupe-x" type="button">×</button></div>
            <div id="mh-pm-dupe-tools">
              <button id="mh-pm-dupe-scan" class="blue" type="button">扫描并计算</button>
              <button id="mh-pm-dupe-select" class="green" type="button">选中所有重复项</button>
              <button id="mh-pm-dupe-recycle" class="red" type="button">移入回收站</button>
              <button id="mh-pm-dupe-library" class="blue" type="button">移到 library</button>
              <button id="mh-pm-dupe-close" type="button">关闭</button>
            </div>
            <div id="mh-pm-dupe-note" class="small text-muted"></div>
            <div id="mh-pm-dupe-results"></div>
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
    document.getElementById("mh-pm-library").onclick = pmLibrary;
    document.getElementById("mh-pm-dupe-open").onclick = pmDupeOpen;
    document.getElementById("mh-pm-del").onclick = pmRecycle;
    document.getElementById("mh-pm-open").onclick = pmOpenSelected;
    document.getElementById("mh-pm-dupe-x").onclick = pmDupeClose;
    document.getElementById("mh-pm-dupe-close").onclick = pmDupeClose;
    document.getElementById("mh-pm-dupe-scan").onclick = pmDupeScan;
    document.getElementById("mh-pm-dupe-select").onclick = pmDupeSelectAll;
    document.getElementById("mh-pm-dupe-recycle").onclick = function () { pmDupeClose(); pmRecycle(); };
    document.getElementById("mh-pm-dupe-library").onclick = function () { pmDupeClose(); pmLibrary(); };
    document.getElementById("mh-pm-dupe").addEventListener("click", function (e) {
      if (e.target.id === "mh-pm-dupe") pmDupeClose();
    });
    document.getElementById("mh-pm-prev").onclick = function () { if (PM.page > 1) { PM.page--; pmQuery(); } };
    document.getElementById("mh-pm-next").onclick = function () { if (PM.page < PM.pages) { PM.page++; pmQuery(); } };
    document.getElementById("mh-pm-preview-close").onclick = function () {
      document.getElementById("mh-pm-preview").classList.remove("open");
    };
    document.getElementById("mh-pm-preview").addEventListener("click", function (e) {
      if (e.target.id === "mh-pm-preview") e.target.classList.remove("open");
    });
    document.getElementById("mh-nine-load").onclick = nineLoad;
    document.getElementById("mh-nine-run").onclick = nineRun;
    document.getElementById("mh-nine-library").onclick = nineLibrary;
    document.getElementById("mh-nine-folder").addEventListener("keydown", function (e) {
      if (e.key === "Enter") nineLoad();
    });
    document.getElementById("mh-folder-load").onclick = function () { FOLDER.page = 1; folderLoad(); };
    document.getElementById("mh-folder-refresh").onclick = function () { folderLoad(); };
    document.getElementById("mh-folder-path").addEventListener("keydown", function (e) {
      if (e.key === "Enter") { FOLDER.page = 1; folderLoad(); }
    });
    document.getElementById("mh-folder-recursive").onchange = function () { FOLDER.page = 1; folderLoad(); };
    document.getElementById("mh-folder-kind").onchange = function () { FOLDER.page = 1; folderLoad(); };
    document.getElementById("mh-folder-all").onclick = folderSelectAll;
    document.getElementById("mh-folder-none").onclick = folderClear;
    document.getElementById("mh-folder-to-library").onclick = function () { folderMove("library"); };
    document.getElementById("mh-folder-to-embedding").onclick = function () { folderMove("embeddingsafedata"); };
    document.getElementById("mh-folder-prev").onclick = function () {
      if (FOLDER.page > 1) { FOLDER.page--; folderLoad(); }
    };
    document.getElementById("mh-folder-next").onclick = function () {
      if (FOLDER.page < FOLDER.pages) { FOLDER.page++; folderLoad(); }
    };
    document.getElementById("mh-go").onclick = searchText;
    document.getElementById("mh-q").onkeydown = function (e) { if (e.key === "Enter") searchText(); };
    document.getElementById("mh-map-go").onclick = mapHighlight;
    document.getElementById("mh-map-reset").onclick = mapReset;
    document.getElementById("mh-map-q").onkeydown = function (e) {
      if (e.key === "Enter") mapHighlight();
    };
    document.getElementById("mh-mode").addEventListener("change", function () {
      updateModeUI();
      rerunWithOptions();
    });
    ["mh-kind", "mh-match", "mh-ignore-case"].forEach(function (id) {
      document.getElementById(id).addEventListener("change", rerunWithOptions);
    });
    document.getElementById("mh-regex").addEventListener("change", function () {
      updateModeUI();
      rerunWithOptions();
    });
    var regexButtons = document.querySelectorAll("#mh-regex-presets [data-regex]");
    for (var ri = 0; ri < regexButtons.length; ri++) {
      regexButtons[ri].onclick = function () {
        var input = document.getElementById("mh-q");
        if (input) input.value = this.dataset.regex;
        var regexBox = document.getElementById("mh-regex");
        if (regexBox) regexBox.checked = true;
        updateModeUI();
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
    document.getElementById("mh-face-scan").onclick = faceScan;
    document.getElementById("mh-face-recluster").onclick = faceRecluster;
    document.getElementById("mh-face-apply").onclick = faceApply;
    document.getElementById("mh-face-threshold").addEventListener("input", function () {
      var label = document.getElementById("mh-face-threshold-val");
      if (label) label.textContent = Number(pmValue("mh-face-threshold") || 0.6).toFixed(2);
    });
    document.getElementById("mh-face-min").addEventListener("change", function () {
      FACES.page = 1;
      faceLoadClusters();
    });
    document.getElementById("mh-face-prev").onclick = function () {
      if (FACES.page > 1) {
        FACES.page--;
        faceLoadClusters();
      }
    };
    document.getElementById("mh-face-next").onclick = function () {
      if (FACES.page < FACES.pages) {
        FACES.page++;
        faceLoadClusters();
      }
    };
    document.getElementById("mh-face-detail-close").onclick = function () {
      document.getElementById("mh-face-detail").style.display = "none";
    };
    document.getElementById("mh-settings-save").onclick = settingsSave;
    document.getElementById("mh-settings-reload").onclick = settingsLoad;
    document.getElementById("mh-pm-chatsearch").addEventListener("input", pmRenderChats);
    document.getElementById("mh-pm-chatmode").addEventListener("change", pmUpdateChatControls);
    document.getElementById("mh-pm-groups").addEventListener("change", pmRenderChats);
    ["mh-pm-kind", "mh-pm-scope", "mh-pm-sort", "mh-pm-dir", "mh-pm-cat", "mh-pm-level",
      "mh-pm-only", "mh-pm-review", "mh-pm-chatmode", "mh-pm-groups", "mh-pm-unknown", "mh-pm-mapped"].forEach(function (id) {
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
    ["search", "map", "qq", "faces", "dupes", "folder", "nine", "settings"].forEach(function (t) {
      var p = document.getElementById("mh-tab-" + t);
      if (p) p.style.display = t === name ? "" : "none";
    });
    if (name === "map") mapInit();
    if (name === "qq") ensurePmLoaded();
    if (name === "faces") faceInit();
    if (name === "dupes") dupeInit();
    if (name === "folder") folderInit();
    if (name === "nine") nineInit();
    if (name === "settings") settingsLoad();
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
      mode: "feature",
      regex: p.get("mode") === "regex" || p.get("regex") === "1",
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
    var regexEl = document.getElementById("mh-regex");
    if (modeEl) modeEl.value = "feature";
    if (kindEl) kindEl.value = p.kind;
    if (matchEl) matchEl.value = p.match;
    if (regexEl) regexEl.checked = !!p.regex;
    updateModeUI();
    if (p.id) {
      setScoreRange("image");
      var topEl = document.getElementById("mh-top");
      if (topEl) topEl.value = String(SIMILAR_TOP);
      renderTopPresets();
      showSource(p.kind, p.id);
      if (title) title.textContent = "相似于 " + (p.kind === "scene" ? "场景" : "图片") + " #" + p.id;
      if (hint) hint.style.display = "none";
      doSearch({ stash_id: String(p.id), kind: p.kind, top: topValue(), min_score: scoreValue() });
    } else if (p.text) {
      hideSource();
      if (input) input.value = p.text;
      if (title) title.textContent = p.regex ? "MineHub 特征搜索（正则）" : "MineHub 特征搜索";
      if (hint) hint.style.display = "none";
      searchText();
    } else {
      hideSource();
      setScoreRange("text");
      if (title) title.textContent = "";
      var results = document.getElementById("mh-results");
      if (hint && (!results || !results.children.length)) hint.style.display = "";
    }
  }

  function syncPage() {
    if (INLINE.active) {
      var currentPath = location.pathname.replace(/\/+$/, "");
      if (currentPath !== INLINE.path) closeInlineSearch();
    }
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

  function navigateTo(url) {
    if (!url) return;
    var target;
    try {
      target = new URL(url, location.origin);
    } catch (e) {
      location.assign(url);
      return;
    }
    var next = target.pathname + target.search + target.hash;
    var current = location.pathname + location.search + location.hash;
    if (next === current) return;
    try {
      history.pushState(Object.assign({}, history.state || {}), "", next);
      window.dispatchEvent(new PopStateEvent("popstate"));
    } catch (e) {
      location.assign(next);
    }
  }

  function openHub(tab) {
    if (location.pathname !== PAGE_PATH) {
      var q = tab && tab !== "search" ? "?tab=" + encodeURIComponent(tab) : "";
      navigateTo(PAGE_PATH + q);
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
    navigateTo(PAGE_PATH + (qs.toString() ? "?" + qs.toString() : ""));
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
      '<span>搜索</span></a>';
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

  function gifTimelineCleanup() {
    var state = GIF_TIMELINE;
    GIF_TIMELINE = null;
    if (!state) return;
    if (state.timer) clearTimeout(state.timer);
    state.gen++;
    if (state.ro) state.ro.disconnect();
    if (state.decoder) { try { state.decoder.close(); } catch (e) {} }
    if (state.canvas && state.canvas.parentNode) state.canvas.parentNode.removeChild(state.canvas);
    if (state.bar && state.bar.parentNode) state.bar.parentNode.removeChild(state.bar);
    if (state.img) state.img.style.visibility = "";
  }

  function installGifTimeline(id, info, tries) {
    tries = tries || 0;
    var container = document.querySelector(".image-container");
    var img = container && container.querySelector("img.image-image, img");
    if (!container || !img) {
      if (tries < 20) {
        setTimeout(function () {
          if (GIF_INFO && GIF_INFO.id === id) installGifTimeline(id, info, tries + 1);
        }, 250);
      }
      return;
    }
    if (GIF_TIMELINE && GIF_TIMELINE.id === id && GIF_TIMELINE.bar && GIF_TIMELINE.bar.isConnected) return;
    var existingBar = container.querySelector(".mh-gif-timeline");
    if (existingBar) {
      if (existingBar.dataset.mhGifId === String(id)) return;
      existingBar.parentNode.removeChild(existingBar);
      var oldCanvas = container.querySelector(".mh-gif-canvas");
      if (oldCanvas && oldCanvas.parentNode) oldCanvas.parentNode.removeChild(oldCanvas);
    }
    gifTimelineCleanup();

    var canvas = document.createElement("canvas");
    canvas.className = "mh-gif-canvas";
    var bar = document.createElement("div");
    bar.className = "mh-gif-timeline";
    bar.dataset.mhGifId = String(id);
    bar.style.visibility = "hidden";
    bar.innerHTML = '<button type="button" class="mh-gif-play" title="暂停">❚❚</button>' +
      '<input type="range" min="0" max="0" value="0" step="1" aria-label="GIF 帧">' +
      '<span class="mh-gif-count">1 / 1</span>';
    container.appendChild(canvas);
    container.appendChild(bar);

    var state = {
      id: id, img: img, canvas: canvas, bar: bar, decoder: null,
      count: 0, index: 0, playing: false, timer: 0, gen: 0, ro: null,
      slider: bar.querySelector("input"), countEl: bar.querySelector(".mh-gif-count"),
      playBtn: bar.querySelector(".mh-gif-play")
    };
    GIF_TIMELINE = state;

    function syncRect() {
      if (GIF_TIMELINE !== state) return;
      var r = img.getBoundingClientRect();
      var c = container.getBoundingClientRect();
      canvas.style.left = (r.left - c.left) + "px";
      canvas.style.top = (r.top - c.top) + "px";
      canvas.style.width = r.width + "px";
      canvas.style.height = r.height + "px";
    }
    state.ro = window.ResizeObserver ? new ResizeObserver(syncRect) : null;
    if (state.ro) {
      state.ro.observe(img);
      state.ro.observe(container);
    }
    syncRect();
    canvas.width = Number(info.width) || img.naturalWidth || 1;
    canvas.height = Number(info.height) || img.naturalHeight || 1;

    var src = img.currentSrc || img.src;
    fetch(src, { cache: "force-cache" }).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.arrayBuffer();
    }).then(function (buf) {
      if (!window.ImageDecoder) throw new Error("ImageDecoder unsupported");
      var decoder = new ImageDecoder({ data: buf, type: "image/gif" });
      state.decoder = decoder;
      return decoder.tracks.ready.then(function () { return decoder; });
    }).then(function (decoder) {
      if (GIF_TIMELINE !== state) { try { decoder.close(); } catch (e) {} return; }
      var track = decoder.tracks.selectedTrack;
      var count = track ? Number(track.frameCount) : 0;
      if (!count || count < 2) {
        if (GIF_INFO && GIF_INFO.id === id) GIF_INFO.timelineFailed = true;
        gifTimelineCleanup();
        return;
      }
      state.count = count;
      state.slider.max = String(count - 1);
      canvas.style.display = "block";
      bar.style.visibility = "visible";
      img.style.visibility = "hidden";
      syncRect();
      state.playBtn.onclick = function () {
        if (state.playing) pauseGifTimeline(); else playGifTimeline();
      };
      state.slider.oninput = function () {
        pauseGifTimeline();
        var n = Math.max(0, Math.min(count - 1, Number(state.slider.value) || 0));
        state.index = n;
        showGifFrame(n);
      };
      playGifTimeline();
    }).catch(function () {
      if (GIF_INFO && GIF_INFO.id === id) GIF_INFO.timelineFailed = true;
      if (GIF_TIMELINE === state) gifTimelineCleanup();
    });

    function showGifFrame(n) {
      if (GIF_TIMELINE !== state || !state.decoder) return Promise.resolve(100);
      var gen = state.gen;
      return state.decoder.decode({ frameIndex: n }).then(function (result) {
        var frame = result.image;
        if (GIF_TIMELINE !== state || gen !== state.gen) { frame.close(); return 100; }
        var ctx = canvas.getContext("2d");
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.drawImage(frame, 0, 0, canvas.width, canvas.height);
        var delay = frame.duration ? frame.duration / 1000 : 100;
        frame.close();
        state.index = n;
        state.slider.value = String(n);
        state.countEl.textContent = (n + 1) + " / " + state.count;
        return delay;
      });
    }

    function playGifTimeline() {
      if (GIF_TIMELINE !== state || !state.decoder || state.playing) return;
      state.playing = true;
      state.playBtn.textContent = "❚❚";
      state.playBtn.title = "暂停";
      state.gen++;
      var gen = state.gen;
      function run() {
        if (GIF_TIMELINE !== state || !state.playing || gen !== state.gen) return;
        showGifFrame(state.index).then(function (delay) {
          if (GIF_TIMELINE !== state || !state.playing || gen !== state.gen) return;
          state.timer = setTimeout(function () {
            if (GIF_TIMELINE !== state || !state.playing || gen !== state.gen) return;
            state.index = (state.index + 1) % state.count;
            run();
          }, Math.max(30, delay || 100));
        }).catch(function () { pauseGifTimeline(); });
      }
      run();
    }

    function pauseGifTimeline() {
      state.playing = false;
      state.gen++;
      if (state.timer) { clearTimeout(state.timer); state.timer = 0; }
      state.playBtn.textContent = "▶";
      state.playBtn.title = "播放";
    }
  }

  function injectGifNote() {
    var m = location.pathname.match(/^\/images\/(\d+)(?:$|\/)/);
    if (!m) {
      gifTimelineCleanup();
      GIF_INFO = null;
      var old = document.getElementById("mh-gif-note");
      if (old) old.remove();
      return;
    }
    var panel = document.querySelector(".file-info-panel");
    if (!panel) return;
    var note = document.getElementById("mh-gif-note");
    var id = m[1];
    if (GIF_INFO && GIF_INFO.id === id) {
      if (GIF_INFO.node && !note) panel.insertBefore(GIF_INFO.node, panel.firstChild);
      if (GIF_INFO.info && GIF_INFO.info.is_gif && Number(GIF_INFO.info.frames) > 1 &&
          !GIF_INFO.timelineFailed) {
        installGifTimeline(id, GIF_INFO.info);
      }
      return;
    }
    if (note) note.remove();
    gifTimelineCleanup();
    GIF_INFO = { id: id, node: null, info: null, timelineFailed: false };
    fetch(BASE + "/media/info?kind=image&id=" + encodeURIComponent(id))
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (j) {
        if (!GIF_INFO || GIF_INFO.id !== id) return;
        GIF_INFO.info = j;
        if (j.is_gif && Number(j.frames) > 1) {
          installGifTimeline(id, j);
          return;
        }
        if (!j.is_gif || Number(j.frames) !== 1) return;
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
    var ctx = inlineContext();
    if (!ctx) return;
    if (INLINE.active && INLINE.input && INLINE.input.isConnected &&
        !INLINE.input.value.trim()) {
      closeInlineSearch();
    }
    installInlineModeBar(ctx);
    installInlineInput(ctx);
    installFeaturePopover();
    updateInlineInputHints();
    if (!INLINE_CLEAR_BOUND) {
      INLINE_CLEAR_BOUND = true;
      document.addEventListener("click", function (e) {
        if (INLINE.active && e.target.closest(".clearable-text-field-clear")) {
          closeInlineSearch();
        }
      }, true);
    }
    var inputs = document.querySelectorAll(
      ".filtered-list-toolbar .search-term-input input, .sidebar-search-container input"
    );
    for (var i = 0; i < inputs.length; i++) {
      var input = inputs[i];
      if (!input.dataset.mhSemanticBound) {
        input.dataset.mhSemanticBound = "1";
        input.addEventListener("keydown", function (e) {
          if (e.key === "Escape") {
            closeInlineSearch();
            return;
          }
          if (e.key !== "Enter" || e.isComposing || e.keyCode === 229) return;
          var text = e.currentTarget.value.trim();
          var current = location.pathname.replace(/\/+$/, "");
          var targetKind = current === "/images" ? "image" : (current === "/scenes" ? "scene" : "");
          if (!targetKind) return;
          e.preventDefault();
          e.stopPropagation();
          e.stopImmediatePropagation();
          if (!text) {
            closeInlineSearch();
            return;
          }
          runInlineSearch(e.currentTarget, text, targetKind);
        }, true);
        input.addEventListener("input", function (e) {
          if (INLINE.active && !e.currentTarget.value.trim()) {
            closeInlineSearch();
          }
        });
      }
    }
  }

  var FEATURE_POP = null;
  var FEATURE_BOUND = false;

  function closeFeaturePop() {
    if (!FEATURE_POP) return;
    FEATURE_POP.remove();
    FEATURE_POP = null;
  }

  function placeFeaturePop(anchor) {
    if (!FEATURE_POP || !anchor) return;
    var rect = anchor.getBoundingClientRect();
    var box = FEATURE_POP.getBoundingClientRect();
    var left = Math.max(12, Math.min(window.innerWidth - box.width - 12,
      rect.left + rect.width / 2 - box.width / 2));
    var top = rect.bottom + 8;
    if (top + box.height > window.innerHeight - 12) {
      top = Math.max(12, rect.top - box.height - 8);
    }
    FEATURE_POP.style.left = left + "px";
    FEATURE_POP.style.top = top + "px";
  }

  function renderFeaturePop(pop, data) {
    pop.textContent = "";
    var head = document.createElement("h6");
    head.textContent = "MineHub 特征";
    var hint = document.createElement("span");
    hint.textContent = "语义 Top5 + 全部关键词";
    head.appendChild(hint);
    pop.appendChild(head);

    var semTitle = document.createElement("h6");
    semTitle.textContent = "语义";
    pop.appendChild(semTitle);
    var semBox = document.createElement("div");
    semBox.className = "mh-feature-chips";
    (data.semantic || []).forEach(function (term) {
      var chip = document.createElement("span");
      chip.className = "mh-feature-chip sem";
      chip.textContent = term.label;
      chip.title = term.key + " · " + Number(term.score).toFixed(3);
      semBox.appendChild(chip);
    });
    if (!semBox.children.length) {
      var empty = document.createElement("div");
      empty.className = "mh-feature-empty";
      empty.textContent = "暂无语义标签";
      pop.appendChild(empty);
    } else {
      pop.appendChild(semBox);
    }

    var keyTitle = document.createElement("h6");
    keyTitle.textContent = "关键词";
    pop.appendChild(keyTitle);
    var keyBox = document.createElement("div");
    keyBox.className = "mh-feature-chips";
    (data.keywords || []).forEach(function (tag) {
      var chip = document.createElement("span");
      chip.className = "mh-feature-chip";
      chip.textContent = tag;
      keyBox.appendChild(chip);
    });
    if (!keyBox.children.length) {
      var keyEmpty = document.createElement("div");
      keyEmpty.className = "mh-feature-empty";
      keyEmpty.textContent = "没有标签";
      pop.appendChild(keyEmpty);
    } else {
      pop.appendChild(keyBox);
    }

    var foot = document.createElement("div");
    foot.className = "mh-feature-foot";
    var open = document.createElement("a");
    open.href = data.page_url || (data.kind === "scene"
      ? "/scenes/" + data.stash_id : "/images/" + data.stash_id);
    open.textContent = "打开详情";
    open.target = "_blank";
    open.rel = "noreferrer";
    var close = document.createElement("a");
    close.href = "#";
    close.textContent = "关闭";
    close.onclick = function (e) {
      e.preventDefault();
      closeFeaturePop();
    };
    foot.append(open, close);
    pop.appendChild(foot);
  }

  function openFeaturePop(anchor, kind, stashId) {
    closeFeaturePop();
    var pop = document.createElement("div");
    pop.className = "mh-feature-pop";
    var loading = document.createElement("div");
    loading.className = "mh-feature-empty";
    loading.textContent = "读取语义特征…";
    pop.appendChild(loading);
    document.body.appendChild(pop);
    FEATURE_POP = pop;
    placeFeaturePop(anchor);
    var url = BASE + "/media/features?kind=" + encodeURIComponent(kind) +
      "&id=" + encodeURIComponent(stashId);
    fetch(url).then(function (response) {
      return response.json().then(function (body) {
        if (!response.ok) throw new Error(body.error || ("HTTP " + response.status));
        return body;
      });
    }).then(function (data) {
      if (FEATURE_POP !== pop) return;
      renderFeaturePop(pop, data);
      placeFeaturePop(anchor);
    }).catch(function (error) {
      if (FEATURE_POP !== pop) return;
      pop.textContent = "";
      var msg = document.createElement("div");
      msg.className = "mh-feature-empty";
      msg.textContent = "读取失败：" + error.message;
      pop.appendChild(msg);
      placeFeaturePop(anchor);
    });
  }

  function installFeaturePopover() {
    if (FEATURE_BOUND) return;
    FEATURE_BOUND = true;
    document.addEventListener("click", function (e) {
      var button = e.target.closest(".tag-count button");
      if (button) {
        var card = button.closest(".image-card, .scene-card");
        var link = card && card.querySelector('a[href^="/images/"], a[href^="/scenes/"]');
        if (link) {
          e.preventDefault();
          e.stopPropagation();
          e.stopImmediatePropagation();
          var parts = link.getAttribute("href").split("/");
          openFeaturePop(button, parts[1] === "scenes" ? "scene" : "image", parts[2]);
          return;
        }
      }
      if (FEATURE_POP && !FEATURE_POP.contains(e.target)) closeFeaturePop();
    }, true);
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") closeFeaturePop();
    }, true);
    window.addEventListener("scroll", closeFeaturePop, true);
  }

  function imageIdFromSrc(src) {
    if (!src) return "";
    var i = src.indexOf("/image/");
    if (i >= 0) {
      var rest = src.slice(i + 7);
      var n = 0;
      while (n < rest.length && rest.charAt(n) >= "0" && rest.charAt(n) <= "9") n++;
      if (n) return rest.slice(0, n);
    }
    i = src.indexOf("/scene/");
    if (i >= 0) {
      var rest2 = src.slice(i + 7);
      var n2 = 0;
      while (n2 < rest2.length && rest2.charAt(n2) >= "0" && rest2.charAt(n2) <= "9") n2++;
      if (n2) return rest2.slice(0, n2);
    }
    return "";
  }

  function wallItemDetailUrl(item) {
    var link = item.querySelector('a[href^="/images/"], a[href^="/scenes/"]');
    if (link) return link.getAttribute("href");
    var img = item.querySelector("img");
    var src = img ? (img.currentSrc || img.src || img.getAttribute("src") || "") : "";
    var id = imageIdFromSrc(src);
    if (id) return (src.indexOf("/scene/") >= 0 ? "/scenes/" : "/images/") + id;
    var video = item.querySelector("video");
    var vsrc = video ? (video.currentSrc || video.src || "") : "";
    id = imageIdFromSrc(vsrc);
    if (id) return (vsrc.indexOf("/scene/") >= 0 ? "/scenes/" : "/images/") + id;
    return "";
  }

  function sceneIdFromUrl(url) {
    var id = ((String(url || "").split("/")[2] || "").split("?")[0].split("#")[0]);
    return /^[0-9]+$/.test(id) ? id : "";
  }

  function wallScenePreviewItems() {
    var items = [];
    var nodes = document.querySelectorAll(".wall-item");
    for (var i = 0; i < nodes.length; i++) {
      var node = nodes[i];
      var url = wallItemDetailUrl(node);
      if (url.indexOf("/scenes/") !== 0) continue;
      var id = sceneIdFromUrl(url);
      if (!id) continue;
      var img = node.querySelector("img");
      var title = (node.getAttribute("title") || (img && img.alt) || "").trim();
      items.push({
        kind: "scene",
        id: id,
        title: title,
        image: "/scene/" + id + "/screenshot",
        video: "/scene/" + id + "/preview",
        fallbackVideo: "/scene/" + id + "/stream",
        page_url: url
      });
    }
    return items;
  }

  function openSceneWallPreview(card) {
    var url = wallItemDetailUrl(card);
    var id = sceneIdFromUrl(url);
    var items = wallScenePreviewItems();
    var index = 0;
    for (var i = 0; i < items.length; i++) {
      if (items[i].id === id) { index = i; break; }
    }
    if (!items.length) {
      window.location.assign(url);
      return;
    }
    openMediaViewer(items, index);
  }

  function injectWallPreviewButtons() {
    var items = document.querySelectorAll(".wall-item");
    for (var i = 0; i < items.length; i++) {
      var item = items[i];
      if (item.closest("#mh-hub") || item.querySelector(".mh-wall-preview")) continue;
      var url = wallItemDetailUrl(item);
      var isScene = url.indexOf("/scenes/") === 0;
      if (!isScene && url.indexOf("/images/") !== 0) continue;
      var button = document.createElement("button");
      button.type = "button";
      button.className = "mh-wall-preview";
      button.dataset.mhKind = isScene ? "scene" : "image";
      button.title = isScene ? "预览视频" : "预览";
      button.setAttribute("aria-label", button.title);
      button.innerHTML = isScene ? WALL_PLAY_SVG : WALL_PREVIEW_SVG;
      button.addEventListener("click", function (event) {
        event.preventDefault();
        event.stopPropagation();
        var card = this.closest(".wall-item");
        if (!card) return;
        if (this.dataset.mhKind === "scene") {
          openSceneWallPreview(card);
          return;
        }
        card.dataset.mhNativePreview = "1";
        card.click();
        setTimeout(function () { delete card.dataset.mhNativePreview; }, 0);
      });
      item.appendChild(button);
    }
  }

  var WALL_CLICK_BOUND = false;
  function installWallClickGuard() {
    if (WALL_CLICK_BOUND) return;
    WALL_CLICK_BOUND = true;
    document.addEventListener("click", function (event) {
      var item = event.target.closest(".wall-item");
      if (!item) return;
      if (wallItemDetailUrl(item).indexOf("/images/") !== 0) return;
      if (event.target.closest(".mh-wall-preview") || event.target.closest(".mh-image-sim") ||
          event.target.closest(".wall-item-check") || event.target.closest("a[href]")) return;
      if (document.querySelector(".wall-item-check:checked")) return;
      if (item.dataset.mhNativePreview === "1") {
        delete item.dataset.mhNativePreview;
        return;
      }
      var url = wallItemDetailUrl(item);
      if (!url) return;
      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation();
      window.location.assign(url);
    }, true);
  }

  function cardImageId(card) {
    if (!card) return "";
    var link = card.querySelector('a[href^="/images/"]');
    if (link) {
      var parts = (link.getAttribute("href") || "").split("/");
      if (parts[1] === "images" && /^[0-9]+$/.test(parts[2] || "")) return parts[2];
    }
    var img = card.querySelector("img");
    var src = img ? (img.currentSrc || img.src || img.getAttribute("src") || "") : "";
    var m = /\/images?\/([0-9]+)/.exec(src);
    return m ? m[1] : "";
  }

  function nativeSelectedImageIds() {
    var ids = Array.from(NATIVE_SELECTION.image || []);
    if (ids.length) return ids;
    var seen = Object.create(null);
    var nodes = document.querySelectorAll(
      ".wall-item-check:checked, .image-card input[type=checkbox]:checked, " +
      ".image-card.selected, .wall-item.selected"
    );
    for (var i = 0; i < nodes.length; i++) {
      var card = nodes[i].closest(".wall-item, .image-card");
      var id = cardImageId(card);
      if (id) seen[id] = true;
    }
    return Object.keys(seen);
  }

  function trainingMoveSelected() {
    var ids = nativeSelectedImageIds();
    if (!ids.length) {
      window.alert("请先在图片列表中勾选图片");
      return;
    }
    if (!window.confirm("将选中的 " + ids.length + " 张图片移动到\nF:\\MineHubData\\embeddingsafedata？")) return;
    var btn = document.getElementById("mh-training-move-btn");
    if (btn) btn.disabled = true;
    fetch(BASE + "/library/move", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        items: ids.map(function (id) { return { kind: "image", id: id }; }),
        dest: "embeddingsafedata"
      })
    }).then(function (r) {
      return r.json().then(function (j) {
        if (!r.ok) throw new Error(j.error || ("HTTP " + r.status));
        return j;
      });
    }).then(function (j) {
      var msg = "已移动 " + (j.moved || []).length + " 张到 embeddingsafedata";
      if (j.errors && j.errors.length) msg += "；失败 " + j.errors.length + " 条：" + j.errors.slice(0, 2).join("；");
      window.alert(msg);
      window.location.reload();
    }).catch(function (e) {
      window.alert("移动失败：" + (e.message || e));
      if (btn) btn.disabled = false;
    });
  }

  function ensureTrainingMoveButton() {
    if (listPath() !== "/images") return;
    var toolbar = document.querySelector(".filtered-list-toolbar");
    if (!toolbar) return;
    var button = document.getElementById("mh-training-move-btn");
    if (!button) {
      button = document.createElement("button");
      button.id = "mh-training-move-btn";
      button.type = "button";
      button.className = "btn btn-secondary btn-sm mh-training-move";
      button.addEventListener("click", function (e) {
        e.preventDefault();
        trainingMoveSelected();
      });
    }
    var trash = toolbar.querySelector('button[title*="Delete"], button[title*="删除"], svg[data-icon="trash"]');
    if (trash && trash.tagName.toLowerCase() === "svg") trash = trash.closest("button");
    var more = toolbar.querySelector("#more-menu, .list-operations .dropdown-toggle, svg[data-icon=\"ellipsis\"]");
    if (more && more.tagName.toLowerCase() === "svg") more = more.closest("button");
    if (more && more.parentNode) {
      if (button.parentNode !== more.parentNode || button.nextElementSibling !== more) {
        more.parentNode.insertBefore(button, more);
      }
    } else if (trash && trash.parentNode) {
      if (button.previousElementSibling !== trash) trash.parentNode.insertBefore(button, trash.nextSibling);
    } else if (button.parentNode !== toolbar) {
      toolbar.appendChild(button);
    }
    var count = nativeSelectedImageIds().length;
    button.innerHTML = '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M3 7h6l2 2h10v10H3z"/><path d="M12 12v5M9.5 14.5h5"/></svg><span>训练集' + (count ? " " + count : "") + "</span>";
    button.title = count
      ? "移动选中的 " + count + " 张图片到 F:\\MineHubData\\embeddingsafedata"
      : "先勾选图片；选中后移动到 embeddingsafedata";
  }

  function injectNativeSimilarButtons() {
    var cards = document.querySelectorAll(".image-card, .wall-item");
    for (var i = 0; i < cards.length; i++) {
      var card = cards[i];
      if (card.closest("#mh-hub") || card.querySelector(".mh-image-sim")) continue;
      if (card.classList.contains("wall-item") && wallItemDetailUrl(card).indexOf("/images/") !== 0) continue;
      var link = card.querySelector('a[href^="/images/"]');
      var id = "";
      if (link) {
        var parts = (link.getAttribute("href") || "").split("/");
        if (parts[1] === "images" && /^[0-9]+$/.test(parts[2] || "")) id = parts[2];
      }
      if (!id) {
        var img = card.querySelector("img");
        id = imageIdFromSrc(img ? (img.currentSrc || img.src || img.getAttribute("src") || "") : "");
      }
      if (!id) continue;
      var button = document.createElement("button");
      button.type = "button";
      button.className = "mh-image-sim";
      button.title = "查找相似图片";
      button.setAttribute("aria-label", "查找相似图片");
      button.dataset.mhSimId = id;
      button.innerHTML = SIMILAR_SVG;
      button.addEventListener("click", function (event) {
        event.preventDefault();
        event.stopPropagation();
        openSearch({ id: this.dataset.mhSimId, kind: "image" });
      });
      card.appendChild(button);
    }
  }

  function translateSceneLabel() {
    var spans = document.querySelectorAll(".top-nav a span, .nav-link a span");
    for (var i = 0; i < spans.length; i++) {
      if (spans[i].textContent.trim() === "短片") spans[i].textContent = "视频";
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
    document.title = document.title.replace(/\bStash\b/g, "MineHub").replace(/短片/g, "视频");
    translateSceneLabel();
    var brands = document.querySelectorAll(".brand-link");
    for (var i = 0; i < brands.length; i++) {
      if (brands[i].textContent.trim() === "Stash") brands[i].textContent = "MineHub";
    }
    injectNavItem();
    injectDetailButton();
    injectGifNote();
    installWallClickGuard();
    injectWallPreviewButtons();
    injectNativeSimilarButtons();
    ensureTrainingMoveButton();
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
      installNativeListPatches();
      applyListDefaults();
      polish();
    }, 40);
  }

  new MutationObserver(update).observe(document.documentElement, { childList: true, subtree: true });
  window.addEventListener("popstate", update);
  window.addEventListener("hashchange", update);
  setInterval(update, 1000);
  ensureStyle();
  installNativeListPatches();
  installWallClickGuard();
  update();
})();
