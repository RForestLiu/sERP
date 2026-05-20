/**
 * sERP ExtensionHelper — 店小秘 Ozon 智能助手
 * 左侧悬浮工具栏：选择产品 → 智能匹配品类 → 大模型自动填充表单
 */
(function () {
  "use strict";

  // ==================== 配置 ====================
  var FLASK_BASE = "http://127.0.0.1:5000";
  var API_PRODUCTS = FLASK_BASE + "/api/products";
  var API_AUTO_FILL = FLASK_BASE + "/api/auto-fill/analyze";
  var SERP_EXTENSION_VERSION = "3.2.9";

  // ==================== Service Worker Fetch Proxy ====================
  // Content scripts on some sites can"t directly fetch to localhost due to CSP.
  // Route all requests through the extension"s background service worker.
  function bgFetch(url, options) {
    console.log("[sERP] bgFetch:", (options && options.method) || "GET", url);
    return new Promise(function (resolve, reject) {
      chrome.runtime.sendMessage(
        { type: "fetch", url: url, options: options || {} },
        function (result) {
          if (chrome.runtime.lastError) {
            reject(new Error(chrome.runtime.lastError.message));
            return;
          }
          if (!result) {
            reject(new Error("bgFetch: no response from service worker"));
            return;
          }
          // Build a synthetic Response-like object
          var body = result.body || "";
          resolve({
            ok: result.ok,
            status: result.status,
            statusText: result.statusText,
            json: function () { return Promise.resolve(JSON.parse(body)); },
            text: function () { return Promise.resolve(body); }
          });
        }
      );
    });
  }

  // 带超时的 bgFetch 包装
  function bgFetchWithTimeout(url, options, timeoutMs) {
    timeoutMs = timeoutMs || 150000;  // default 150s
    return Promise.race([
      bgFetch(url, options),
      new Promise(function (_, reject) {
        setTimeout(function () {
          reject(new Error("AI分析超时 (" + Math.round(timeoutMs / 1000) + "s)，请重试"));
        }, timeoutMs);
      })
    ]);
  }

  // 店铺中文名 → store_id 映射
  var STORE_CN_MAP = {
    "安凌": "ozon_anling",
    "anling": "ozon_anling",
    "安美": "ozon_anmei",
    "anmei": "ozon_anmei",
    "安曼": "ozon_anman",
    "anman": "ozon_anman"
  };

  // ==================== 状态 ====================
  var selectedProduct = null;
  var allProducts = [];
  var _fieldMap = {};  // index → {fid, el, selectors, options, tag, label, type}
  var _categoryMatchRunning = false;

  // ==================== CSS 注入 ====================
  var style = document.createElement("style");
  style.textContent = [
    "/* ===== 左侧悬浮工具栏 ===== */",
    "#serp-toolbar{position:fixed;left:8px;top:120px;z-index:999990;display:flex;flex-direction:row;align-items:flex-start;gap:6px;background:#fff;border-radius:10px;padding:8px;box-shadow:0 4px 16px rgba(0,0,0,0.12);font-family:\"Microsoft YaHei\",sans-serif;user-select:none;}",
    "#serp-toolbar .serp-tb-btn{height:48px;min-width:56px;border-radius:8px;border:1px solid #e8e8e8;background:#fff;cursor:pointer;display:flex;flex-direction:column;align-items:center;justify-content:center;transition:all 0.2s;font-size:11px;color:#666;line-height:1.2;gap:2px;padding:0 6px;white-space:nowrap;}",
    "#serp-toolbar .serp-tb-btn:hover{background:#f0f5ff;border-color:#428bca;color:#428bca;}",
    "#serp-toolbar .serp-tb-btn:active{transform:scale(0.95);}",
    "#serp-toolbar .serp-tb-btn.loading{pointer-events:none;opacity:0.6;}",
    "#serp-toolbar .serp-tb-btn .tb-icon{font-size:16px;line-height:1;}",
    "#serp-toolbar .serp-tb-btn .tb-label{font-size:10px;line-height:1;}",
    "#serp-toolbar .serp-tb-btn.has-product{border-color:#52c41a;background:#f6ffed;color:#389e0d;}",
    "/* 产品信息区 — 横向时放在按钮行下方 */",
    "#serp-toolbar .serp-product-info{display:none;position:absolute;top:100%;left:0;margin-top:6px;background:#fff;border-radius:8px;padding:6px 8px;box-shadow:0 2px 8px rgba(0,0,0,0.1);width:150px;}",
    "#serp-toolbar .serp-product-info.visible{display:block;}",
    "#serp-toolbar .serp-product-info .pi-label{font-size:9px;color:#999;margin-bottom:2px;}",
    "#serp-toolbar .serp-product-info .pi-skc{font-size:11px;font-weight:600;color:#428bca;word-break:break-all;}",
    "#serp-toolbar .serp-product-info .pi-title{font-size:10px;color:#666;word-break:break-word;max-height:40px;overflow:hidden;line-height:1.3;margin-top:2px;}",
    "#serp-toolbar .serp-product-info .pi-clear{font-size:10px;color:#ff4d4f;cursor:pointer;margin-top:4px;text-align:center;border:1px solid #ffccc7;border-radius:3px;padding:2px 6px;transition:all 0.2s;}",
    "#serp-toolbar .serp-product-info .pi-clear:hover{background:#fff1f0;}",
    "/* ===== 产品选择弹窗 ===== */",
    "#serp-modal-overlay{display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.5);z-index:1000000;align-items:center;justify-content:center;}",
    "#serp-modal-overlay.active{display:flex;}",
    "#serp-modal{background:#fff;border-radius:12px;width:700px;max-width:90vw;max-height:80vh;display:flex;flex-direction:column;box-shadow:0 20px 60px rgba(0,0,0,0.3);font-family:\"Microsoft YaHei\",sans-serif;}",
    "#serp-modal-header{display:flex;align-items:center;justify-content:space-between;padding:18px 24px;border-bottom:1px solid #e5e7eb;}",
    "#serp-modal-header h3{font-size:18px;color:#333;margin:0;}",
    "#serp-modal-close{background:none;border:none;font-size:22px;cursor:pointer;color:#999;padding:4px 8px;border-radius:4px;transition:all 0.2s;}",
    "#serp-modal-close:hover{background:#f3f4f6;color:#333;}",
    "#serp-modal-search{padding:12px 24px;border-bottom:1px solid #f0f0f0;}",
    "#serp-modal-search input{width:100%;padding:10px 14px;border:1px solid #d1d5db;border-radius:8px;font-size:14px;outline:none;transition:border-color 0.2s;box-sizing:border-box;}",
    "#serp-modal-search input:focus{border-color:#667eea;box-shadow:0 0 0 3px rgba(102,126,234,0.1);}",
    "#serp-modal-list{flex:1;overflow-y:auto;padding:12px 24px;}",
    ".serp-product-item{display:flex;align-items:center;padding:12px 16px;border-radius:8px;cursor:pointer;transition:all 0.2s;margin-bottom:6px;border:1px solid #f0f0f0;}",
    ".serp-product-item:hover{background:#f8f9ff;border-color:#667eea;transform:translateX(2px);}",
    ".serp-product-item.selected{background:#f0f5ff;border-color:#428bca;}",
    ".serp-product-item .skc-badge{font-size:12px;font-weight:bold;color:#667eea;background:#eef0ff;padding:3px 10px;border-radius:4px;margin-right:12px;flex-shrink:0;}",
    ".serp-product-item .product-info{flex:1;min-width:0;}",
    ".serp-product-item .product-title{font-size:14px;color:#333;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}",
    ".serp-product-item .product-meta{font-size:12px;color:#999;margin-top:2px;}",
    ".serp-product-item .product-status{font-size:11px;color:#16a34a;background:#dcfce7;padding:2px 8px;border-radius:4px;flex-shrink:0;}",
    "#serp-modal-empty{text-align:center;padding:40px;color:#aaa;font-size:14px;}",
    "/* ===== Toast ===== */",
    "#serp-toast{position:fixed;top:20px;right:20px;z-index:1000001;padding:12px 24px;border-radius:8px;font-size:14px;font-family:\"Microsoft YaHei\",sans-serif;box-shadow:0 4px 15px rgba(0,0,0,0.15);display:none;max-width:450px;}",
    "#serp-toast.success{background:#dcfce7;color:#16a34a;border:1px solid #bbf7d0;}",
    "#serp-toast.error{background:#fee2e2;color:#dc2626;border:1px solid #fecaca;}",
    "#serp-toast.info{background:#dbeafe;color:#1d4ed8;border:1px solid #bfdbfe;}",
    "/* ===== 进度条 ===== */",
    "#serp-progress-bar{position:fixed;top:0;left:0;height:3px;background:linear-gradient(90deg,#667eea,#764ba2);z-index:1000002;transition:width 0.3s ease;width:0%;}",
    "/* ===== 额外提示词面板（居中弹窗） ===== */",
    "#serp-hint-toggle{font-size:10px;color:#8b8b8b;cursor:pointer;text-align:center;padding:2px 4px;border:1px dashed #d9d9d9;border-radius:4px;transition:all 0.2s;white-space:nowrap;}",
    "#serp-hint-toggle:hover{color:#428bca;border-color:#428bca;}",
    "#serp-hint-toggle.active{color:#428bca;border-color:#428bca;background:#f0f5ff;}",
    "#serp-hint-overlay{display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.5);z-index:1000001;align-items:center;justify-content:center;}",
    "#serp-hint-overlay.active{display:flex;}",
    "#serp-hint-panel{background:#fff;border-radius:12px;width:560px;max-width:90vw;max-height:85vh;overflow-y:auto;padding:20px 24px;box-shadow:0 20px 60px rgba(0,0,0,0.3);font-family:\"Microsoft YaHei\",sans-serif;}",
    "#serp-hint-panel .hint-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;padding-bottom:10px;border-bottom:1px solid #e5e7eb;}",
    "#serp-hint-panel .hint-header .hint-title{font-size:16px;font-weight:600;color:#333;}",
    "#serp-hint-panel .hint-header .hint-close{background:none;border:none;font-size:20px;cursor:pointer;color:#999;padding:0 4px;}",
    "#serp-hint-panel .hint-header .hint-close:hover{color:#333;}",
    "/* ===== Section 卡片 ===== */",
    "#serp-hint-panel .hint-section{border:1px solid #e8e8e8;border-radius:8px;padding:10px 12px;margin-bottom:10px;background:#fafafa;}",
    "#serp-hint-panel .hint-section-header{font-size:12px;font-weight:600;color:#555;margin-bottom:6px;display:flex;align-items:center;gap:6px;}",
    "#serp-hint-panel .hint-section-header .hs-ctx{font-size:10px;color:#999;font-weight:400;}",
    "#serp-hint-panel .hint-section-header .hs-ctx span{color:#428bca;}",
    "#serp-hint-panel .hint-label{font-size:11px;color:#888;margin-bottom:2px;margin-top:6px;}",
    "#serp-hint-panel .hint-label:first-of-type{margin-top:0;}",
    "#serp-hint-panel textarea.serp-hint-input{width:100%;height:50px;border:1px solid #d1d5db;border-radius:6px;font-size:12px;padding:5px 8px;resize:vertical;font-family:\"Microsoft YaHei\",sans-serif;box-sizing:border-box;outline:none;transition:border-color 0.2s;}",
    "#serp-hint-panel textarea.serp-hint-input:focus{border-color:#428bca;box-shadow:0 0 0 3px rgba(66,139,202,0.1);}",
    "/* ===== 保存按钮 ===== */",
    "#serp-hint-panel .hint-save-row{display:flex;justify-content:flex-end;margin-top:6px;}",
    "#serp-hint-panel .hint-save-btn{font-size:11px;padding:3px 12px;border:1px solid #428bca;border-radius:4px;background:#fff;color:#428bca;cursor:pointer;transition:all 0.2s;}",
    "#serp-hint-panel .hint-save-btn:hover{background:#428bca;color:#fff;}",
    "#serp-hint-panel .hint-save-btn.saved{background:#16a34a;color:#fff;border-color:#16a34a;}",
    "/* ===== 填充结果面板 ===== */",
    "#serp-results-panel{position:fixed;left:8px;top:auto;z-index:999989;background:#fff;border-radius:10px;padding:10px 12px;box-shadow:0 4px 16px rgba(0,0,0,0.12);font-family:\"Microsoft YaHei\",sans-serif;font-size:12px;max-width:360px;max-height:400px;overflow-y:auto;display:none;}",
    "#serp-results-panel.visible{display:block;}",
    "#serp-results-panel .sr-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;padding-bottom:6px;border-bottom:1px solid #f0f0f0;}",
    "#serp-results-panel .sr-header .sr-title{font-weight:600;font-size:13px;color:#333;}",
    "#serp-results-panel .sr-header .sr-close{background:none;border:none;font-size:16px;cursor:pointer;color:#999;padding:0 4px;line-height:1;}",
    "#serp-results-panel .sr-header .sr-close:hover{color:#333;}",
    "#serp-results-panel .sr-summary{font-size:11px;color:#666;margin-bottom:6px;line-height:1.5;}",
    "#serp-results-panel .sr-summary .sr-ok{color:#16a34a;font-weight:600;}",
    "#serp-results-panel .sr-summary .sr-fail{color:#dc2626;font-weight:600;}",
    "#serp-results-panel .sr-item{display:flex;align-items:flex-start;gap:6px;padding:3px 0;border-bottom:1px solid #fafafa;font-size:11px;line-height:1.4;}",
    "#serp-results-panel .sr-item .sr-icon{flex-shrink:0;width:16px;text-align:center;}",
    "#serp-results-panel .sr-item .sr-label{color:#666;min-width:60px;max-width:100px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}",
    "#serp-results-panel .sr-item .sr-value{color:#333;word-break:break-all;flex:1;}",
    "/* ===== 提取字段面板 ===== */",
    "#serp-extract-panel{position:fixed;left:8px;top:auto;z-index:999989;background:#fff;border-radius:10px;padding:10px 12px;box-shadow:0 4px 16px rgba(0,0,0,0.12);font-family:\"Microsoft YaHei\",sans-serif;font-size:12px;max-width:400px;max-height:500px;overflow-y:auto;display:none;}",
    "#serp-extract-panel.visible{display:block;}",
    "#serp-extract-panel .ex-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;padding-bottom:6px;border-bottom:1px solid #f0f0f0;}",
    "#serp-extract-panel .ex-header .ex-title{font-weight:600;font-size:13px;color:#333;}",
    "#serp-extract-panel .ex-header .ex-close{background:none;border:none;font-size:16px;cursor:pointer;color:#999;padding:0 4px;line-height:1;}",
    "#serp-extract-panel .ex-header .ex-close:hover{color:#333;}",
    "#serp-extract-panel .ex-summary{font-size:11px;color:#666;margin-bottom:8px;line-height:1.6;}",
    "#serp-extract-panel .ex-summary .ex-count{font-weight:600;}",
    "#serp-extract-panel .ex-section{margin-bottom:8px;}",
    "#serp-extract-panel .ex-section-title{font-size:11px;font-weight:600;color:#555;margin-bottom:3px;padding:2px 6px;background:#f5f5f5;border-radius:3px;}",
    "#serp-extract-panel .ex-item{font-size:11px;color:#333;padding:2px 8px;line-height:1.5;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}",
    "#serp-extract-panel .ex-item .ex-tag{display:inline-block;font-size:9px;padding:0 4px;border-radius:2px;margin-right:4px;flex-shrink:0;line-height:1.5;}",
    "#serp-extract-panel .ex-tag.txt{background:#e6f7ff;color:#1890ff;}",
    "#serp-extract-panel .ex-tag.sel{background:#f6ffed;color:#52c41a;}",
    "#serp-extract-panel .ex-tag.cb{background:#fff7e6;color:#fa8c16;}",
    "#serp-extract-panel .ex-tag.rd{background:#f9f0ff;color:#722ed1;}",
    "#serp-image-picker{position:fixed;left:8px;top:86px;z-index:999990;width:420px;max-height:620px;background:#fff;border-radius:10px;box-shadow:0 8px 28px rgba(0,0,0,0.16);font-family:\"Microsoft YaHei\",sans-serif;font-size:12px;display:none;overflow:hidden;}",
    "#serp-image-picker.visible{display:block;}",
    "#serp-image-picker .ip-header{display:flex;align-items:center;justify-content:space-between;padding:10px 12px;border-bottom:1px solid #eee;}",
    "#serp-image-picker .ip-title{font-size:13px;font-weight:600;color:#333;}",
    "#serp-image-picker .ip-close{border:none;background:transparent;color:#888;font-size:18px;cursor:pointer;line-height:1;}",
    "#serp-image-picker .ip-body{padding:10px 12px;max-height:510px;overflow:auto;}",
    "#serp-image-picker .ip-set{border:1px solid #e5e7eb;border-radius:8px;margin-bottom:10px;padding:8px;background:#fafafa;}",
    "#serp-image-picker .ip-set-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;color:#444;font-weight:600;}",
    "#serp-image-picker .ip-use-set{border:1px solid #428bca;background:#fff;color:#428bca;border-radius:4px;padding:2px 8px;font-size:11px;cursor:pointer;}",
    "#serp-image-picker .ip-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:6px;}",
    "#serp-image-picker .ip-img{position:relative;border:2px solid transparent;border-radius:6px;overflow:hidden;background:#fff;aspect-ratio:1;cursor:pointer;}",
    "#serp-image-picker .ip-img.selected{border-color:#16a34a;}",
    "#serp-image-picker .ip-img img{width:100%;height:100%;object-fit:cover;display:block;}",
    "#serp-image-picker .ip-footer{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:10px 12px;border-top:1px solid #eee;background:#fff;}",
    "#serp-image-picker .ip-copy{border:1px solid #16a34a;background:#16a34a;color:#fff;border-radius:5px;padding:4px 10px;font-size:12px;cursor:pointer;}",
    "#serp-image-picker .ip-empty{color:#888;text-align:center;padding:28px 10px;}",
    "#serp-ext-version{font-size:10px;color:#999;align-self:center;padding:0 2px;writing-mode:vertical-rl;letter-spacing:0;}"
  ].join("\n");
  document.head.appendChild(style);

  // ==================== 构建 DOM ====================

  var toolbar = document.createElement("div");
  toolbar.id = "serp-toolbar";
  toolbar.innerHTML =
    '<button class="serp-tb-btn" id="serp-btn-select" title="选择产品">' +
      '<span class="tb-icon">📦</span><span class="tb-label">选品</span>' +
    '</button>' +
    '<button class="serp-tb-btn" id="serp-btn-category" title="自动匹配品类">' +
      '<span class="tb-icon">🏷️</span><span class="tb-label">自动分类</span>' +
    '</button>' +
    '<button class="serp-tb-btn" id="serp-btn-extract" title="提取页面可填字段">' +
      '<span class="tb-icon">🔍</span><span class="tb-label">提取</span>' +
    '</button>' +
    '<button class="serp-tb-btn" id="serp-btn-fill" title="自动填充表单">' +
      '<span class="tb-icon">✍️</span><span class="tb-label">自动填充</span>' +
    '</button>' +
    '<button class="serp-tb-btn" id="serp-btn-images" title="选择变种图片集或单张图片">' +
      '<span class="tb-icon">图</span><span class="tb-label">变种图</span>' +
    '</button>' +
    '<button class="serp-tb-btn" id="serp-btn-clear-form" title="清空所有表单字段">' +
      '<span class="tb-icon">🧹</span><span class="tb-label">清空</span>' +
    '</button>' +
    '<button class="serp-tb-btn" id="serp-btn-send-html" title="发送当前页面HTML到后台分析">' +
      '<span class="tb-icon">📄</span><span class="tb-label">发送HTML</span>' +
    '</button>' +
    '<div id="serp-ext-version" title="sERP extension version">v' + SERP_EXTENSION_VERSION + '</div>' +
    '<div id="serp-hint-toggle" title="展开设置自定义提示词">💡</div>' +
    '<div class="serp-product-info" id="serp-product-info">' +
      '<div class="pi-label">已选产品</div>' +
      '<div class="pi-skc" id="serp-pi-skc"></div>' +
      '<div class="pi-title" id="serp-pi-title"></div>' +
      '<div class="pi-clear" id="serp-pi-clear">清除</div>' +
    '</div>';
  document.body.appendChild(toolbar);

  var toast = document.createElement("div");
  toast.id = "serp-toast";
  document.body.appendChild(toast);

  var progressBar = document.createElement("div");
  progressBar.id = "serp-progress-bar";
  document.body.appendChild(progressBar);

  var resultsPanel = document.createElement("div");
  resultsPanel.id = "serp-results-panel";
  resultsPanel.innerHTML =
    '<div class="sr-header">' +
      '<span class="sr-title">📋 填充结果</span>' +
      '<button class="sr-close" id="serp-results-close">✕</button>' +
    '</div>' +
    '<div class="sr-summary" id="serp-results-summary"></div>' +
    '<div id="serp-results-list"></div>';
  document.body.appendChild(resultsPanel);

  var extractPanel = document.createElement("div");
  extractPanel.id = "serp-extract-panel";
  extractPanel.innerHTML =
    '<div class="ex-header">' +
      '<span class="ex-title">🔍 提取字段</span>' +
      '<button class="ex-close" id="serp-extract-close">✕</button>' +
    '</div>' +
    '<div class="ex-summary" id="serp-extract-summary"></div>' +
    '<div id="serp-extract-sections"></div>';
  document.body.appendChild(extractPanel);

  var imagePicker = document.createElement("div");
  imagePicker.id = "serp-image-picker";
  imagePicker.innerHTML =
    '<div class="ip-header">' +
      '<span class="ip-title">变种图片选择</span>' +
      '<button class="ip-close" id="serp-image-close">×</button>' +
    '</div>' +
    '<div class="ip-body" id="serp-image-body"></div>' +
    '<div class="ip-footer">' +
      '<span id="serp-image-count">已选 0 张</span>' +
      '<button class="ip-copy" id="serp-image-copy">复制图片URL</button>' +
    '</div>';
  document.body.appendChild(imagePicker);

  var hintOverlay = document.createElement("div");
  hintOverlay.id = "serp-hint-overlay";
  hintOverlay.innerHTML =
    '<div id="serp-hint-panel">' +
      '<div class="hint-header">' +
        '<span class="hint-title">💡 额外提示词</span>' +
        '<button class="hint-close" id="serp-hint-close">✕</button>' +
      '</div>' +
      /* ===== 平台提示词 ===== */
      '<div class="hint-section" id="hint-section-platform">' +
        '<div class="hint-section-header">📋 平台提示词 <span class="hs-ctx">(当前: <span id="hint-ctx-platform">--</span>)</span></div>' +
        '<div class="hint-label">产品标题</div>' +
        '<textarea class="serp-hint-input" id="serp-hint-title" placeholder="标题填充提示..."></textarea>' +
        '<div class="hint-label">产品描述</div>' +
        '<textarea class="serp-hint-input" id="serp-hint-desc" placeholder="描述填充提示..."></textarea>' +
        '<div class="hint-label">JSON富文本</div>' +
        '<textarea class="serp-hint-input" id="serp-hint-json" placeholder="JSON属性填充提示..."></textarea>' +
        '<div class="hint-label">主题标签</div>' +
        '<textarea class="serp-hint-input" id="serp-hint-hashtag" placeholder="主题标签填充提示..."></textarea>' +
        '<div class="hint-label">平台专属提示</div>' +
        '<textarea class="serp-hint-input" id="serp-hint-platform-prompt" placeholder="当前平台的额外填充指引..."></textarea>' +
        '<div class="hint-save-row"><button class="hint-save-btn" data-level="platform">💾 保存</button></div>' +
      '</div>' +
      /* ===== 店铺提示词 ===== */
      '<div class="hint-section" id="hint-section-store">' +
        '<div class="hint-section-header">📋 店铺提示词 <span class="hs-ctx">(当前: <span id="hint-ctx-store">--</span>)</span></div>' +
        '<div class="hint-label">店铺专属提示</div>' +
        '<textarea class="serp-hint-input" id="serp-hint-store-prompt" placeholder="当前店铺的额外填充指引..."></textarea>' +
        '<div class="hint-save-row"><button class="hint-save-btn" data-level="store">💾 保存</button></div>' +
      '</div>' +
      /* ===== 品类提示词 ===== */
      '<div class="hint-section" id="hint-section-category" style="display:none;">' +
        '<div class="hint-section-header">📋 品类提示词 <span class="hs-ctx">(当前: <span id="hint-ctx-category">--</span>)</span></div>' +
        '<div class="hint-label">品类专属提示</div>' +
        '<textarea class="serp-hint-input" id="serp-hint-category-prompt" placeholder="此品类的额外填充指引..."></textarea>' +
        '<div class="hint-save-row"><button class="hint-save-btn" data-level="category">💾 保存</button></div>' +
      '</div>' +
    '</div>';
  document.body.appendChild(hintOverlay);

  var modalOverlay = document.createElement("div");
  modalOverlay.id = "serp-modal-overlay";
  modalOverlay.innerHTML =
    '<div id="serp-modal">' +
      '<div id="serp-modal-header"><h3>📋 选择产品</h3><button id="serp-modal-close">✕</button></div>' +
      '<div id="serp-modal-search"><input type="text" id="serp-search-input" placeholder="搜索产品名称或 SKC 编码..." /></div>' +
      '<div id="serp-modal-list"><div id="serp-modal-empty">正在加载产品列表...</div></div>' +
    '</div>';
  document.body.appendChild(modalOverlay);

  // ==================== DOM 引用 ====================
  var btnSelect = document.getElementById("serp-btn-select");
  var btnCategory = document.getElementById("serp-btn-category");
  var btnExtract = document.getElementById("serp-btn-extract");
  var btnFill = document.getElementById("serp-btn-fill");
  var btnImages = document.getElementById("serp-btn-images");
  var btnSendHtml = document.getElementById("serp-btn-send-html");
  var productInfo = document.getElementById("serp-product-info");
  var piSkc = document.getElementById("serp-pi-skc");
  var piTitle = document.getElementById("serp-pi-title");
  var piClear = document.getElementById("serp-pi-clear");
  var hintToggle = document.getElementById("serp-hint-toggle");
  var hintPanel = document.getElementById("serp-hint-panel");
  var hintTitle = document.getElementById("serp-hint-title");
  var hintDesc = document.getElementById("serp-hint-desc");
  var hintJson = document.getElementById("serp-hint-json");
  var hintHashtag = document.getElementById("serp-hint-hashtag");
  var hintPlatformPrompt = document.getElementById("serp-hint-platform-prompt");
  var hintStorePrompt = document.getElementById("serp-hint-store-prompt");
  var hintCategoryPrompt = document.getElementById("serp-hint-category-prompt");
  var hintCtxPlatform = document.getElementById("hint-ctx-platform");
  var hintCtxStore = document.getElementById("hint-ctx-store");
  var hintCtxCategory = document.getElementById("hint-ctx-category");
  var hintSectionCategory = document.getElementById("hint-section-category");
  var imageBody = document.getElementById("serp-image-body");
  var imageCount = document.getElementById("serp-image-count");
  var imageCopy = document.getElementById("serp-image-copy");
  var selectedImageUrls = {};

  // ==================== 平台检测 ====================
  function detectPlatform() {
    var host = window.location.hostname;
    if (host.indexOf("ozon") !== -1) return "ozon";
    if (host.indexOf("amazon") !== -1) return "amazon";
    if (host.indexOf("1688") !== -1) return "1688";
    if (host.indexOf("wildberries") !== -1) return "wb";
    return null;
  }

  // ==================== 品类检测 ====================
  function detectCategory() {
    var el = document.querySelector(".category-item .ant-select-selection-item");
    if (!el) return null;
    return (el.getAttribute("title") || el.textContent || "").trim() || null;
  }

  // ==================== 提示词持久化（平台/店铺/品类三层） ====================
  function loadAllHints() {
    var platform = detectPlatform();
    var storeId = detectStoreId();
    var category = detectCategory();

    // 更新 section header 中的上下文显示
    hintCtxPlatform.textContent = platform || "未识别";
    hintCtxStore.textContent = storeId || "未识别";
    hintCtxCategory.textContent = category || "未选择";

    // 品类 section 仅在选中店铺+品类时显示
    hintSectionCategory.style.display = (storeId && category) ? "" : "none";

    var keys = [];
    if (platform) keys.push("serp_hint_platform_" + platform);
    if (storeId) {
      keys.push("serp_hint_store_" + storeId);
      if (category) keys.push("serp_hint_category_" + storeId + "_" + category);
    }
    if (!keys.length) return;

    chrome.storage.local.get(keys, function (data) {
      // 平台提示词
      if (platform && data["serp_hint_platform_" + platform]) {
        var pd = data["serp_hint_platform_" + platform];
        hintTitle.value = pd.title || "";
        hintDesc.value = pd.description || "";
        hintJson.value = pd.json_text || "";
        hintHashtag.value = pd.hashtag || "";
        hintPlatformPrompt.value = pd.platform_prompt || "";
      }
      // 店铺提示词
      if (storeId && data["serp_hint_store_" + storeId]) {
        var sd = data["serp_hint_store_" + storeId];
        hintStorePrompt.value = sd.prompt || "";
      } else {
        hintStorePrompt.value = "";
      }
      // 品类提示词
      if (storeId && category && data["serp_hint_category_" + storeId + "_" + category]) {
        var cd = data["serp_hint_category_" + storeId + "_" + category];
        hintCategoryPrompt.value = cd.prompt || "";
      } else {
        hintCategoryPrompt.value = "";
      }
    });
  }

  function saveHints(level) {
    var platform = detectPlatform();
    var storeId = detectStoreId();
    var category = detectCategory();
    var kv = {};
    var key;

    if (level === "platform") {
      if (!platform) { showToast("未识别当前平台，无法保存", "error"); return; }
      key = "serp_hint_platform_" + platform;
      kv[key] = {
        title: hintTitle.value,
        description: hintDesc.value,
        json_text: hintJson.value,
        hashtag: hintHashtag.value,
        platform_prompt: hintPlatformPrompt.value
      };
    } else if (level === "store") {
      if (!storeId) { showToast("未识别当前店铺，无法保存", "error"); return; }
      key = "serp_hint_store_" + storeId;
      kv[key] = { prompt: hintStorePrompt.value };
    } else if (level === "category") {
      if (!storeId || !category) { showToast("请先选择店铺和品类后再保存", "error"); return; }
      key = "serp_hint_category_" + storeId + "_" + category;
      kv[key] = { prompt: hintCategoryPrompt.value };
    }

    chrome.storage.local.set(kv, function () {
      // 保存按钮反馈
      var btn = document.querySelector(".hint-save-btn[data-level=\"" + level + "\"]");
      if (btn) {
        var originalText = btn.textContent;
        btn.textContent = "已保存 ✓";
        btn.classList.add("saved");
        setTimeout(function () {
          btn.textContent = originalText;
          btn.classList.remove("saved");
        }, 1500);
      }
    });
  }

  // ==================== Debug: 发送页面HTML到后台分析 ====================
  function captureAndSendHTML() {
    if (!selectedProduct) {
      showToast("请先选择产品后再发送HTML", "error");
      return;
    }
    setBtnLoading(btnSendHtml, true);

    var html = document.documentElement.outerHTML;
    var fields = typeof collectFormFields === "function" ? collectFormFields() : [];
    var fieldsCount = fields.length;

    // 诊断日志
    console.log("[sERP] captureAndSendHTML: fieldsCount=" + fieldsCount + " url=" + window.location.href);
    if (fieldsCount > 0) {
      var typeCounts = {};
      fields.forEach(function(f) { typeCounts[f.tag] = (typeCounts[f.tag] || 0) + 1; });
      console.log("[sERP] captureAndSendHTML: field types=" + JSON.stringify(typeCounts));
      console.log("[sERP] captureAndSendHTML: field labels=" + JSON.stringify(fields.map(function(f) { return "[" + f.index + "] " + f.tag + " " + f.label; })));
    }

    var payload = {
      html: html,
      url: window.location.href,
      note: "sku=" + (selectedProduct.skc || "") + " title=" + (selectedProduct.title || "").substring(0, 80),
      form_fields_count: fieldsCount
    };

    bgFetch(FLASK_BASE + "/api/debug/capture-html", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    }).then(function (r) {
      setBtnLoading(btnSendHtml, false);
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    }).then(function (data) {
      showToast("HTML已发送: " + (data.file || "ok") + " (" + (data.size || 0) + " bytes)", "info");
      console.log("[sERP] HTML captured:", data.file, "size:", data.size);
    }).catch(function (err) {
      setBtnLoading(btnSendHtml, false);
      showToast("发送失败: " + err.message, "error");
      console.error("[sERP] HTML capture error:", err);
    });
  }

  // ==================== 工具函数 ====================
  function showToast(msg, type) {
    type = type || "info";
    toast.textContent = msg;
    toast.className = type;
    toast.style.display = "block";
    clearTimeout(toast._hideTimer);
    toast._hideTimer = setTimeout(function () { toast.style.display = "none"; }, 4000);
  }

  function setProgress(pct) {
    progressBar.style.width = Math.min(100, Math.max(0, pct)) + "%";
    if (pct >= 100) setTimeout(function () { progressBar.style.width = "0%"; }, 1000);
  }

  function setBtnLoading(btn, loading) {
    if (loading) btn.classList.add("loading"); else btn.classList.remove("loading");
  }

  function sleep(ms) {
    return new Promise(function (resolve) { setTimeout(resolve, ms); });
  }

  function updateProductUI() {
    if (selectedProduct) {
      productInfo.classList.add("visible");
      piSkc.textContent = selectedProduct.skc || "";
      piTitle.textContent = selectedProduct.title || "未命名产品";
      btnSelect.classList.add("has-product");
    } else {
      productInfo.classList.remove("visible");
      piSkc.textContent = "";
      piTitle.textContent = "";
      btnSelect.classList.remove("has-product");
    }
  }

  // ==================== 店铺检测 ====================
  function detectStoreId() {
    // Try multiple selector strategies to find the store name in DOM
    var name = null;
    var storeItems = document.querySelectorAll(".shop-form-item .ant-select-selection-item");
    if (storeItems.length) {
      name = (storeItems[0].getAttribute("title") || storeItems[0].textContent || "").trim();
    }
    // Fallback: broader ant-select-selection-item search
    if (!name) {
      var allSelectionItems = document.querySelectorAll(".ant-select-selection-item");
      for (var i = 0; i < allSelectionItems.length; i++) {
        var t = (allSelectionItems[i].getAttribute("title") || allSelectionItems[i].textContent || "").trim();
        if (t && (t.indexOf("安") !== -1 || t.indexOf("an") !== -1 || t.indexOf("ozon") !== -1 || t.indexOf("Ozon") !== -1)) {
          name = t;
          break;
        }
      }
    }
    // Fallback: URL-based detection
    if (!name) {
      var href = window.location.href;
      var urlM = href.match(/store[=_](\w+)/i) || href.match(/\/([a-z]+_\w+)\//);
      if (urlM) name = urlM[1];
    }
    if (!name) return null;

    for (var key in STORE_CN_MAP) {
      if (STORE_CN_MAP.hasOwnProperty(key) && name.indexOf(key) !== -1) return STORE_CN_MAP[key];
    }
    var lowerName = name.toLowerCase().replace(/\s+/g, "_");
    if (lowerName.indexOf("ozon_") !== -1) return lowerName;
    return null;
  }

  // ==================== 产品 API ====================
  function fetchProducts() {
    console.log("[sERP] 正在请求产品列表:", API_PRODUCTS);
    return bgFetch(API_PRODUCTS)
      .then(function (res) {
        console.log("[sERP] 产品列表响应状态:", res.status);
        if (!res.ok) throw new Error("HTTP " + res.status + " 获取产品列表失败");
        return res.json();
      })
      .then(function (data) {
        var count = (data.products || []).length;
        console.log("[sERP] 产品列表已加载:", count, "个产品");
        return data.products || [];
      })
      .catch(function (e) {
        console.error("[sERP] 产品列表加载失败:", e.message);
        showToast("无法连接到 sERP 后端: " + e.message, "error");
        return [];
      });
  }

  function escapeHtml(s) {
    return String(s || "").replace(/[&<>"']/g, function (ch) {
      return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch];
    });
  }

  function normalizeImageUrl(url) {
    if (!url) return "";
    if (/^https?:\/\//i.test(url)) return url;
    if (url.charAt(0) === "/") return FLASK_BASE + url;
    return FLASK_BASE + "/" + url.replace(/^\/+/, "");
  }

  function updateSelectedImageCount() {
    var count = Object.keys(selectedImageUrls).length;
    imageCount.textContent = "已选 " + count + " 张";
  }

  async function copyTextToClipboard(text) {
    if (navigator.clipboard) {
      try { await navigator.clipboard.writeText(text); return true; } catch (e) {}
    }
    var ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.left = "-9999px";
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    var ok = false;
    try { ok = document.execCommand("copy"); } catch (copyErr) {}
    document.body.removeChild(ta);
    return ok;
  }

  function renderImagePickerSets(imageSets) {
    selectedImageUrls = {};
    updateSelectedImageCount();
    if (!imageSets || !imageSets.length) {
      imageBody.innerHTML = '<div class="ip-empty">当前产品没有可选择的图片集</div>';
      return;
    }
    imageBody.innerHTML = imageSets.map(function (set, setIndex) {
      var imgs = set.images || [];
      var name = set.label || set.name || ("图片集 " + (setIndex + 1));
      return '<div class="ip-set" data-set="' + setIndex + '">' +
        '<div class="ip-set-head"><span>' + escapeHtml(name) + ' (' + imgs.length + ')</span><button class="ip-use-set" data-set="' + setIndex + '">选择本组</button></div>' +
        '<div class="ip-grid">' + imgs.map(function (img, imgIndex) {
          var url = normalizeImageUrl(img.url || img.path || img.file || img.filename || "");
          return '<div class="ip-img" data-url="' + escapeHtml(url) + '" data-set="' + setIndex + '" data-img="' + imgIndex + '">' +
            '<img src="' + escapeHtml(url) + '" loading="lazy">' +
          '</div>';
        }).join("") + '</div>' +
      '</div>';
    }).join("");

    imageBody.querySelectorAll(".ip-img").forEach(function (node) {
      node.addEventListener("click", function () {
        var url = node.dataset.url;
        if (!url) return;
        if (selectedImageUrls[url]) {
          delete selectedImageUrls[url];
          node.classList.remove("selected");
        } else {
          selectedImageUrls[url] = true;
          node.classList.add("selected");
        }
        updateSelectedImageCount();
      });
    });
    imageBody.querySelectorAll(".ip-use-set").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var setId = btn.dataset.set;
        imageBody.querySelectorAll('.ip-img[data-set="' + setId + '"]').forEach(function (node) {
          var url = node.dataset.url;
          if (url) {
            selectedImageUrls[url] = true;
            node.classList.add("selected");
          }
        });
        updateSelectedImageCount();
      });
    });
  }

  async function openImagePicker() {
    if (!selectedProduct || !selectedProduct.skc) {
      showToast("请先选择产品，再选择变种图片", "error");
      return;
    }
    imagePicker.classList.add("visible");
    imageBody.innerHTML = '<div class="ip-empty">正在加载图片...</div>';
    updateSelectedImageCount();
    try {
      var r = await bgFetch(FLASK_BASE + "/api/products/" + encodeURIComponent(selectedProduct.skc) + "/images");
      if (!r.ok) throw new Error("HTTP " + r.status);
      var data = await r.json();
      renderImagePickerSets(data.image_sets || []);
    } catch (e) {
      imageBody.innerHTML = '<div class="ip-empty">图片加载失败：' + escapeHtml(e.message) + '</div>';
      showToast("图片加载失败: " + e.message, "error");
    }
  }

  // ==================== 产品选择弹窗 ====================
  function renderProductList(products) {
    var listEl = document.getElementById("serp-modal-list");
    if (products.length === 0) { listEl.innerHTML = '<div id="serp-modal-empty">没有找到匹配的产品</div>'; return; }
    listEl.innerHTML = products.map(function (p) {
      var cls = "serp-product-item" + (selectedProduct && selectedProduct.skc === p.skc ? " selected" : "");
      return '<div class="' + cls + '" data-skc="' + (p.skc || "") + '">' +
        '<span class="skc-badge">' + (p.skc || "—") + '</span>' +
        '<div class="product-info">' +
          '<div class="product-title">' + (p.title || "未命名产品") + '</div>' +
          '<div class="product-meta">' + (p.category || "其他") + " · " + (p.platform || "未知平台") + (p.price ? " · " + p.price : "") + '</div>' +
        '</div>' +
        '<span class="product-status">' + (p.store_status ? Object.values(p.store_status).filter(function (s) { return s === "已上架"; }).length + " 店已上架" : "") + '</span>' +
      '</div>';
    }).join("");
    listEl.querySelectorAll(".serp-product-item").forEach(function (item) {
      item.addEventListener("click", function () {
        var p = allProducts.find(function (x) { return x.skc === item.dataset.skc; });
        if (p) { selectedProduct = p; updateProductUI(); modalOverlay.classList.remove("active"); showToast("已选择产品: " + (p.skc || ""), "success"); }
      });
    });
  }

  // ==================== 平台检测 ====================
  function detectPlatform() {
    // 从 store_id 前缀检测平台：ozon_anling → ozon, wb_xxx → wb
    var storeId = detectStoreId();
    if (!storeId) return null;
    var parts = storeId.split("_");
    return parts[0] || null;
  }

  // ==================== 智能分类 ====================
  // 通用入口：检测平台 → 调用后端匹配 → 分派平台策略填充
  function doMatchCategory() {
    if (_categoryMatchRunning) {
      showToast("正在匹配品类，请稍候...", "info");
      return;
    }
    if (!selectedProduct) { showToast("请先点击\"选品\"选择一个产品", "error"); return; }
    var storeId = detectStoreId();
    if (!storeId) { showToast("无法识别当前店铺", "error"); return; }
    var platform = detectPlatform();
    if (!platform) { showToast("无法识别当前平台", "error"); return; }

    _categoryMatchRunning = true;
    setBtnLoading(btnCategory, true);
    showToast("正在匹配品类...", "info");

    var prodData = selectedProduct.product_data || {};
    var desc = (prodData.about_item || "") + " " + (prodData.product_description || "");
    return bgFetch(FLASK_BASE + "/api/" + platform + "/" + storeId + "/match-category", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ product_title: selectedProduct.title || "", product_category: selectedProduct.category || "", product_description: desc.trim() })
    })
    .then(function (r) { return r.json(); })
    .then(function (data) {
      if (!data.success || !data.best_match || !data.best_match.id) { showToast("品类匹配失败: " + (data.error || data.warning || "无匹配结果"), "error"); return; }
      var m = data.best_match;
      showToast("已匹配品类: " + (m.path || m.name) + " (ID: " + m.id + ")", "success");
      // 分派到平台策略
      return fillCategorySelect(m, platform);
    })
    .catch(function (e) { console.error("[sERP] 品类匹配异常:", e); showToast("品类匹配失败: " + e.message, "error"); })
    .then(function () { _categoryMatchRunning = false; setBtnLoading(btnCategory, false); });
  }

  // ===== 平台策略分发 =====
  function fillCategorySelect(matched, platform) {
    if (!platform) platform = detectPlatform();
    switch (platform) {
      case "ozon": return fillCategorySelect_ozon(matched);
      // 后续平台在这里加 case: case "wb": return fillCategorySelect_wb(matched);
      default:
        showToast("平台 \"" + platform + "\" 的品类选择尚未支持", "error");
        return Promise.resolve();
    }
  }

  // 等待元素出现（轮询，超时返回 null）
  function waitFor(selector, timeoutMs, root) {
    root = root || document;
    var deadline = Date.now() + (timeoutMs || 3000);
    return new Promise(function (resolve) {
      function check() {
        var el = root.querySelector(selector);
        if (el) { resolve(el); return; }
        if (Date.now() > deadline) { resolve(null); return; }
        setTimeout(check, 150);
      }
      check();
    });
  }

  // 等待下拉选项出现
  function waitForDropdownOptions(timeoutMs) {
    var deadline = Date.now() + (timeoutMs || 5000);
    return new Promise(function (resolve) {
      function check() {
        var dd = document.querySelector(".ant-select-dropdown:not(.ant-select-dropdown-hidden)");
        if (dd) {
          var opts = dd.querySelectorAll(".ant-select-item-option");
          if (opts.length > 0) { resolve({ dropdown: dd, options: opts }); return; }
        }
        if (Date.now() > deadline) { resolve(null); return; }
        setTimeout(check, 200);
      }
      check();
    });
  }

  // ===== 分类弹窗 Modal 导航帮助函数 =====

  // 等待分类弹窗出现
  function waitForCategoryModal(timeoutMs) {
    var deadline = Date.now() + (timeoutMs || 8000);
    return new Promise(function (resolve) {
      function check() {
        var modal = document.querySelector(".ant-modal");
        // 弹窗必须可见（offsetParent !== null 表示非 display:none）
        if (modal && modal.offsetParent !== null) { resolve(modal); return; }
        if (Date.now() > deadline) { resolve(null); return; }
        setTimeout(check, 200);
      }
      check();
    });
  }

  // 等待第 N 列出现（0-indexed）
  function waitForCategoryColumn(columnIndex, timeoutMs) {
    var deadline = Date.now() + (timeoutMs || 8000);
    return new Promise(function (resolve) {
      function check() {
        var boxes = document.querySelectorAll(".categories-box");
        if (boxes.length > columnIndex) {
          var col = boxes[columnIndex];
          // 列容器出现还不够，需要等待列表项渲染完毕
          if (col.querySelectorAll(".categories-item").length > 0) {
            resolve(col);
            return;
          }
        }
        if (Date.now() > deadline) { resolve(null); return; }
        setTimeout(check, 200);
      }
      check();
    });
  }

  // 在列中查找匹配项（按 title 属性精确匹配俄语名）
  function findCategoryInColumn(column, ruName) {
    var items = column.querySelectorAll(".categories-item");
    var best = null;

    // Pass 1: 精确匹配（最高优先级）
    for (var i = 0; i < items.length; i++) {
      var titleEl = items[i].querySelector(".categories-item-name");
      var title = titleEl ? (titleEl.getAttribute("title") || "").trim() : "";
      if (title === ruName) { return items[i]; }
    }

    // Pass 2: 包含匹配 — 取最短标题（最接近精确匹配）
    for (var j = 0; j < items.length; j++) {
      var titleEl2 = items[j].querySelector(".categories-item-name");
      var title2 = titleEl2 ? (titleEl2.getAttribute("title") || "").trim() : "";
      if (title2.indexOf(ruName) !== -1) {
        if (!best || title2.length < (best._matchTitle || "").length) {
          best = items[j];
          best._matchTitle = title2;
        }
      }
    }

    // Pass 3: 反向包含匹配
    if (!best) {
      for (var k = 0; k < items.length; k++) {
        var titleEl3 = items[k].querySelector(".categories-item-name");
        var title3 = titleEl3 ? (titleEl3.getAttribute("title") || "").trim() : "";
        if (ruName.indexOf(title3) !== -1 && title3.length > 0) {
          if (!best || title3.length > (best._matchTitle || "").length) {
            best = items[k];
            best._matchTitle = title3;
          }
        }
      }
    }

    // Pass 4: textContent 模糊匹配
    if (!best) {
      for (var m = 0; m < items.length; m++) {
        var txt = items[m].textContent.trim();
        if (txt.indexOf(ruName) !== -1) { best = items[m]; break; }
      }
    }

    return best;
  }

  // ===== 旧的帮助函数保留 =====
  // 帮助函数：从下拉选项中找匹配项
  function findOptionByLevelName(options, levelName) {
    // levelName 格式: "Russian（Chinese）" 或纯 "Russian"
    var cnMatch = levelName.match(/（(.+?)）$/);
    var ruName = cnMatch ? levelName.substring(0, levelName.lastIndexOf("（")).trim().toLowerCase() : levelName.toLowerCase();
    var cnName = cnMatch ? cnMatch[1].trim().toLowerCase() : "";

    console.log("[sERP] findOption: ru=" + ruName + " cn=" + cnName + " 在 " + options.length + " 个选项中");

    var best = null;

    // 策略A: 精确匹配俄语名（去除括号内容）
    for (var i = 0; i < options.length; i++) {
      var txt = (options[i].textContent || "").trim();
      var txtRu = txt.replace(/（.+?）$/, "").trim().toLowerCase();
      if (txtRu === ruName) { best = options[i]; break; }
    }

    // 策略B: 俄语名包含匹配
    if (!best) {
      for (var i = 0; i < options.length; i++) {
        var txt = (options[i].textContent || "").toLowerCase();
        if (txt.indexOf(ruName) !== -1) { best = options[i]; break; }
      }
    }

    // 策略C: 中文名匹配
    if (!best && cnName) {
      for (var i = 0; i < options.length; i++) {
        var txt = (options[i].textContent || "").toLowerCase();
        if (txt.indexOf(cnName) !== -1) { best = options[i]; break; }
      }
    }

    // 策略D: 模糊匹配（匹配前几个字符）
    if (!best && ruName.length > 3) {
      var shortRu = ruName.substring(0, 5);
      for (var i = 0; i < options.length; i++) {
        var txt = (options[i].textContent || "").toLowerCase();
        if (txt.indexOf(shortRu) !== -1) { best = options[i]; break; }
      }
    }

    if (best) console.log("[sERP] findOption 匹配到:", best.textContent.trim().substring(0, 60));
    else console.log("[sERP] findOption 未匹配到任何选项");
    return best;
  }

  // ================================================================
  //  Ozon 平台策略：Modal 弹窗 + 多列级联面板
  // ================================================================
  var _fillCategoryRunning = false;

  function fillCategorySelect_ozon(matched, _isInternal) {
    if (!_isInternal && _fillCategoryRunning) {
      console.log("[sERP] fillCategorySelect 已在执行中，跳过重复调用");
      return Promise.resolve();
    }
    if (!_isInternal) {
        _fillCategoryRunning = true;
        setTimeout(function() {
            if (_fillCategoryRunning) {
                console.warn("[sERP] fillCategorySelect lock safety-timeout triggered after 30s");
                _fillCategoryRunning = false;
            }
        }, 30000);
    }

    // 解析路径
    var pathNames = [];
    if (matched.node_path_names && matched.node_path_names.length > 0) {
      pathNames = matched.node_path_names;
    } else if (matched.path) {
      pathNames = matched.path.split(" > ").filter(function (s) { return s.trim(); });
    } else {
      pathNames = [matched.name || ""];
    }

    console.log("[sERP] fillCategorySelect: pathNames =", pathNames);
    console.log("[sERP] fillCategorySelect: matched.id =", matched.id, "| type_id =", matched.type_id);

    // Step 1: 点击"选择分类"按钮打开弹窗
    var openBtn = document.querySelector(".category-item .ant-btn-primary");
    if (!openBtn) {
      if (!_isInternal) _fillCategoryRunning = false;
      showToast("未找到\"选择分类\"按钮", "error");
      return Promise.resolve();
    }

    // 如果弹窗已打开（可见状态），先关闭再重新开始
    var existingModal = document.querySelector(".ant-modal");
    if (existingModal && existingModal.offsetParent !== null) {
      console.log("[sERP] 弹窗已打开，先关闭...");
      var closeX = existingModal.querySelector(".ant-modal-close");
      if (closeX) closeX.click();
      // 等待弹窗真正关闭（隐藏或从 DOM 移除）
      return new Promise(function (resolve) {
        var deadline = Date.now() + 3000;
        function checkHidden() {
          var m = document.querySelector(".ant-modal");
          if (!m || m.offsetParent === null) {
            resolve(fillCategorySelect_ozon(matched, true));
            return;
          }
          if (Date.now() > deadline) {
            console.log("[sERP] 弹窗关闭超时，继续执行");
            resolve(fillCategorySelect_ozon(matched, true));
            return;
          }
          setTimeout(checkHidden, 150);
        }
        checkHidden();
      });
    }

    console.log("[sERP] 点击\"选择分类\"按钮...");
    openBtn.click();

    // Step 2: 等待弹窗出现
    return waitForCategoryModal(8000).then(function (modal) {
      if (!modal) {
        if (!_isInternal) _fillCategoryRunning = false;
        showToast("分类弹窗未出现", "error");
        return;
      }
      console.log("[sERP] 分类弹窗已打开");

      // Step 2.5: 确保"初始类目"模式 + 清空搜索框（搜索会破坏列级联视图）
      var modeSelectItem = modal.querySelector(".modal-body-header .ant-select-selection-item");
      var modeText = modeSelectItem ? modeSelectItem.textContent.trim() : "";
      var searchInput = modal.querySelector("input[name='searchCategory']");
      var searchVal = searchInput ? searchInput.value : "";

      if (searchVal) {
        console.log("[sERP] 清空搜索框:", searchVal);
        var ns = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
        ns.call(searchInput, "");
        searchInput.dispatchEvent(new Event("input", { bubbles: true }));
      }

      if (modeText !== "初始类目") {
        console.log("[sERP] 切换到初始类目模式，当前:", modeText);
        var selInput = modal.querySelector(".modal-body-header .ant-select input");
        if (selInput) {
          selInput.focus();
          selInput.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", code: "Enter", keyCode: 13, bubbles: true }));
          var dd = document.querySelector(".ant-select-dropdown:not(.ant-select-dropdown-hidden)");
          if (dd) {
            var opts = dd.querySelectorAll(".ant-select-item-option");
            for (var oi = 0; oi < opts.length; oi++) {
              if (opts[oi].textContent.trim() === "初始类目") {
                opts[oi].click();
                break;
              }
            }
          }
        }
      }

      // Step 3: 逐层导航列
      function navigateColumn(idx) {
        if (idx >= pathNames.length) {
          // 所有层级选完 → 点击"选择"确认
          console.log("[sERP] 所有层级已导航完毕，点击\"选择\"确认...");
          var confirmBtns = document.querySelectorAll(".ant-modal .ant-btn-primary");
          for (var k = 0; k < confirmBtns.length; k++) {
            if (confirmBtns[k].textContent.trim() === "选择") {
              confirmBtns[k].click();
              break;
            }
          }
          // 关闭弹窗并验证
          return sleep(500).then(function () {
            var xBtn = document.querySelector(".ant-modal-close");
            if (xBtn) xBtn.click();
            return sleep(400);
          }).then(function () {
            var catItem = document.querySelector(".category-item .ant-select-selection-item");
            var newVal = catItem ? (catItem.getAttribute("title") || catItem.textContent || "").trim() : "";
            console.log("[sERP] 最终品类值:", newVal);
            if (newVal && newVal.length > 0) {
              showToast("品类已自动选中: " + newVal, "success");
            } else {
              showToast("品类可能未正确选中，当前值: " + (newVal || "空"), "error");
            }
          });
        }

        var levelName = pathNames[idx];
        // 从 "Russian（Chinese）" 提取俄语名
        var ruName = levelName.replace(/（.+?）$/, "").trim();
        console.log("[sERP] ====== 导航第 " + (idx + 1) + "/" + pathNames.length + " 层: " + ruName + " ======");

        // 等待这一列出现
        return waitForCategoryColumn(idx, 8000).then(function (column) {
          if (!column) {
            showToast("第" + (idx + 1) + "层分类列未出现，请手动选择", "error");
            if (!_isInternal) _fillCategoryRunning = false;
            return;
          }

          var items = column.querySelectorAll(".categories-item");
          console.log("[sERP] 第" + (idx + 1) + "层: " + items.length + " 个选项");

          // 打印前 3 个帮助调试
          for (var j = 0; j < Math.min(3, items.length); j++) {
            var tEl = items[j].querySelector(".categories-item-name");
            console.log("[sERP]   选项[" + j + "]: " + (tEl ? tEl.getAttribute("title") : items[j].textContent.trim().substring(0, 40)));
          }

          // 在当前列中匹配
          var bestItem = findCategoryInColumn(column, ruName);

          if (!bestItem) {
            // 打印所有标题帮助调试
            var allTitles = [];
            for (var j = 0; j < items.length; j++) {
              var tEl = items[j].querySelector(".categories-item-name");
              allTitles.push(tEl ? tEl.getAttribute("title") : items[j].textContent.trim().substring(0, 40));
            }
            console.log("[sERP] 匹配失败，可用标题:", JSON.stringify(allTitles));
            console.log("[sERP] 查找目标:", JSON.stringify(ruName));
            showToast("未找到品类 \"" + ruName + "\"，请手动选择", "error");
            if (!_isInternal) _fillCategoryRunning = false;
            return;
          }

          console.log("[sERP] 点击:", ruName);
          bestItem.scrollIntoView({ block: "nearest" });
          bestItem.click();

          return sleep(600).then(function () {
            return navigateColumn(idx + 1);
          });
        });
      }

      return navigateColumn(0);
    }).then(function () {
      if (!_isInternal) _fillCategoryRunning = false;
    }).catch(function (e) {
      if (!_isInternal) _fillCategoryRunning = false;
      console.error("[sERP] fillCategorySelect 异常:", e);
    });
  }

  // ==================== 智能填充 ====================
  function findLabel(el, skipWrapper) {
    if (el.id) { var lb = document.querySelector('label[for="' + el.id + '"]'); if (lb) return lb.textContent.trim(); }
    if (!skipWrapper) {
      var p = el.parentElement;
      while (p) { if (p.tagName === "LABEL") return p.textContent.trim(); var prev = p.previousElementSibling; if (prev && prev.tagName === "LABEL") return prev.textContent.trim(); p = p.parentElement; }
    }
    p = el.closest(".ant-form-item, .el-form-item, .form-group, .vxe-form-item");
    if (p) {
      // 优先取 ant-form-item-label > label 的纯文本（排除 required 星号等装饰元素）
      var labelCol = p.querySelector(".ant-form-item-label, .el-form-item__label");
      if (labelCol) {
        var labelEl = labelCol.querySelector("label");
        if (labelEl) {
          var txt = (labelEl.textContent || "").replace(/[\s*:：]+$/g, "").trim();
          if (txt) return txt;
        }
      }
      var le = p.querySelector("label");
      if (le) return le.textContent.trim();
    }
    var tableHeader = getTableHeaderLabel(el);
    if (tableHeader) return tableHeader;
    // 回退：Dianxiaomi checkbox-group-with-search — 向上查找 checkbox-wrapper 的兄弟 label
    var cw = el.closest(".checkbox-wrapper, .checkbox-group-with-search");
    if (cw) {
      var cwParent = cw.parentElement;
      while (cwParent && !cwParent.matches(".ant-form-item, .ant-col")) {
        cwParent = cwParent.parentElement;
      }
      if (cwParent) {
        var prevSib = cwParent.previousElementSibling;
        if (prevSib) {
          var prevLabel = prevSib.querySelector("label") || prevSib;
          var prevTxt = (prevLabel.textContent || "").replace(/[\s*:：]+$/g, "").trim();
          if (prevTxt) return prevTxt;
        }
      }
    }
    return "";
  }

  var _serpFidCounter = 0;
  function buildSelector(el) {
    if (el.id) {
      var idSel = "#" + CSS.escape(el.id);
      return document.querySelectorAll(idSel).length === 1 ? idSel : _serpFidSelector(el);
    }
    if (el.name) {
      var nameSel = el.tagName.toLowerCase() + '[name="' + el.name + '"]';
      return document.querySelectorAll(nameSel).length === 1 ? nameSel : _serpFidSelector(el);
    }
    var cls = Array.from(el.classList).filter(function (c) { return !c.startsWith("ant-") && !c.startsWith("el-") && !c.startsWith("vxe-") && !c.startsWith("css-"); });
    if (cls.length) {
      var clsSel = el.tagName.toLowerCase() + "." + cls.map(function (c) { return CSS.escape(c); }).join(".");
      if (document.querySelectorAll(clsSel).length === 1) return clsSel;
      return _serpFidSelector(el);
    }
    if (el.placeholder) {
      var phSel = el.tagName.toLowerCase() + '[placeholder="' + el.placeholder + '"]';
      return document.querySelectorAll(phSel).length === 1 ? phSel : _serpFidSelector(el);
    }
    if (el.title) {
      var tiSel = el.tagName.toLowerCase() + '[title="' + el.title + '"]';
      return document.querySelectorAll(tiSel).length === 1 ? tiSel : _serpFidSelector(el);
    }
    return _serpFidSelector(el);
  }
  function _serpFidSelector(el) {
    if (!el.hasAttribute("data-serp-fid")) {
      _serpFidCounter++;
      el.setAttribute("data-serp-fid", "f" + _serpFidCounter);
    }
    return '[data-serp-fid="' + el.getAttribute("data-serp-fid") + '"]';
  }

  function isVisibleField(el) {
    if (el.closest("#serp-toolbar, #serp-modal-overlay, #serp-hint-overlay, #serp-results-panel, #serp-extract-panel")) return false;
    // 过滤下拉弹出层内的元素（不属于表单本身）
    if (el.closest(".ant-select-dropdown")) return false;
    if (el.closest(".ant-dropdown")) return false;
    if (el.closest(".ant-picker-dropdown")) return false;
    if (el.closest(".ant-tooltip")) return false;
    if (el.closest(".ant-popover")) return false;
    // 过滤隐藏弹窗内的元素
    var modal = el.closest(".ant-modal");
    if (modal && modal.offsetParent === null) return false;
    // 主检查：offsetParent 不为 null → 可见
    if (el.offsetParent !== null) return true;
    // 回退：CSS containment / fixed positioning 可能导致 offsetParent 为 null，
    // 但元素实际可见。用 bounding rect 做二次校验
    try {
      var rect = el.getBoundingClientRect();
      if (rect.width > 0 && rect.height > 0) return true;
    } catch (e) {}
    return false;
  }

  function getTableHeaderLabel(el) {
    var row = el.closest("tr");
    var cell = el.closest("td, th");
    var table = el.closest("table");
    if (!row || !cell || !table) return "";

    var cells = Array.from(row.children).filter(function (c) {
      return c.tagName === "TD" || c.tagName === "TH";
    });
    var idx = cells.indexOf(cell);
    if (idx < 0) return "";

    var headers = Array.from(table.querySelectorAll("thead th"));
    if (!headers[idx]) return "";
    return (headers[idx].textContent || "")
      .replace(/一键生成|高级|批量/g, "")
      .replace(/[()（）·]/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  // 跳过这些已经由其他按钮专门处理的字段，避免二次填充
  function isSkippedField(label) {
    var kw = (label || "").toLowerCase().replace(/\s+/g, "");
    return kw.indexOf("店铺") !== -1
        || kw.indexOf("分类") !== -1
        || kw.indexOf("品类") !== -1
        || kw.indexOf("类目") !== -1;
  }

  function fieldBaseLabel(label) {
    return (label || "")
      .replace(/\s*\[[^\]]+\]\s*$/g, "")
      .replace(/\s*\((?:可选值|选项):[\s\S]*$/g, "")
      .replace(/\s+/g, " ")
      .trim();
  }

  function isDictionarySearchInput(el) {
    if (!el) return false;
    if (el.classList.contains("ant-select-selection-search-input")) return true;
    if ((el.placeholder || "").trim() === "搜索") return true;
    var item = el.closest(".ant-form-item");
    var txt = item ? (item.textContent || "") : "";
    return txt.indexOf("更多属性值请搜索添加") !== -1;
  }

  // 获取字段所在表格行的上下文（用于区分多个SKU行中的同名字段）
  function getRowContext(el) {
    var row = el.closest(".ant-table-row, tr[class*=\"ant-table\"], .skuData-body tr, table.myj-table tbody tr, tr");
    if (!row) return null;

    // Strategy 1: Look for variant name column — short text cell, often the 1st or 2nd column
    var cells = row.querySelectorAll("td");
    for (var i = 0; i < Math.min(cells.length, 4); i++) {
      var txt = (cells[i].textContent || "").replace(/[\s​]+/g, " ").trim();
      // Variant name is typically short (1-40 chars), non-numeric, and not a button cluster
      if (txt && txt.length >= 1 && txt.length <= 40 && !/^\d/.test(txt) && !/^(复制|删除|移除|操作)/.test(txt)) {
        return txt;
      }
    }

    // Strategy 2: Look for ant-select with variant value
    var antSelects = row.querySelectorAll(".ant-select-selection-item");
    for (var j = 0; j < antSelects.length; j++) {
      var stxt = (antSelects[j].textContent || "").trim();
      if (stxt && stxt.length < 40 && !/^(请选择|Выбрать)/i.test(stxt)) return stxt;
    }

    // Strategy 3: first-child fallback with generous length limit
    var nameCell = row.querySelector("td:first-child, th:first-child");
    if (nameCell) {
      var ftxt = (nameCell.textContent || "").replace(/[\s​]+/g, " ").trim();
      if (ftxt && ftxt.length < 60) return ftxt;
    }

    // Strategy 4: row text (compact)
    var rowText = (row.textContent || "").replace(/[\s​]+/g, " ").trim();
    if (rowText && rowText.length < 80) return rowText;
    return null;
  }

  function countSkuRows() {
    var rows = document.querySelectorAll(".ant-table-tbody tr.ant-table-row, .skuData-body tr, table.myj-table tbody tr");
    var count = 0;
    rows.forEach(function(r) {
      if (r.querySelector("input, .ant-select")) count++;
    });
    return count;
  }

  async function clickAddVariantButton() {
    // Strategy 1: Look for button text "添加变种" / "添加规格" / "+"
    var buttons = document.querySelectorAll("button, .ant-btn, a");
    for (var i = 0; i < buttons.length; i++) {
      var txt = (buttons[i].textContent || "").trim();
      if (txt.indexOf("添加变种") !== -1 || txt.indexOf("添加规格") !== -1 || txt === "+") {
        buttons[i].click();
        await sleep(500);
        return true;
      }
    }
    // Strategy 2: Look for icon buttons near SKU table
    var skuTable = document.querySelector(".ant-table");
    if (skuTable) {
      var iconBtns = skuTable.querySelectorAll(".anticon-plus, [class*='add-variant'], [class*='add-sku']");
      for (var j = 0; j < iconBtns.length; j++) {
        iconBtns[j].click();
        await sleep(500);
        return true;
      }
    }
    console.warn("[sERP] 未找到添加变种按钮");
    return false;
  }

  async function ensureSkuRows(neededCount) {
    var existing = countSkuRows();
    if (existing >= neededCount) {
      console.log("[sERP] SKU行数充足: 现有" + existing + " >= 需要" + neededCount);
      return true;
    }
    console.log("[sERP] SKU行数不足: 现有" + existing + " < 需要" + neededCount + "，开始创建...");
    var rowsToAdd = neededCount - existing;
    var added = 0;
    for (var i = 0; i < rowsToAdd; i++) {
      var clicked = await clickAddVariantButton();
      if (!clicked) break;
      added++;
    }
    if (added > 0) {
      console.log("[sERP] 已添加 " + added + " 个SKU行");
      await sleep(500);
    }
    return added === rowsToAdd;
  }

  function findVisibleContainerByText(patterns, selectors) {
    selectors = selectors || [".ant-form-item", ".ant-card", ".ant-collapse-item", ".ant-row", "section", "div"];
    var nodes = Array.from(document.querySelectorAll(selectors.join(","))).filter(function (node) {
      return node && (node.offsetWidth || node.offsetHeight || node.getClientRects().length);
    });
    for (var i = 0; i < nodes.length; i++) {
      var txt = (nodes[i].textContent || "").replace(/\s+/g, " ").trim();
      if (!txt) continue;
      for (var j = 0; j < patterns.length; j++) {
        if (patterns[j].test(txt)) return nodes[i];
      }
    }
    return null;
  }

  async function ensureVariantThemeSelected(variantValues) {
    if (!variantValues || variantValues.length < 2) return true;
    var themeBlock = findVisibleContainerByText([/变种主题|规格主题|variant theme|variation theme|тема/i]);
    if (!themeBlock) {
      console.warn("[sERP] variant theme block not found");
      return false;
    }
    var preferred = ["颜色", "Color", "colour", "Цвет", "цвет товара"];
    var antSelect = themeBlock.querySelector(".ant-select");
    if (antSelect) {
      for (var i = 0; i < preferred.length; i++) {
        if (await fillAntSelect(antSelect, preferred[i], "variant theme")) {
          await sleep(500);
          return true;
        }
      }
    }
    var nativeSelect = themeBlock.querySelector("select");
    if (nativeSelect) {
      var opts = Array.from(nativeSelect.options);
      var match = opts.find(function (o) { return /颜色|color|colour|цвет/i.test(o.textContent || o.value || ""); });
      if (match) {
        nativeSelect.value = match.value;
        nativeSelect.dispatchEvent(new Event("change", { bubbles: true }));
        await sleep(500);
        return true;
      }
    }
    var input = themeBlock.querySelector("input:not([type]), input[type='text']");
    if (input) {
      input.focus();
      input.select();
      try { document.execCommand("insertText", false, "颜色"); } catch (e) {
        var ns = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
        ns.call(input, "颜色");
      }
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
      await sleep(500);
      return true;
    }
    return false;
  }

  async function clickCreateVariantRowsButton() {
    var scope = findVisibleContainerByText([/变种属性|规格属性|variant/i], [".ant-card", ".ant-collapse-item", "section", "div"]) || document;
    var buttons = Array.from(scope.querySelectorAll("button, .ant-btn, a")).filter(function (btn) {
      return btn && (btn.offsetWidth || btn.offsetHeight || btn.getClientRects().length);
    });
    for (var i = 0; i < buttons.length; i++) {
      var txt = (buttons[i].textContent || "").replace(/\s+/g, " ").trim();
      if (/创建|生成|添加|确认|应用|Create|Generate|Add/i.test(txt) && /变种|规格|SKU|variant/i.test((scope.textContent || "") + " " + txt)) {
        buttons[i].click();
        await sleep(800);
        return true;
      }
    }
    return false;
  }

  async function ensureVariantRowsForProduct(variantValues) {
    if (!variantValues || variantValues.length < 2) return true;
    var themeOk = await ensureVariantThemeSelected(variantValues);
    if (themeOk) await clickCreateVariantRowsButton();
    var rowsOk = await ensureSkuRows(variantValues.length);
    if (!themeOk && !rowsOk) {
      showToast("未能自动创建变种行，请先在“变种主题”选择颜色后重试", "error");
    }
    return rowsOk;
  }

  function getProductVariantValues(productData) {
    var result = [];
    var seen = {};
    function add(name, price, attrs) {
      name = String(name || "").trim();
      if (!name || seen[name]) return;
      seen[name] = true;
      result.push({ name: name, variantName: name, price: price || "", attributes: attrs || {} });
    }
    var pd = productData || {};
    var variants = pd.variants || {};
    if (Array.isArray(variants.values)) {
      variants.values.forEach(function (v) {
        if (typeof v === "string") add(v);
        else add(v.name || v.variantName || v.value, v.price, v.attributes || {});
      });
    }
    ["colors", "sizes", "styles", "skus"].forEach(function (key) {
      if (Array.isArray(variants[key])) {
        variants[key].forEach(function (v) {
          if (typeof v === "string") add(v);
          else add(v.name || v.variantName || v.value, v.price, v.attributes || {});
        });
      }
    });
    if (Array.isArray(pd.variantData)) {
      pd.variantData.forEach(function (v) {
        if (v && typeof v === "object") add(v.variantName || v.currentVariant, v.price, v.variantInfo || {});
      });
    }
    return result;
  }

  function collectFormFields() {
    var fields = [];
    var seenSelectors = {};
    var groupedBaseLabels = {};

    // ===== 第一遍：收集 checkbox/radio，按 form-item 分组 =====
    // { groupKey: { groupLabel, rowCtx, items: [{selector, optionLabel}] } }
    var checkboxGroups = {};
    var radioGroups = {};
    var loneCheckboxes = [];  // 无 groupLabel 或单选项的独立 checkbox
    var loneRadios = [];

    document.querySelectorAll('input[type="checkbox"], input[type="radio"]').forEach(function (el) {
      if (!isVisibleField(el)) return;
      var groupLabel = findLabel(el, true);  // form-item 标签（如"材料"）
      if (isSkippedField(groupLabel)) return;
      var optionLabel = findLabel(el);       // 单个选项的文本（如"天然皮革"）
      if (!optionLabel) optionLabel = (el.parentElement ? el.parentElement.textContent : "").trim();
      var sel = _serpFidSelector(el);       // 内部使用 data-serp-fid
      var rowCtx = getRowContext(el);

      // 无有效 groupLabel 的，作为独立字段收集（如 SKU 表格工具栏按钮）
      if (!groupLabel || !groupLabel.trim()) {
        var soloLabel = optionLabel + (rowCtx ? " [" + rowCtx + "]" : "");
        if (/^(设置sku标题|颜色样本|条形码)$/.test(fieldBaseLabel(soloLabel))) return;
        if (el.type === "checkbox") {
          loneCheckboxes.push({ _fid: sel, label: soloLabel, el: el, selector: sel });
        } else {
          loneRadios.push({ _fid: sel, label: soloLabel, el: el, selector: sel });
        }
        return;
      }

      var groupKey = (groupLabel + "|" + (rowCtx || "")).replace(/\(.+?\)/g, "").trim();
      if (el.type === "checkbox") {
        if (!checkboxGroups[groupKey]) checkboxGroups[groupKey] = { groupLabel: groupLabel, rowCtx: rowCtx, items: [] };
        checkboxGroups[groupKey].items.push({ _fid: sel, optionLabel: optionLabel, el: el });
      } else {
        if (!radioGroups[groupKey]) radioGroups[groupKey] = { groupLabel: groupLabel, rowCtx: rowCtx, items: [] };
        radioGroups[groupKey].items.push({ _fid: sel, optionLabel: optionLabel, el: el });
      }
    });

    // 独立 checkbox（无 group 或仅单个）：作为普通 input 字段
    loneCheckboxes.forEach(function (item) {
      if (seenSelectors[item._fid]) return;
      seenSelectors[item._fid] = true;
      fields.push({ tag: "input", type: "checkbox", label: item.label, currentValue: item.el.checked ? "true" : "", _fid: item._fid, el: item.el });
    });

    // 独立 radio（无 group 或仅单个）
    loneRadios.forEach(function (item) {
      if (seenSelectors[item._fid]) return;
      seenSelectors[item._fid] = true;
      fields.push({ tag: "input", type: "radio", label: item.label, currentValue: item.el.checked ? "true" : "", _fid: item._fid, el: item.el });
    });

    // checkbox 组：≥2 个选项才用组格式；单个的回退为普通 checkbox
    Object.keys(checkboxGroups).forEach(function (key) {
      var grp = checkboxGroups[key];
      if (grp.items.length < 2) {
        // 单选项：按普通 checkbox 收集
        var single = grp.items[0];
        if (!seenSelectors[single._fid]) {
          seenSelectors[single._fid] = true;
          var sLabel = grp.groupLabel + " - " + single.optionLabel + (grp.rowCtx ? " [" + grp.rowCtx + "]" : "");
          fields.push({ tag: "input", type: "checkbox", label: sLabel, currentValue: single.el.checked ? "true" : "", _fid: single._fid, el: single.el });
        }
        return;
      }
      groupedBaseLabels[fieldBaseLabel(grp.groupLabel)] = true;
      var optionLabels = grp.items.map(function (x) { return x.optionLabel; });
      var fids = grp.items.map(function (x) { return x._fid; });
      var els = grp.items.map(function (x) { return x.el; });
      var currentChecks = grp.items.filter(function (x) { return x.el.checked; }).map(function (x) { return x.optionLabel; });
      var rowCtx = grp.rowCtx || "";
      var fullLabel = grp.groupLabel
        + (rowCtx ? " [" + rowCtx + "]" : "")
        + " (可选值: " + optionLabels.join(" / ") + ")";
      fields.push({
        tag: "checkbox-group",
        type: "checkbox",
        label: fullLabel,
        currentValue: currentChecks.join(", "),
        _fid: fids[0],
        _fids: fids,
        _els: els,
        options: grp.items.map(function (x, i) { return { text: x.optionLabel, _fid: fids[i] }; })
      });
    });

    // radio 组：≥2 个选项才用组格式
    Object.keys(radioGroups).forEach(function (key) {
      var grp = radioGroups[key];
      if (grp.items.length < 2) {
        var single = grp.items[0];
        if (!seenSelectors[single._fid]) {
          seenSelectors[single._fid] = true;
          var sLabel = grp.groupLabel + " - " + single.optionLabel + (grp.rowCtx ? " [" + grp.rowCtx + "]" : "");
          fields.push({ tag: "input", type: "radio", label: sLabel, currentValue: single.el.checked ? "true" : "", _fid: single._fid, el: single.el });
        }
        return;
      }
      groupedBaseLabels[fieldBaseLabel(grp.groupLabel)] = true;
      var optionLabels = grp.items.map(function (x) { return x.optionLabel; });
      var fids = grp.items.map(function (x) { return x._fid; });
      var els = grp.items.map(function (x) { return x.el; });
      var rowCtx = grp.rowCtx || "";
      var fullLabel = grp.groupLabel
        + (rowCtx ? " [" + rowCtx + "]" : "")
        + " (选项: " + optionLabels.join(" / ") + ")";
      fields.push({
        tag: "radio-group",
        type: "radio",
        label: fullLabel,
        currentValue: "",
        _fid: fids[0],
        _fids: fids,
        _els: els,
        options: grp.items.map(function (x, i) { return { text: x.optionLabel, _fid: fids[i] }; })
      });
    });

    // ===== 第二遍：其他 input（排除 checkbox/radio） =====
    document.querySelectorAll('input:not([type="hidden"]):not([type="file"]):not([type="checkbox"]):not([type="radio"])').forEach(function (el) {
      if (!isVisibleField(el)) return;
      if (isDictionarySearchInput(el)) return;
      var fid = _serpFidSelector(el);
      var label = findLabel(el);
      if (isSkippedField(label)) return;
      var rowCtx = getRowContext(el);
      var extra = el.placeholder && el.placeholder !== "请输入" ? " " + el.placeholder : "";
      var fullLabel = label + extra + (rowCtx ? " [" + rowCtx + "]" : "");
      if (seenSelectors[fid]) return;
      seenSelectors[fid] = true;

      // 检测 AntSelect：.ant-select 包裹的 input，排除 dropdown 内的搜索框
      var antSelect = el.closest(".ant-select");
      if (antSelect && !el.closest(".ant-select-dropdown")) {
        if (groupedBaseLabels[fieldBaseLabel(label)]) return;
        if (fieldBaseLabel(label).indexOf("JSON富文本") !== -1) return;
        var selectMode = antSelect.classList.contains("ant-select-multiple") ? "multiple" : "single";
        var showSearch = antSelect.classList.contains("ant-select-show-search");
        var currentVal = "";
        var selItem = antSelect.querySelector(".ant-select-selection-item");
        if (selItem) currentVal = (selItem.textContent || "").trim();
        fields.push({
          tag: "select",
          renderMode: "AntSelect",
          type: "select",
          label: fullLabel,
          selectMode: selectMode,
          showSearch: showSearch,
          currentValue: currentVal,
          _el: antSelect,
          _fid: _serpFidSelector(antSelect),
          options: []
        });
        return;
      }

      fields.push({ tag: "input", type: el.type || "text", name: el.name || "", id: el.id || "", label: fullLabel, placeholder: el.placeholder || "", currentValue: el.value || "", _fid: fid, el: el });
    });

    // ===== select / textarea =====
    document.querySelectorAll("select").forEach(function (el) {
      if (!isVisibleField(el)) return;
      var fid = _serpFidSelector(el);
      var label = findLabel(el);
      if (isSkippedField(label)) return;
      var rowCtx = getRowContext(el);
      var fullLabel = label + (rowCtx ? " [" + rowCtx + "]" : "");
      fields.push({ tag: "select", name: el.name || "", id: el.id || "", label: fullLabel, currentValue: el.value || "", options: Array.from(el.options).map(function (o) { return { value: o.value, text: o.text }; }), _fid: fid, el: el });
    });
    document.querySelectorAll("textarea").forEach(function (el) {
      if (!isVisibleField(el)) return;
      var fid = _serpFidSelector(el);
      var label = findLabel(el);
      if (isSkippedField(label)) return;
      var rowCtx = getRowContext(el);
      var fullLabel = label + (rowCtx ? " [" + rowCtx + "]" : "");
      fields.push({ tag: "textarea", name: el.name || "", id: el.id || "", label: fullLabel, placeholder: el.placeholder || "", currentValue: el.value || "", _fid: fid, el: el });
    });

    var jsonBtn = Array.from(document.querySelectorAll("button")).find(function (btn) {
      return (btn.textContent || "").trim() === "编辑JSON代码" && isVisibleField(btn);
    });
    if (jsonBtn) {
      var jsonFid = _serpFidSelector(jsonBtn);
      fields.push({
        tag: "json-editor",
        type: "json",
        label: "JSON富文本",
        currentValue: "",
        _fid: jsonFid,
        _el: jsonBtn
      });
    }

    // ===== 构建索引和字段映射表 =====
    _buildFieldMap(fields);

    // 诊断日志：汇总各类字段采集数量
    var stats = { input: 0, select: 0, textarea: 0, "checkbox-group": 0, "radio-group": 0, "lone-checkbox": 0, "lone-radio": 0 };
    fields.forEach(function (f) {
      if (f.tag === "checkbox-group" || f.tag === "radio-group") stats[f.tag] = (stats[f.tag] || 0) + 1;
      else if (f.type === "checkbox") stats["lone-checkbox"]++;
      else if (f.type === "radio") stats["lone-radio"]++;
      else stats[f.tag] = (stats[f.tag] || 0) + 1;
    });
    console.log("[sERP] collectFormFields: total=" + fields.length +
      " input=" + (stats.input || 0) + " select=" + (stats.select || 0) +
      " textarea=" + (stats.textarea || 0) +
      " checkbox-group=" + (stats["checkbox-group"] || 0) +
      " radio-group=" + (stats["radio-group"] || 0) +
      " lone-cb=" + (stats["lone-checkbox"] || 0) +
      " lone-rd=" + (stats["lone-radio"] || 0));

    return fields;
  }

  function _buildFieldMap(fields) {
    _fieldMap = {};
    fields.forEach(function (f, idx) {
      f.index = idx;
      _fieldMap[idx] = {
        fid: f._fid,
        el: f._el || f.el,
        els: f._els || null,
        fids: f._fids || null,
        options: f.options || null,
        tag: f.tag,
        label: f.label,
        type: f.type,
        renderMode: f.renderMode || null,
        jsonEditor: f.tag === "json-editor"
      };
    });
  }

  /** 按索引解析字段 — 优先直接 DOM 引用，失效时回退到 data-serp-fid */
  function resolveFieldByIndex(index) {
    var entry = _fieldMap[index];
    if (!entry) return null;
    // 优先用持有的 DOM 引用
    if (entry.el && entry.el.isConnected) return entry;
    // 回退到 data-serp-fid 查询
    if (entry.fid) {
      var el = document.querySelector(entry.fid);
      if (el) { entry.el = el; return entry; }
    }
    // 回退到 fids 数组恢复
    if (entry.fids && entry.fids.length > 0) {
      var els = [];
      var allFound = true;
      for (var i = 0; i < entry.fids.length; i++) {
        var el_i = document.querySelector(entry.fids[i]);
        if (el_i) { els.push(el_i); } else { allFound = false; break; }
      }
      if (allFound && els.length > 0) {
        entry.els = els;
        entry.el = els[0];
        return entry;
      }
    }
    return null;
  }

  function waitForDropdown(timeoutMs) {
    var deadline = Date.now() + (timeoutMs || 500);
    return new Promise(function (resolve) {
      function check() {
        var dd = document.querySelector(".ant-select-dropdown:not(.ant-select-dropdown-hidden)");
        if (dd) { resolve(dd); return; }
        if (Date.now() > deadline) { resolve(null); return; }
        setTimeout(check, 50);
      }
      check();
    });
  }

  async function fillAntSelect(container, value, label) {
    var selector = container.querySelector(".ant-select-selector");
    if (!selector) { console.warn("[sERP] 未找到 AntSelect selector"); return false; }

    var searchInput = container.querySelector(".ant-select-selection-search-input");
    var maxRetries = 2;
    for (var attempt = 0; attempt <= maxRetries; attempt++) {
        // 关闭任何残留的下拉（避免前一个字段的下拉被误认为当前字段的）
        var staleDropdown = document.querySelector(".ant-select-dropdown:not(.ant-select-dropdown-hidden)");
        if (staleDropdown && !container.contains(staleDropdown)) {
            document.body.click();
            await sleep(200);
        }
        if (!container.classList.contains("ant-select-open")) {
            selector.click();
            await sleep(150);
        }
        if (searchInput && container.classList.contains("ant-select-show-search")) {
            if (document.activeElement !== searchInput) {
                searchInput.focus();
            }
            var ns = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
            ns.call(searchInput, value);
            searchInput.dispatchEvent(new Event("input", { bubbles: true }));
        }
        var dropdown = await waitForDropdown(800);
        if (dropdown) {
            // 匹配选项：精确文本 → 标准化 → 子串
            var items = dropdown.querySelectorAll(".ant-select-item-option:not(.ant-select-item-option-disabled)");
            var vNorm = (value || "").toLowerCase().replace(/\s+/g, " ").trim();
            var matched = null;

            items.forEach(function (item) {
              if (matched) return;
              if (item.textContent.trim() === value) matched = item;
            });
            if (!matched) {
              items.forEach(function (item) {
                if (matched) return;
                var n = item.textContent.toLowerCase().replace(/\s+/g, " ").trim();
                if (n === vNorm) matched = item;
              });
            }
            if (!matched) {
              items.forEach(function (item) {
                if (matched) return;
                var n = item.textContent.toLowerCase().replace(/\s+/g, " ").trim();
                if (n.indexOf(vNorm) !== -1 || vNorm.indexOf(n) !== -1) matched = item;
              });
            }

            if (matched) {
              matched.click();
              return true;
            }

            // 匹配失败：输出可用选项便于排查
            var available = [];
            items.forEach(function (item) { available.push(item.textContent.trim()); });
            console.warn("[sERP] AntSelect 选项未匹配: label=" + (label || "?") + " value=" + value + " vNorm=" + vNorm + " available=" + JSON.stringify(available));
            break;
        }
        if (attempt < maxRetries) {
            console.warn("[sERP] AntSelect 下拉未出现，重试 " + (attempt + 1) + "/" + maxRetries + ": value=" + value);
            if (container.classList.contains("ant-select-open")) {
                document.body.click();
                await sleep(300);
            }
        }
    }
    return false;
  }

  async function fillFormField(index, value) {
    if (!value && value !== 0) return false;
    value = String(value);
    try {
      var entry = resolveFieldByIndex(index);
      if (!entry) { console.warn("[sERP] 解析字段失败: index=" + index); return false; }
      var el = entry.el;
      if (!el) return false;
      var tag = el.tagName.toLowerCase();
      var isCheckboxGroup = (entry.tag === "checkbox-group" && entry.els && entry.els.length > 1);
      var isRadioGroup = (entry.tag === "radio-group" && entry.els && entry.els.length > 1);

      function trigger(el, eventName) {
        el.dispatchEvent(new Event(eventName, { bubbles: true }));
      }

      function norm(s) {
        return (s || "").toLowerCase().replace(/\s+/g, " ").replace(/[()（）]/g, "").trim();
      }

      // 带词边界的 indexOf：避免 "3 个卡槽" 误匹配 "13 个卡槽"
      function indexOfWord(haystack, needle) {
        var idx = haystack.indexOf(needle);
        if (idx === -1) return -1;
        if (idx > 0 && /[\w]/.test(haystack.charAt(idx - 1))) return -1;
        var endIdx = idx + needle.length;
        if (endIdx < haystack.length && /[\w]/.test(haystack.charAt(endIdx))) return -1;
        return idx;
      }

      if (entry.jsonEditor) {
        el.click();
        await sleep(700);
        var dialogs = Array.from(document.querySelectorAll(".ant-modal, .ant-drawer, [role='dialog']")).filter(function (d) {
          return d.offsetWidth || d.offsetHeight || d.getClientRects().length;
        });
        var dialog = dialogs.find(function (d) { return (d.textContent || "").indexOf("JSON") !== -1; }) || dialogs[dialogs.length - 1];
        if (!dialog) { console.warn("[sERP] JSON编辑弹窗未出现"); return false; }

        var wroteJson = false;
        var classicCm = dialog.querySelector(".CodeMirror");
        if (classicCm && classicCm.CodeMirror && typeof classicCm.CodeMirror.setValue === "function") {
          classicCm.CodeMirror.setValue(value);
          if (typeof classicCm.CodeMirror.refresh === "function") classicCm.CodeMirror.refresh();
          wroteJson = true;
        }

        function writeToTextTarget(target) {
          if (!target) return false;
          target.focus();
          if (typeof target.select === "function") target.select();
          try { document.execCommand("selectAll"); } catch (e0) {}
          var inserted = false;
          try { inserted = document.execCommand("insertText", false, value); } catch (e1) {}
          if (!inserted) {
            if (target.tagName === "TEXTAREA") {
              var jts = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value").set;
              jts.call(target, value);
            } else if (target.tagName === "INPUT") {
              var jis = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
              jis.call(target, value);
            } else {
              target.textContent = value;
            }
          }
          trigger(target, "input");
          trigger(target, "change");
          target.dispatchEvent(new KeyboardEvent("keyup", { bubbles: true }));
          return true;
        }

        if (!wroteJson) {
          var ta = dialog.querySelector("textarea");
          var editable = dialog.querySelector("[contenteditable='true'], .cm-content, .cm-line, .monaco-editor textarea.inputarea");
          wroteJson = writeToTextTarget(ta) || writeToTextTarget(editable);
        }
        if (!wroteJson && navigator.clipboard) {
          try {
            await navigator.clipboard.writeText(value);
            var focusable = dialog.querySelector(".cm-content, [contenteditable='true'], textarea, .monaco-editor textarea.inputarea");
            if (focusable) {
              focusable.focus();
              try { document.execCommand("selectAll"); document.execCommand("paste"); } catch (pasteErr) {}
              wroteJson = true;
            }
          } catch (clipErr) {}
        }
        if (!wroteJson) {
          console.warn("[sERP] JSON editor target not found");
          return false;
        }

        var okBtn = Array.from(dialog.querySelectorAll("button")).find(function (btn) {
          var t = (btn.textContent || "").trim();
          return /^(确定|保存|确认|应用|完成|提交|OK|Save|Apply)$/i.test(t) || /保存|确定|确认|应用|完成|提交/i.test(t);
        });
        if (okBtn) {
          okBtn.click();
          await sleep(500);
        }
        return true;
      }

      // ===== checkbox 组填充 =====
      if (isCheckboxGroup) {
        var vals = value.split(/[,，、/|]/).map(function (s) { return norm(s); }).filter(function (s) { return s.length > 0; });
        if (vals.length === 0) vals = [norm(value)];
        var anyChecked = false;

        console.log("[sERP] checkbox-group fill: index=" + index + " label=" + entry.label + " value=" + value + " vals=" + JSON.stringify(vals));

        entry.els.forEach(function (cb, i) {
          if (!cb || !cb.isConnected) {
            cb = document.querySelector(entry.fids[i]);
            if (cb) entry.els[i] = cb; else return;
          }
          var optText = (entry.options && entry.options[i]) ? entry.options[i].text : "";
          var optNorm = norm(optText);
          var matched = vals.some(function (v) {
            return indexOfWord(optNorm, v) !== -1 || indexOfWord(v, optNorm) !== -1;
          });
          if (!matched) {
            // CJK-prefix fallback: 只比较中文/数字前缀，避免 substring(0,3) 过度匹配
            // 例: "3 个卡槽3 отделения..." vs "3 个钞票隔间3 отделения..." → 中文不同 → 不匹配
            matched = vals.some(function (v2) {
              function cjkCore(s) {
                var m = s.match(/^([\d\s一-鿿㐀-䶿（）()，,、.-]+)/);
                return m ? m[1].replace(/\s+/g, " ").trim() : "";
              }
              var vCjk = cjkCore(v2);
              var oCjk = cjkCore(optNorm);
              if (vCjk.length >= 2 && oCjk.length >= 2) {
                return vCjk === oCjk || indexOfWord(oCjk, vCjk) !== -1 || indexOfWord(vCjk, oCjk) !== -1;
              }
              return false;
            });
          }
          console.log("[sERP]   cb[" + i + "] optText=" + optText + " optNorm=" + optNorm + " matched=" + matched);
          if (matched) {
            cb.checked = true;
            trigger(cb, "change");
            anyChecked = true;
          }
        });

        if (!anyChecked) {
          console.log("[sERP] checkbox-group: no match, trying boolean fallback, value=" + value);
          var boolCheck = (value === "true" || value === "1" || value === "yes");
          if (boolCheck && entry.els.length > 0) {
            var firstCb = entry.els[0];
            if (firstCb && firstCb.isConnected) { firstCb.checked = true; trigger(firstCb, "change"); anyChecked = true; }
          }
        }
        console.log("[sERP] checkbox-group result: anyChecked=" + anyChecked);
        return anyChecked;
      }

      // ===== radio 组填充 =====
      if (isRadioGroup) {
        var vNormRd = norm(value);
        var anySelected = false;

        console.log("[sERP] radio-group fill: index=" + index + " label=" + entry.label + " value=" + value + " vNormRd=" + vNormRd);

        entry.els.forEach(function (rb, i) {
          if (!rb || !rb.isConnected) {
            rb = document.querySelector(entry.fids[i]);
            if (rb) entry.els[i] = rb; else return;
          }
          var optText = (entry.options && entry.options[i]) ? entry.options[i].text : "";
          var optNorm = norm(optText);
          var matched = (indexOfWord(optNorm, vNormRd) !== -1 || indexOfWord(vNormRd, optNorm) !== -1);
          console.log("[sERP]   rb[" + i + "] optText=" + optText + " optNorm=" + optNorm + " matched=" + matched);
          if (matched) {
            rb.checked = true;
            trigger(rb, "change");
            anySelected = true;
          }
        });
        console.log("[sERP] radio-group result: anySelected=" + anySelected);
        return anySelected;
      }

      // JSON 编辑器开关
      if (tag === "textarea" || el.type === "textarea" || el.classList.contains("CodeMirror")) {
        var formItem = el.closest(".ant-form-item");
        var jsonToggle = (formItem || document).querySelector(".ant-switch, [class*='json-toggle'], [class*='code-toggle']");
        if (!jsonToggle) {
          var allSwitches = document.querySelectorAll(".ant-switch");
          for (var si = 0; si < allSwitches.length; si++) {
            var swLabel = allSwitches[si].closest(".ant-form-item");
            if (swLabel && swLabel.textContent.indexOf("JSON") !== -1) { jsonToggle = allSwitches[si]; break; }
          }
        }
        if (jsonToggle && !jsonToggle.classList.contains("ant-switch-checked")) {
          jsonToggle.click();
        }
      }

      // ===== 普通 input（text/number 等） =====
      if (tag === "input") {
        if (el.type === "checkbox" || el.type === "radio") {
          var boolVal = (value === "true" || value === "1" || value === "yes");
          if (boolVal || value === "false" || value === "0" || value === "no") {
            el.checked = boolVal;
            trigger(el, "change");
            console.log("[sERP] single " + el.type + " boolean: index=" + index + " label=" + entry.label + " value=" + value + " checked=" + boolVal);
            return true;
          }
          // 修正运算符优先级：|| 优先级高于 ?:，必须加括号确保 findLabel 为空时走 parentElement.textContent 回退
          var cbOptLabel = norm(findLabel(el) || (el.parentElement ? el.parentElement.textContent : ""));
          var cbFormLabel = norm(findLabel(el, true) || "");
          var vLower = norm(value);
          el.checked = (cbOptLabel.indexOf(vLower) !== -1 || vLower.indexOf(cbOptLabel) !== -1 || cbFormLabel.indexOf(vLower) !== -1 || vLower.indexOf(cbFormLabel) !== -1);
          trigger(el, "change");
          console.log("[sERP] single " + el.type + " text-match: index=" + index + " label=" + entry.label + " value=" + value + " vLower=" + vLower + " cbOptLabel=" + cbOptLabel + " cbFormLabel=" + cbFormLabel + " checked=" + el.checked);
          return true;
        }
        // 键盘驱动输入：先聚焦清空，再 insertText
        el.focus();
        el.select();
        try { document.execCommand("selectAll"); } catch (e) {}
        try { document.execCommand("insertText", false, value); } catch (e) {
          // fallback: 原生 setter + 事件
          var ns = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
          ns.call(el, value);
        }
        trigger(el, "input");
        trigger(el, "change");
        return true;
      }

      // AntSelect 填充（renderMode 存储在 _buildFieldMap 中）
      if (entry.renderMode === "AntSelect") {
        return await fillAntSelect(el, value, entry.label);
      }

      // ===== select =====
      if (tag === "select") {
        var opts = Array.from(el.options), matched = false;
        el.focus();

        var exact = opts.find(function (o) { return o.value === value; });
        if (exact) { el.value = value; matched = true; }

        if (!matched) {
          var textExact = opts.find(function (o) { return norm(o.text) === norm(value); });
          if (textExact) { el.value = textExact.value; matched = true; }
        }

        if (!matched) {
          var vNorm = norm(value);
          var fuzzy = opts.find(function (o) {
            var oNorm = norm(o.text);
            return oNorm.indexOf(vNorm) !== -1 || vNorm.indexOf(oNorm) !== -1;
          });
          if (fuzzy) { el.value = fuzzy.value; matched = true; }
        }

        if (!matched && value.length >= 3) {
          var prefix = norm(value).substring(0, 3);
          var kwMatch = opts.find(function (o) { return norm(o.text).indexOf(prefix) !== -1; });
          if (kwMatch) { el.value = kwMatch.value; matched = true; }
        }

        if (!matched) {
          var numVal = parseFloat(value);
          if (!isNaN(numVal)) {
            var numMatch = opts.find(function (o) {
              var oNum = parseFloat(o.text);
              return !isNaN(oNum) && Math.abs(oNum - numVal) < 0.01;
            });
            if (numMatch) { el.value = numMatch.value; matched = true; }
          }
        }

        if (matched) { trigger(el, "change"); trigger(el, "input"); }
        return matched;
      }

      // ===== textarea =====
      if (tag === "textarea") {
        el.focus();
        el.select();
        try { document.execCommand("selectAll"); } catch (e) {}
        try { document.execCommand("insertText", false, value); } catch (e) {
          var ts = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value").set;
          ts.call(el, value);
        }
        trigger(el, "input");
        trigger(el, "change");
        return true;
      }

      if (el.isContentEditable) {
        el.focus();
        el.textContent = value;
        trigger(el, "input");
        return true;
      }
      return false;
    } catch (e) { console.warn("[sERP] 填充失败: index=" + index, e); return false; }
  }

  function collectCustomPrompts() {
    // 直接从 chrome.storage 读取，不依赖 DOM 状态（面板可能未打开）
    var platform = detectPlatform();
    var storeId = detectStoreId();
    var category = detectCategory();

    console.log("[sERP] collectCustomPrompts: platform=" + platform + " store=" + storeId + " category=" + category);

    var keys = [];
    if (platform) keys.push("serp_hint_platform_" + platform);
    if (storeId) {
      keys.push("serp_hint_store_" + storeId);
      if (category) keys.push("serp_hint_category_" + storeId + "_" + category);
    }
    if (!keys.length) { console.log("[sERP] collectCustomPrompts: no keys to read, returning empty"); return Promise.resolve({}); }

    return new Promise(function (resolve) {
      chrome.storage.local.get(keys, function (data) {
        var prompts = {};
        if (platform && data["serp_hint_platform_" + platform]) {
          var pd = data["serp_hint_platform_" + platform];
          if (pd.title) prompts.title = pd.title;
          if (pd.description) prompts.description = pd.description;
          if (pd.json_text) prompts.json_text = pd.json_text;
          if (pd.hashtag) prompts.hashtag = pd.hashtag;
          if (pd.platform_prompt) prompts.platform = pd.platform_prompt;
        }
        if (storeId && data["serp_hint_store_" + storeId]) {
          var sd = data["serp_hint_store_" + storeId];
          if (sd.prompt) prompts.store = sd.prompt;
        }
        if (storeId && category && data["serp_hint_category_" + storeId + "_" + category]) {
          var cd = data["serp_hint_category_" + storeId + "_" + category];
          if (cd.prompt) prompts.category = cd.prompt;
        }
        console.log("[sERP] collectCustomPrompts: resolved keys=" + keys.join(",") + " prompts=" + JSON.stringify(Object.keys(prompts)));
        resolve(prompts);
      });
    });
  }

  function positionResultsPanel() {
    var tbRect = toolbar.getBoundingClientRect();
    var top = tbRect.bottom + 8;
    // 如果产品信息区已展开，放到它下面
    if (productInfo.classList.contains("visible")) {
      var piRect = productInfo.getBoundingClientRect();
      top = piRect.bottom + 8;
    }
    resultsPanel.style.top = top + "px";
    resultsPanel.style.left = "8px";
  }

  function renderFillResults(allResults, totalFields) {
    var filled = 0, failed = 0;
    allResults.forEach(function (r) { if (r.filled) filled++; else failed++; });

    var summary = document.getElementById("serp-results-summary");
    summary.innerHTML =
      "表单共 <b>" + totalFields + "</b> 个字段，" +
      "LLM 匹配 <b>" + allResults.length + "</b> 个映射：" +
      "<span class=\"sr-ok\">" + filled + " 成功</span>，" +
      "<span class=\"sr-fail\">" + failed + " 未填充</span>";

    var listEl = document.getElementById("serp-results-list");
    listEl.innerHTML = allResults.map(function (r) {
      var icon = r.filled ? "✅" : "❌";
      var label = r.label || ("字段 " + r.index) || "(未知)";
      return '<div class="sr-item">' +
        '<span class="sr-icon">' + icon + '</span>' +
        '<span class="sr-label" title="字段 #' + (r.index != null ? r.index : "") + '">' + label + '</span>' +
        '<span class="sr-value">' + (r.filled ? (r.value || "") : (r.error || "LLM 未匹配此字段")) + '</span>' +
      '</div>';
    }).join("");

    positionResultsPanel();
    resultsPanel.classList.add("visible");
  }

  function doExtractFields() {
    resultsPanel.classList.remove("visible");
    var formFields = collectFormFields();
    if (!formFields.length) { showToast("未找到可填充的表单字段", "error"); return; }

    // 分类统计
    var txtFields = [], selFields = [], cbFields = [], rdFields = [];
    formFields.forEach(function (f) {
      if (f.tag === "checkbox-group") cbFields.push(f);
      else if (f.tag === "radio-group") rdFields.push(f);
      else if (f.tag === "select") selFields.push(f);
      else txtFields.push(f);
    });

    // 摘要
    var summary = document.getElementById("serp-extract-summary");
    var parts = [];
    if (txtFields.length) parts.push('<span class="ex-count" style="color:#1890ff">' + txtFields.length + '</span> 文本输入');
    if (selFields.length) parts.push('<span class="ex-count" style="color:#52c41a">' + selFields.length + '</span> 下拉选择');
    if (cbFields.length) parts.push('<span class="ex-count" style="color:#fa8c16">' + cbFields.length + '</span> 多选组');
    if (rdFields.length) parts.push('<span class="ex-count" style="color:#722ed1">' + rdFields.length + '</span> 单选组');
    summary.innerHTML = '共 <b>' + formFields.length + '</b> 个字段：' + parts.join(' &nbsp;|&nbsp; ');

    // 详情列表
    var sections = document.getElementById("serp-extract-sections");
    var html = "";

    function renderSection(title, fields, tagClass, showOptions) {
      if (!fields.length) return "";
      var s = '<div class="ex-section"><div class="ex-section-title">' + title + ' (' + fields.length + ')</div>';
      fields.forEach(function (f) {
        var label = f.label || f.name || f.placeholder || "(无标签)";
        s += '<div class="ex-item"><span class="ex-tag ' + tagClass + '">' + title.charAt(0) + '</span>' + label + '</div>';
      });
      s += '</div>';
      return s;
    }

    html += renderSection("文本输入", txtFields, "txt");
    html += renderSection("下拉选择", selFields, "sel");
    html += renderSection("多选组", cbFields, "cb");
    html += renderSection("单选组", rdFields, "rd");

    sections.innerHTML = html;

    // 定位面板
    var tbRect = toolbar.getBoundingClientRect();
    var top = tbRect.bottom + 8;
    if (productInfo.classList.contains("visible")) {
      top = productInfo.getBoundingClientRect().bottom + 8;
    }
    extractPanel.style.top = top + "px";
    extractPanel.style.left = "8px";
    extractPanel.classList.add("visible");

    showToast("已提取 " + formFields.length + " 个字段", "info");
  }

  function clearAllFormFields() {
    var cleared = 0;

    // Text/number inputs
    document.querySelectorAll('input[type="text"], input[type="number"], input:not([type])').forEach(function (el) {
      if (!el.offsetParent) return;
      var ns = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
      ns.call(el, "");
      el.dispatchEvent(new Event("input", { bubbles: true }));
      cleared++;
    });

    // Checkboxes & radios
    document.querySelectorAll('input[type="checkbox"], input[type="radio"]').forEach(function (el) {
      if (!el.offsetParent) return;
      if (el.checked) {
        el.checked = false;
        el.dispatchEvent(new Event("change", { bubbles: true }));
        cleared++;
      }
    });

    // Textareas
    document.querySelectorAll("textarea").forEach(function (el) {
      if (!el.offsetParent) return;
      var ns = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value").set;
      ns.call(el, "");
      el.dispatchEvent(new Event("input", { bubbles: true }));
      cleared++;
    });

    // AntSelect clear icons
    document.querySelectorAll(".ant-select-allow-clear .ant-select-clear").forEach(function (el) {
      el.click();
      cleared++;
    });

    showToast("已清空 " + cleared + " 个字段", "info");
  }

  function precomputeDeterministicValues(formFields, productData, manualData) {
    var deterministic = {};  // fieldIndex -> value
    var pd = (productData && productData.product_details) || {};

    formFields.forEach(function(f) {
      var label = (f.label || "").toLowerCase();
      var value = null;

      // Weight with unit conversion
      if (label.indexOf("重量") !== -1 || label.indexOf("вес") !== -1 || label.indexOf("weight") !== -1) {
        if (manualData && manualData.weight_g && String(manualData.weight_g).trim()) {
          value = String(manualData.weight_g).trim();
        } else if (pd.weight) {
          var w = parseFloat(pd.weight);
          if (!isNaN(w)) {
            var unit = (pd.weight_unit || "").toLowerCase();
            if (unit.indexOf("oz") !== -1) value = String(Math.round(w * 28.35));
            else if (unit.indexOf("lb") !== -1) value = String(Math.round(w * 453.6));
            else value = String(w);
          }
        }
      }

      // Length
      if ((label.indexOf("长") !== -1 || label.indexOf("длина") !== -1 || label.indexOf("length") !== -1) && !(label.indexOf("波长") !== -1)) {
        if (pd.length) value = _convertDimension(pd.length, pd.dimension_unit);
      }
      // Width
      if (label.indexOf("宽") !== -1 || label.indexOf("ширина") !== -1 || label.indexOf("width") !== -1) {
        if (pd.width) value = _convertDimension(pd.width, pd.dimension_unit);
      }
      // Height
      if (label.indexOf("高") !== -1 || label.indexOf("высота") !== -1 || label.indexOf("height") !== -1) {
        if (pd.height) value = _convertDimension(pd.height, pd.dimension_unit);
      }

      // Country of origin — require specific context to avoid false matches
      // "страна" alone may appear in unrelated fields (store selectors, etc.)
      if (label.indexOf("原产国") !== -1 ||
          label.indexOf("страна-изготовитель") !== -1 ||
          (label.indexOf("страна") !== -1 && (label.indexOf("изготовитель") !== -1 || label.indexOf("производства") !== -1)) ||
          (label.indexOf("产地") !== -1 && label.indexOf("原产地") === -1)) {
        value = "Китай";
      }

      // Quantity
      if (label.indexOf("数量") !== -1 || label.indexOf("количество") !== -1 || label.indexOf("quantity") !== -1) {
        if (manualData && manualData.quantity && String(manualData.quantity).trim()) {
          value = String(manualData.quantity).trim();
        } else {
          value = "1";
        }
      }

      if (value !== null) {
        deterministic[f.index] = value;
      }
    });

    return deterministic;
  }

  function _convertDimension(val, unit) {
    var v = parseFloat(val);
    if (isNaN(v)) return String(val);
    var u = (unit || "").toLowerCase();
    if (u.indexOf("in") !== -1) return String(Math.round(v * 2.54 * 10) / 10);
    return String(v);
  }

  async function verifyAndRetry(index, expectedValue) {
    var entry = resolveFieldByIndex(index);
    if (!entry || !entry.el) return false;

    var actualValue = "";
    var el = entry.el;

    if ((entry.tag === "input" || !entry.tag) && el.tagName === "INPUT" && el.type !== "checkbox" && el.type !== "radio") {
      actualValue = el.value || "";
    } else if (el.tagName === "TEXTAREA" || entry.tag === "textarea") {
      actualValue = el.value || "";
    } else if (el.tagName === "SELECT" || entry.tag === "select") {
      actualValue = el.value || "";
      var antSelect = el.closest ? el.closest(".ant-select") : null;
      if (antSelect) {
        var selItem = antSelect.querySelector(".ant-select-selection-item");
        if (selItem) actualValue = (selItem.textContent || "").trim();
      }
    } else if (entry.tag === "checkbox-group" || entry.tag === "radio-group") {
      if (entry.els && entry.els.length > 0) {
        var checked = [];
        entry.els.forEach(function(cb) { if (cb.checked) checked.push((cb.nextElementSibling || cb.parentElement).textContent.trim()); });
        actualValue = checked.join(",");
      }
    }

    var expNorm = (expectedValue || "").trim().toLowerCase();
    var actNorm = actualValue.trim().toLowerCase();

    if (!expNorm || !actNorm) return true;  // Can't verify empty
    if (expNorm === actNorm || actNorm.indexOf(expNorm) !== -1 || expNorm.indexOf(actNorm) !== -1) {
      return true;
    }

    console.warn("[sERP] 验证失败: index=" + index + " expected=" + expNorm + " actual=" + actNorm);
    return false;
  }

  async function doAutoFill() {
    if (!selectedProduct) { showToast("请先点击\"选品\"选择一个产品", "error"); return; }
    setBtnLoading(btnFill, true); setProgress(10);

    showToast("正在收集表单字段...", "info");
    var formFields = collectFormFields();
    if (!formFields.length) { setBtnLoading(btnFill, false); setProgress(0); showToast("未找到可填充的表单字段", "error"); return; }
    setProgress(20);

    var customPrompts = await collectCustomPrompts();

    // 构建发送给 LLM 的字段列表（去掉内部字段）
    function _fieldForLLM(f) {
      var clean = { index: f.index, label: f.label, tag: f.tag, type: f.type };
      if (f.placeholder) clean.placeholder = f.placeholder;
      if (f.name) clean.name = f.name;
      if (f.options) {
        clean.options = f.options.map(function (o) {
          if (typeof o === "string") return { text: o, value: o };
          return { text: o.text || o.value || "", value: o.value || o.text || "" };
        });
      }
      return clean;
    }
    var llmFields = formFields.map(_fieldForLLM);

    // Phase 2: Ensure enough SKU rows for variants
    var variantValues = getProductVariantValues(selectedProduct.product_data || {});
    if (variantValues.length > 1) {
      var ensured = await ensureVariantRowsForProduct(variantValues);
      if (ensured) {
        // Re-collect fields since new DOM elements were added
        formFields = collectFormFields();
        llmFields = formFields.map(_fieldForLLM);
      } else {
        console.warn("[sERP] 变种行创建不完全，继续填充现有行");
      }
    }

    showToast("正在AI分析 " + llmFields.length + " 个字段（最长等待150秒）...", "info");
    setProgress(25);

    var body = {
      skc: selectedProduct.skc,
      product_title: selectedProduct.title,
      product_data: selectedProduct.product_data || {},
      manual_data: selectedProduct.manual_data || {},
      form_fields: llmFields
    };
    if (Object.keys(customPrompts).length > 0) {
      body.custom_prompts = customPrompts;
    }

    var variantList = [];
    var variantValues = getProductVariantValues(selectedProduct.product_data || {});
    if (variantValues.length > 0) {
      variantValues.forEach(function(v) {
        variantList.push({
          name: v.name || v.variantName || "",
          price: v.price || "",
          stock: v.stock || "",
          attributes: v.attributes || {}
        });
      });
    }
    body.variant_list = variantList;

    // Build variant_row_mapping: summarize unique row contexts from form fields
    var rowCtxSet = {};
    var rowCtxOrder = [];
    formFields.forEach(function(f) {
      var label = f.label || "";
      var m = label.match(/\[([^\]]+)\]$/);
      if (m) {
        var ctx = m[1];
        if (!rowCtxSet[ctx]) {
          rowCtxSet[ctx] = true;
          rowCtxOrder.push(ctx);
        }
      }
    });
    if (rowCtxOrder.length > 0 && variantList.length > 0) {
      body.variant_row_summary = {
        row_contexts: rowCtxOrder,
        variant_count: variantList.length,
        note: "行上下文 [row_ctx] 对应表单SKU行。variant_list第i个变体应填入第i行(从0开始)。如果行数和变体数不一致，用产品数据推断。"
      };
    }

    try {
      setProgress(30);
      var r = await bgFetchWithTimeout(API_AUTO_FILL, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      }, 150000);
      setProgress(65);
      if (!r.ok) {
        var e = await r.json();
        throw new Error(e.error || "分析失败");
      }
      var result = await r.json();
      var mappings = result.mappings || [];
      setProgress(75);

      // Layer 1: Pre-fill deterministic values (before LLM mappings)
      var deterministicMap = precomputeDeterministicValues(formFields, selectedProduct.product_data, selectedProduct.manual_data);
      var detIdxSet = {};
      var detCount = 0;
      for (var detIdxStr in deterministicMap) {
        if (deterministicMap.hasOwnProperty(detIdxStr)) {
          var detIdx = parseInt(detIdxStr);
          detIdxSet[detIdx] = true;
          var detOk = await fillFormField(detIdx, deterministicMap[detIdxStr]);
          if (detOk) detCount++;
        }
      }
      console.log("[sERP] 确定性填充: " + detCount + " 个字段, 映射: " + JSON.stringify(deterministicMap));

      if (!mappings.length) {
        setBtnLoading(btnFill, false); setProgress(0);
        showToast("未能自动填充任何字段", "error");
        renderFillResults([], formFields.length);
        return;
      }

      // 构建 index → label 查找表用于结果展示
      var idxToLabel = {};
      formFields.forEach(function (f) { idxToLabel[f.index] = f.label; });

      var fillResults = [];
      var filledCount = 0;

      for (var mi = 0; mi < mappings.length; mi++) {
        var m = mappings[mi];
        var idx = m.index;
        var label = m.label || idxToLabel[idx] || ("字段 " + idx);

        // 进度更新: 75→95 按比例
        setProgress(75 + Math.round((mi / mappings.length) * 20));

        if (detIdxSet[idx]) {
          fillResults.push({ index: idx, label: label, value: m.value, filled: true, order: idx, error: null });
          continue;
        }

        var ok = false;
        for (var retry = 0; retry <= 2; retry++) {
          if (retry > 0) {
            console.log("[sERP] 字段填充重试 " + retry + "/2: index=" + idx + " value=" + m.value);
            await sleep(300 * Math.pow(2, retry - 1));
          }
          var preEntry = resolveFieldByIndex(idx);
          if (!preEntry || !preEntry.el || !preEntry.el.isConnected) {
            if (retry === 0) {
              var reEntry = resolveFieldByIndex(idx);
              if (!reEntry || !reEntry.el) break;
            } else {
              break;
            }
          }
          ok = await fillFormField(idx, m.value);
          if (ok) break;
        }

        if (ok) {
          filledCount++;
          // Layer 3: Post-fill verification (non-blocking)
          verifyAndRetry(idx, m.value).then(function(verified) {
            if (!verified) {
              console.warn("[sERP] 字段验证失败: index=" + idx + " label=" + label);
            }
          });
        }
        var errorMsg = null;
        if (!ok) {
          var preEntry = resolveFieldByIndex(idx);
          if (!preEntry) {
            errorMsg = "DOM 断连：元素已从页面卸载";
          } else if (!preEntry.el || !preEntry.el.isConnected) {
            errorMsg = "DOM 断连：元素引用失效";
          } else {
            errorMsg = "值不匹配：\"" + String(m.value) + "\" 未命中任何选项";
          }
        }
        fillResults.push({
          index: idx,
          label: label,
          value: m.value,
          filled: ok,
          order: idx,
          error: errorMsg
        });
        setProgress(75 + (mi / mappings.length) * 20);
      }

      // 标记未匹配的字段
      var matchedIndices = {};
      mappings.forEach(function (m) { matchedIndices[m.index] = true; });
      formFields.forEach(function (f) {
        if (!matchedIndices[f.index]) {
          fillResults.push({
            index: f.index,
            label: f.label,
            value: "",
            filled: false,
            order: f.index,
            error: "LLM 未匹配此字段"
          });
        }
      });

      fillResults.sort(function (a, b) { return a.order - b.order; });

      setProgress(100);
      showToast("填充完成！成功 " + filledCount + "/" + fillResults.length + " 个字段", filledCount > 0 ? "success" : "error");
      renderFillResults(fillResults, formFields.length);
      setBtnLoading(btnFill, false);
    } catch (e) {
      console.error("[sERP] 填充异常:", e);
      setBtnLoading(btnFill, false); setProgress(0);
      showToast("填充过程出错: " + e.message, "error");
    }
  }

  // ==================== 事件绑定 ====================
  btnSelect.addEventListener("click", function () {
    setBtnLoading(btnSelect, true); modalOverlay.classList.add("active");
    document.getElementById("serp-modal-list").innerHTML = '<div id="serp-modal-empty">正在加载产品列表...</div>';
    fetchProducts().then(function (p) {
      allProducts = p; setBtnLoading(btnSelect, false);
      console.log("[sERP] 选品: 获取到", p.length, "个产品");
      if (!p.length) {
        document.getElementById("serp-modal-list").innerHTML = '<div id="serp-modal-empty">没有找到正式产品。<br><br>请确认：<br>1. sERP Flask 后端已启动 (127.0.0.1:5000)<br>2. 已在产品管理中保存过正式产品</div>';
        return;
      }
      renderProductList(p);
    });
  });
  btnCategory.addEventListener("click", function () { doMatchCategory(); });
  btnExtract.addEventListener("click", function () { doExtractFields(); });
  btnFill.addEventListener("click", function () { doAutoFill(); });
  btnImages.addEventListener("click", function () { openImagePicker(); });
  document.getElementById("serp-btn-clear-form").addEventListener("click", function () { clearAllFormFields(); });
  btnSendHtml.addEventListener("click", function () { captureAndSendHTML(); });
  piClear.addEventListener("click", function () { selectedProduct = null; updateProductUI(); showToast("已清除产品选择", "info"); });
  hintToggle.addEventListener("click", function () {
    hintOverlay.classList.add("active");
    hintToggle.classList.add("active");
    loadAllHints();
  });
  document.getElementById("serp-hint-close").addEventListener("click", function () {
    hintOverlay.classList.remove("active");
    hintToggle.classList.remove("active");
  });
  hintOverlay.addEventListener("click", function (e) {
    if (e.target === hintOverlay) { hintOverlay.classList.remove("active"); hintToggle.classList.remove("active"); }
  });
  // 保存按钮委托
  hintPanel.addEventListener("click", function (e) {
    var btn = e.target.closest(".hint-save-btn");
    if (!btn) return;
    var level = btn.getAttribute("data-level");
    saveHints(level);
  });
  document.getElementById("serp-results-close").addEventListener("click", function () {
    resultsPanel.classList.remove("visible");
  });
  document.getElementById("serp-extract-close").addEventListener("click", function () {
    extractPanel.classList.remove("visible");
  });
  document.getElementById("serp-image-close").addEventListener("click", function () {
    imagePicker.classList.remove("visible");
  });
  imageCopy.addEventListener("click", async function () {
    var urls = Object.keys(selectedImageUrls);
    if (!urls.length) {
      showToast("请先选择图片或图片集", "error");
      return;
    }
    var ok = await copyTextToClipboard(urls.join("\n"));
    showToast(ok ? "已复制 " + urls.length + " 张图片URL" : "复制失败，请手动复制", ok ? "success" : "error");
  });
  document.getElementById("serp-modal-close").addEventListener("click", function () { modalOverlay.classList.remove("active"); });
  modalOverlay.addEventListener("click", function (e) { if (e.target === modalOverlay) modalOverlay.classList.remove("active"); });
  document.getElementById("serp-search-input").addEventListener("input", function (e) {
    var kw = e.target.value.toLowerCase().trim();
    renderProductList(kw ? allProducts.filter(function (p) { return (p.skc || "").toLowerCase().indexOf(kw) !== -1 || (p.title || "").toLowerCase().indexOf(kw) !== -1 || (p.category || "").toLowerCase().indexOf(kw) !== -1; }) : allProducts);
  });
  document.addEventListener("keydown", function (e) {
    if (!e.ctrlKey || !e.shiftKey) return;
    if (e.key.toLowerCase() === "s") { e.preventDefault(); btnSelect.click(); }
    else if (e.key.toLowerCase() === "c") { e.preventDefault(); btnCategory.click(); }
    else if (e.key.toLowerCase() === "f") { e.preventDefault(); btnFill.click(); }
    else if (e.key.toLowerCase() === "h") { e.preventDefault(); btnSendHtml.click(); }
  });

  loadAllHints();
  console.log("[sERP ExtensionHelper] 店小秘 Ozon 智能助手已加载");
  console.log("[sERP ExtensionHelper] 左侧工具栏: 选品 → 分类 → 填充 → 发送HTML | 快捷键: Ctrl+Shift+S/C/F/H");
})();
