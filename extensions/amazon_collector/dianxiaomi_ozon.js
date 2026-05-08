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

  // ==================== CSS 注入 ====================
  var style = document.createElement("style");
  style.textContent = [
    "/* ===== 左侧悬浮工具栏 ===== */",
    "#serp-toolbar{position:fixed;left:8px;top:120px;z-index:999990;display:flex;flex-direction:column;gap:6px;background:#fff;border-radius:10px;padding:8px;box-shadow:0 4px 16px rgba(0,0,0,0.12);font-family:\"Microsoft YaHei\",sans-serif;user-select:none;}",
    "#serp-toolbar .serp-tb-btn{width:48px;height:48px;border-radius:8px;border:1px solid #e8e8e8;background:#fff;cursor:pointer;display:flex;flex-direction:column;align-items:center;justify-content:center;transition:all 0.2s;font-size:11px;color:#666;line-height:1.2;gap:2px;padding:0;}",
    "#serp-toolbar .serp-tb-btn:hover{background:#f0f5ff;border-color:#428bca;color:#428bca;}",
    "#serp-toolbar .serp-tb-btn:active{transform:scale(0.95);}",
    "#serp-toolbar .serp-tb-btn.loading{pointer-events:none;opacity:0.6;}",
    "#serp-toolbar .serp-tb-btn .tb-icon{font-size:18px;line-height:1;}",
    "#serp-toolbar .serp-tb-btn .tb-label{font-size:10px;line-height:1;}",
    "#serp-toolbar .serp-tb-btn.has-product{border-color:#52c41a;background:#f6ffed;color:#389e0d;}",
    "/* 产品信息区 */",
    "#serp-toolbar .serp-product-info{display:none;border-top:1px solid #f0f0f0;margin-top:2px;padding-top:6px;width:120px;}",
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
    "#serp-progress-bar{position:fixed;top:0;left:0;height:3px;background:linear-gradient(90deg,#667eea,#764ba2);z-index:1000002;transition:width 0.3s ease;width:0%;}"
  ].join("\n");
  document.head.appendChild(style);

  // ==================== 构建 DOM ====================

  var toolbar = document.createElement("div");
  toolbar.id = "serp-toolbar";
  toolbar.innerHTML =
    '<button class="serp-tb-btn" id="serp-btn-select" title="选择产品">' +
      '<span class="tb-icon">📦</span><span class="tb-label">选品</span>' +
    '</button>' +
    '<button class="serp-tb-btn" id="serp-btn-category" title="智能选择分类">' +
      '<span class="tb-icon">🏷️</span><span class="tb-label">分类</span>' +
    '</button>' +
    '<button class="serp-tb-btn" id="serp-btn-fill" title="智能填充表单">' +
      '<span class="tb-icon">✍️</span><span class="tb-label">填充</span>' +
    '</button>' +
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
  var btnFill = document.getElementById("serp-btn-fill");
  var productInfo = document.getElementById("serp-product-info");
  var piSkc = document.getElementById("serp-pi-skc");
  var piTitle = document.getElementById("serp-pi-title");
  var piClear = document.getElementById("serp-pi-clear");

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
    var storeItems = document.querySelectorAll(".shop-form-item .ant-select-selection-item");
    if (!storeItems.length) return null;
    var name = (storeItems[0].getAttribute("title") || storeItems[0].textContent || "").trim();
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
    if (!selectedProduct) { showToast("请先点击\"选品\"选择一个产品", "error"); return; }
    var storeId = detectStoreId();
    if (!storeId) { showToast("无法识别当前店铺", "error"); return; }
    var platform = detectPlatform();
    if (!platform) { showToast("无法识别当前平台", "error"); return; }

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
    .then(function () { setBtnLoading(btnCategory, false); });
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
    if (!_isInternal) _fillCategoryRunning = true;

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
  function findLabel(el) {
    if (el.id) { var lb = document.querySelector('label[for="' + el.id + '"]'); if (lb) return lb.textContent.trim(); }
    var p = el.parentElement;
    while (p) { if (p.tagName === "LABEL") return p.textContent.trim(); var prev = p.previousElementSibling; if (prev && prev.tagName === "LABEL") return prev.textContent.trim(); p = p.parentElement; }
    p = el.closest(".ant-form-item, .el-form-item, .form-group, .vxe-form-item");
    if (p) { var le = p.querySelector("label, .ant-form-item-label, .el-form-item__label"); if (le) return le.textContent.trim(); }
    return "";
  }

  function buildSelector(el) {
    if (el.id) return "#" + CSS.escape(el.id);
    if (el.name) return el.tagName.toLowerCase() + '[name="' + el.name + '"]';
    var cls = Array.from(el.classList).filter(function (c) { return !c.startsWith("ant-") && !c.startsWith("el-") && !c.startsWith("vxe-") && !c.startsWith("css-"); });
    if (cls.length) return el.tagName.toLowerCase() + "." + cls.map(function (c) { return CSS.escape(c); }).join(".");
    var parent = el.parentElement;
    if (parent) return el.tagName.toLowerCase() + ":nth-child(" + (Array.from(parent.children).indexOf(el) + 1) + ")";
    return el.tagName.toLowerCase();
  }

  function collectFormFields() {
    var fields = [];
    document.querySelectorAll('input:not([type="hidden"]):not([type="file"])').forEach(function (el) {
      fields.push({ tag: "input", type: el.type || "text", name: el.name || "", id: el.id || "", label: findLabel(el), placeholder: el.placeholder || "", currentValue: el.value || "", selector: buildSelector(el) });
    });
    document.querySelectorAll("select").forEach(function (el) {
      fields.push({ tag: "select", name: el.name || "", id: el.id || "", label: findLabel(el), currentValue: el.value || "", options: Array.from(el.options).map(function (o) { return { value: o.value, text: o.text }; }), selector: buildSelector(el) });
    });
    document.querySelectorAll("textarea").forEach(function (el) {
      fields.push({ tag: "textarea", name: el.name || "", id: el.id || "", label: findLabel(el), placeholder: el.placeholder || "", currentValue: el.value || "", selector: buildSelector(el) });
    });
    return fields;
  }

  function fillFormField(selector, value) {
    if (!value && value !== 0) return false;
    value = String(value);
    try {
      var el = null;
      if (selector.startsWith("#")) { el = document.querySelector(selector); }
      else if (selector.indexOf("[name=") !== -1) { var m = selector.match(/^(\w+)\[name="([^"]+)"\]$/); if (m) el = document.querySelector(m[1] + '[name="' + m[2] + '"]'); }
      if (!el) { var parts = selector.split("."); if (parts.length > 1) el = document.querySelector(parts[0] + "." + parts.slice(1).join(".")); }
      if (!el) return false;
      var tag = el.tagName.toLowerCase();
      if (tag === "input") {
        if (el.type === "checkbox" || el.type === "radio") { el.checked = (value === "true" || value === "1" || value === "yes"); }
        else { var ns = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set; ns.call(el, value); el.dispatchEvent(new Event("input", { bubbles: true })); el.dispatchEvent(new Event("change", { bubbles: true })); el.dispatchEvent(new Event("blur", { bubbles: true })); }
        return true;
      }
      if (tag === "select") {
        var opts = Array.from(el.options), matched = false;
        var exact = opts.find(function (o) { return o.value === value; });
        if (exact) { el.value = value; matched = true; }
        if (!matched) { var fuzzy = opts.find(function (o) { return o.text.toLowerCase().indexOf(value.toLowerCase()) !== -1 || value.toLowerCase().indexOf(o.text.toLowerCase()) !== -1; }); if (fuzzy) { el.value = fuzzy.value; matched = true; } }
        if (matched) { el.dispatchEvent(new Event("change", { bubbles: true })); el.dispatchEvent(new Event("input", { bubbles: true })); }
        return matched;
      }
      if (tag === "textarea") { var ts = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value").set; ts.call(el, value); el.dispatchEvent(new Event("input", { bubbles: true })); el.dispatchEvent(new Event("change", { bubbles: true })); return true; }
      if (el.isContentEditable) { el.textContent = value; el.dispatchEvent(new Event("input", { bubbles: true })); return true; }
      return false;
    } catch (e) { console.warn("[sERP] 填充失败:", selector, e); return false; }
  }

  function doAutoFill() {
    if (!selectedProduct) { showToast("请先点击\"选品\"选择一个产品", "error"); return; }
    setBtnLoading(btnFill, true); setProgress(10);
    showToast("正在分析产品 " + selectedProduct.skc + " 的表单字段...", "info");
    var formFields = collectFormFields(); setProgress(30);
    showToast("正在调用 DeepSeek 分析 " + formFields.length + " 个表单字段...", "info");
    return bgFetch(API_AUTO_FILL, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ skc: selectedProduct.skc, product_title: selectedProduct.title, product_data: selectedProduct.product_data || {}, manual_data: selectedProduct.manual_data || {}, form_fields: formFields })
    })
    .then(function (r) { if (!r.ok) return r.json().then(function (e) { throw new Error(e.error || "分析失败"); }); return r.json(); })
    .then(function (result) {
      setProgress(60);
      if (!result || !result.mappings) { setBtnLoading(btnFill, false); setProgress(0); showToast("分析失败，请重试", "error"); return; }
      var filled = 0, total = result.mappings.length;
      result.mappings.forEach(function (m, i) { if (fillFormField(m.selector, m.value)) filled++; setProgress(60 + (i / total) * 35); });
      setProgress(100);
      showToast(filled > 0 ? "填充完成！成功填充 " + filled + "/" + total + " 个字段" : "未能自动填充任何字段", filled > 0 ? "success" : "error");
      setBtnLoading(btnFill, false);
    })
    .catch(function (e) { console.error("[sERP] 填充异常:", e); setBtnLoading(btnFill, false); setProgress(0); showToast("填充过程出错: " + e.message, "error"); });
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
  btnFill.addEventListener("click", function () { doAutoFill(); });
  piClear.addEventListener("click", function () { selectedProduct = null; updateProductUI(); showToast("已清除产品选择", "info"); });
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
  });

  console.log("[sERP ExtensionHelper] 店小秘 Ozon 智能助手已加载");
  console.log("[sERP ExtensionHelper] 左侧工具栏: 选品 → 分类 → 填充 | 快捷键: Ctrl+Shift+S/C/F");
})();
