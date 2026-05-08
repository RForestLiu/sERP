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

  // ==================== 智能分类 ====================
  function doMatchCategory() {
    if (!selectedProduct) { showToast("请先点击\"选品\"选择一个产品", "error"); return; }
    var storeId = detectStoreId();
    if (!storeId) { showToast("无法识别当前店铺", "error"); return; }
    setBtnLoading(btnCategory, true);
    showToast("正在匹配 Ozon 品类...", "info");
    var prodData = selectedProduct.product_data || {};
    var desc = (prodData.about_item || "") + " " + (prodData.product_description || "");
    return bgFetch(FLASK_BASE + "/api/ozon/" + storeId + "/match-category", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ product_title: selectedProduct.title || "", product_category: selectedProduct.category || "", product_description: desc.trim() })
    })
    .then(function (r) { return r.json(); })
    .then(function (data) {
      if (!data.success || !data.best_match || !data.best_match.id) { showToast("品类匹配失败: " + (data.error || data.warning || "无匹配结果"), "error"); return; }
      var m = data.best_match;
      showToast("已匹配品类: " + (m.path || m.name) + " (ID: " + m.id + ")", "success");
      return fillCategorySelect(m);
    })
    .catch(function (e) { console.error("[sERP] 品类匹配异常:", e); showToast("品类匹配失败: " + e.message, "error"); })
    .then(function () { setBtnLoading(btnCategory, false); });
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

  function fillCategorySelect(matched) {
    var catWrapper = document.querySelector(".category-item .ant-select");
    if (!catWrapper) { showToast("未找到品类下拉框", "error"); return Promise.resolve(); }

    var selector = catWrapper.querySelector(".ant-select-selector");
    if (!selector) { showToast("品类组件异常", "error"); return Promise.resolve(); }

    // 解析路径：优先用后端返回的 node_path_names，否则回退解析 path 字段
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

    // Step 1: 清除现有选择
    var clearBtn = catWrapper.querySelector(".ant-select-clear");
    if (clearBtn) {
      console.log("[sERP] 清除现有品类选择");
      clearBtn.click();
      return sleep(500).then(function () { return fillCategorySelect(matched); });
    }

    // Step 2: 先点击下拉框获取顶级品类列表
    // 如果已经打开就先关闭再打开，确保从顶层开始
    var openDropdown = document.querySelector(".ant-select-dropdown:not(.ant-select-dropdown-hidden)");
    if (openDropdown) {
      document.body.click(); // 关闭
      return sleep(300).then(function () { return fillCategorySelect(matched); });
    }

    console.log("[sERP] 打开品类下拉...");
    selector.click();

    // Step 3: 逐层导航
    function navigateLevel(idx) {
      if (idx >= pathNames.length) {
        console.log("[sERP] 所有层级已导航完毕");
        return Promise.resolve();
      }

      var levelName = pathNames[idx];
      var isLast = (idx === pathNames.length - 1);
      console.log("[sERP] ====== 导航第 " + (idx + 1) + "/" + pathNames.length + " 层: " + levelName + " ======");

      // 如果非第一层，可能需要点击当前选项来加载子选项
      // 对于第一层，下拉菜单应该已经打开并显示顶级品类

      return waitForDropdownOptions(8000).then(function (result) {
        if (!result || result.options.length === 0) {
          console.log("[sERP] 第" + (idx + 1) + "层超时：未出现下拉选项");
          document.body.click();
          showToast("品类第" + (idx + 1) + "层未加载，请手动选择: " + levelName, "error");
          return;
        }

        console.log("[sERP] 第" + (idx + 1) + "层: 找到 " + result.options.length + " 个下拉选项");

        // 打印前几个选项帮助调试
        result.options.slice(0, 5).forEach(function (o, i) {
          console.log("[sERP]   选项[" + i + "]:", (o.textContent || "").trim().substring(0, 70));
        });

        // 在当前选项中查找匹配
        var bestOption = findOptionByLevelName(result.options, levelName);

        if (!bestOption) {
          // 尝试在搜索框输入来缩小范围
          var searchInput = catWrapper.querySelector(".ant-select-selection-search-input");
          if (searchInput) {
            var ruOnly = levelName.replace(/（.+?）$/, "").trim();
            console.log("[sERP] 尝试搜索过滤:", ruOnly);
            var nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
            nativeSetter.call(searchInput, ruOnly);
            searchInput.dispatchEvent(new Event("input", { bubbles: true }));
            searchInput.dispatchEvent(new Event("change", { bubbles: true }));
            searchInput.dispatchEvent(new CompositionEvent("compositionend", { data: ruOnly, bubbles: true }));

            return sleep(600).then(function () {
              return waitForDropdownOptions(5000);
            }).then(function (r2) {
              if (r2 && r2.options.length > 0) {
                var bo2 = findOptionByLevelName(r2.options, levelName);
                if (bo2) { bestOption = bo2; }
              }
              if (!bestOption) {
                console.log("[sERP] 搜索后仍未找到匹配项");
                document.body.click();
                showToast("未找到品类 \"" + levelName + "\"，请手动选择", "error");
                return;
              }
              // Continue below with bestOption set
              return clickAndProceed(bestOption, idx, isLast, levelName);
            });
          } else {
            document.body.click();
            showToast("未找到品类 \"" + levelName + "\"，请手动选择", "error");
            return;
          }
        }

        return clickAndProceed(bestOption, idx, isLast, levelName);
      });
    }

    function clickAndProceed(bestOption, idx, isLast, levelName) {
      console.log("[sERP] 点击: " + bestOption.textContent.trim().substring(0, 60));
      bestOption.click();

      if (isLast) {
        // 最后一层 → 验证选择结果
        return sleep(500).then(function () {
          var si = catWrapper.querySelector(".ant-select-selection-item");
          var newVal = si ? (si.getAttribute("title") || si.textContent || "").trim() : "";
          console.log("[sERP] 最终选择值:", newVal);

          if (newVal && newVal.length > 0) {
            showToast("品类已自动选中: " + newVal, "success");
            document.body.click(); // 关闭下拉
          } else {
            showToast("品类可能未正确选中，当前值: " + (newVal || "空"), "error");
          }
        });
      } else {
        // 非最后一层 → 等待子选项加载，然后导航下一层
        console.log("[sERP] 点击非叶子层，等待子选项出现...");
        return sleep(600).then(function () {
          // 检查下拉是否还开着（有些组件点击后会关闭）
          var dd = document.querySelector(".ant-select-dropdown:not(.ant-select-dropdown-hidden)");
          if (!dd) {
            console.log("[sERP] 下拉已关闭，重新打开以加载子选项");
            selector.click();
            return sleep(500);
          }
        }).then(function () {
          return navigateLevel(idx + 1);
        });
      }
    }

    return navigateLevel(0);
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
