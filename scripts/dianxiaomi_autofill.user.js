// ==UserScript==
// @name         店小秘 Ozon 智能助手
// @namespace    http://tampermonkey.net/
// @version      2.0.0
// @description  左侧悬浮工具栏：选择产品 → 智能匹配品类 → 大模型自动填充表单
// @author       sERP
// @match        https://www.dianxiaomi.com/web/ozonProduct/add*
// @match        https://www.dianxiaomi.com/web/ozonProduct/edit*
// @grant        GM_addStyle
// @grant        GM_xmlhttpRequest
// @connect      localhost
// @connect      127.0.0.1
// ==/UserScript==

(function() {
    'use strict';

    // ==================== 配置 ====================
    const FLASK_BASE = 'http://127.0.0.1:5000';
    const API_PRODUCTS = FLASK_BASE + '/api/products';
    const API_AUTO_FILL = FLASK_BASE + '/api/auto-fill/analyze';

    // 店铺中文名 → store_id 映射
    const STORE_CN_MAP = {
        '安凌': 'ozon_anling',
        'anling': 'ozon_anling',
        '安美': 'ozon_anmei',
        'anmei': 'ozon_anmei',
        '安曼': 'ozon_anman',
        'anman': 'ozon_anman'
    };

    // ==================== 状态 ====================
    let selectedProduct = null;
    let allProducts = [];

    // ==================== 样式 ====================
    GM_addStyle(`
        /* ===== 左侧悬浮工具栏 ===== */
        #serp-toolbar {
            position: fixed;
            left: 8px;
            top: 120px;
            z-index: 999990;
            display: flex;
            flex-direction: column;
            gap: 6px;
            background: #fff;
            border-radius: 10px;
            padding: 8px;
            box-shadow: 0 4px 16px rgba(0,0,0,0.12);
            font-family: "Microsoft YaHei", sans-serif;
            user-select: none;
            transition: transform 0.2s;
        }
        #serp-toolbar.collapsed {
            transform: translateX(-72px);
        }
        #serp-toolbar .serp-tb-btn {
            width: 48px;
            height: 48px;
            border-radius: 8px;
            border: 1px solid #e8e8e8;
            background: #fff;
            cursor: pointer;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            transition: all 0.2s;
            position: relative;
            font-size: 11px;
            color: #666;
            line-height: 1.2;
            gap: 2px;
        }
        #serp-toolbar .serp-tb-btn:hover {
            background: #f0f5ff;
            border-color: #428bca;
            color: #428bca;
        }
        #serp-toolbar .serp-tb-btn:active {
            transform: scale(0.95);
        }
        #serp-toolbar .serp-tb-btn.loading {
            pointer-events: none;
            opacity: 0.6;
        }
        #serp-toolbar .serp-tb-btn .tb-icon {
            font-size: 18px;
            line-height: 1;
        }
        #serp-toolbar .serp-tb-btn .tb-label {
            font-size: 10px;
            line-height: 1;
        }
        #serp-toolbar .serp-tb-btn.has-product {
            border-color: #52c41a;
            background: #f6ffed;
            color: #389e0d;
        }

        /* 产品信息区 */
        #serp-toolbar .serp-product-info {
            display: none;
            border-top: 1px solid #f0f0f0;
            margin-top: 2px;
            padding-top: 6px;
            width: 120px;
        }
        #serp-toolbar .serp-product-info.visible {
            display: block;
        }
        #serp-toolbar .serp-product-info .pi-label {
            font-size: 9px;
            color: #999;
            margin-bottom: 2px;
        }
        #serp-toolbar .serp-product-info .pi-skc {
            font-size: 11px;
            font-weight: 600;
            color: #428bca;
            word-break: break-all;
        }
        #serp-toolbar .serp-product-info .pi-title {
            font-size: 10px;
            color: #666;
            word-break: break-word;
            max-height: 40px;
            overflow: hidden;
            line-height: 1.3;
            margin-top: 2px;
        }
        #serp-toolbar .serp-product-info .pi-clear {
            font-size: 10px;
            color: #ff4d4f;
            cursor: pointer;
            margin-top: 4px;
            text-align: center;
            border: 1px solid #ffccc7;
            border-radius: 3px;
            padding: 2px 6px;
            transition: all 0.2s;
        }
        #serp-toolbar .serp-product-info .pi-clear:hover {
            background: #fff1f0;
        }

        /* 折叠按钮 */
        #serp-tb-toggle {
            position: fixed;
            left: 60px;
            top: 142px;
            z-index: 999989;
            width: 16px;
            height: 32px;
            border-radius: 0 4px 4px 0;
            border: 1px solid #e8e8e8;
            border-left: none;
            background: #fff;
            cursor: pointer;
            display: none;
            font-size: 10px;
            color: #999;
            align-items: center;
            justify-content: center;
            transition: all 0.2s;
        }
        #serp-tb-toggle:hover {
            color: #428bca;
            background: #f0f5ff;
        }

        /* ===== 产品选择弹窗 ===== */
        #serp-modal-overlay {
            display: none;
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(0,0,0,0.5);
            z-index: 1000000;
            align-items: center;
            justify-content: center;
        }
        #serp-modal-overlay.active {
            display: flex;
        }
        #serp-modal {
            background: white;
            border-radius: 12px;
            width: 700px;
            max-width: 90vw;
            max-height: 80vh;
            display: flex;
            flex-direction: column;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            font-family: "Microsoft YaHei", sans-serif;
        }
        #serp-modal-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 18px 24px;
            border-bottom: 1px solid #e5e7eb;
        }
        #serp-modal-header h3 {
            font-size: 18px;
            color: #333;
            margin: 0;
        }
        #serp-modal-close {
            background: none;
            border: none;
            font-size: 22px;
            cursor: pointer;
            color: #999;
            padding: 4px 8px;
            border-radius: 4px;
            transition: all 0.2s;
        }
        #serp-modal-close:hover {
            background: #f3f4f6;
            color: #333;
        }
        #serp-modal-search {
            padding: 12px 24px;
            border-bottom: 1px solid #f0f0f0;
        }
        #serp-modal-search input {
            width: 100%;
            padding: 10px 14px;
            border: 1px solid #d1d5db;
            border-radius: 8px;
            font-size: 14px;
            outline: none;
            transition: border-color 0.2s;
            box-sizing: border-box;
        }
        #serp-modal-search input:focus {
            border-color: #667eea;
            box-shadow: 0 0 0 3px rgba(102,126,234,0.1);
        }
        #serp-modal-list {
            flex: 1;
            overflow-y: auto;
            padding: 12px 24px;
        }
        .serp-product-item {
            display: flex;
            align-items: center;
            padding: 12px 16px;
            border-radius: 8px;
            cursor: pointer;
            transition: all 0.2s;
            margin-bottom: 6px;
            border: 1px solid #f0f0f0;
        }
        .serp-product-item:hover {
            background: #f8f9ff;
            border-color: #667eea;
            transform: translateX(2px);
        }
        .serp-product-item.selected {
            background: #f0f5ff;
            border-color: #428bca;
        }
        .serp-product-item .skc-badge {
            font-size: 12px;
            font-weight: bold;
            color: #667eea;
            background: #eef0ff;
            padding: 3px 10px;
            border-radius: 4px;
            margin-right: 12px;
            flex-shrink: 0;
        }
        .serp-product-item .product-info {
            flex: 1;
            min-width: 0;
        }
        .serp-product-item .product-title {
            font-size: 14px;
            color: #333;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .serp-product-item .product-meta {
            font-size: 12px;
            color: #999;
            margin-top: 2px;
        }
        .serp-product-item .product-status {
            font-size: 11px;
            color: #16a34a;
            background: #dcfce7;
            padding: 2px 8px;
            border-radius: 4px;
            flex-shrink: 0;
        }
        #serp-modal-empty {
            text-align: center;
            padding: 40px;
            color: #aaa;
            font-size: 14px;
        }

        /* ===== Toast ===== */
        #serp-toast {
            position: fixed;
            top: 20px;
            right: 20px;
            z-index: 1000001;
            padding: 12px 24px;
            border-radius: 8px;
            font-size: 14px;
            font-family: "Microsoft YaHei", sans-serif;
            box-shadow: 0 4px 15px rgba(0,0,0,0.15);
            display: none;
            max-width: 450px;
        }
        #serp-toast.success {
            background: #dcfce7;
            color: #16a34a;
            border: 1px solid #bbf7d0;
        }
        #serp-toast.error {
            background: #fee2e2;
            color: #dc2626;
            border: 1px solid #fecaca;
        }
        #serp-toast.info {
            background: #dbeafe;
            color: #1d4ed8;
            border: 1px solid #bfdbfe;
        }

        /* ===== 进度条 ===== */
        #serp-progress-bar {
            position: fixed;
            top: 0;
            left: 0;
            height: 3px;
            background: linear-gradient(90deg, #667eea, #764ba2);
            z-index: 1000002;
            transition: width 0.3s ease;
            width: 0%;
        }
    `);

    // ==================== 构建 DOM ====================

    // 工具栏
    const toolbar = document.createElement('div');
    toolbar.id = 'serp-toolbar';
    toolbar.innerHTML = `
        <button class="serp-tb-btn" id="serp-btn-select" title="选择产品">
            <span class="tb-icon">📦</span>
            <span class="tb-label">选品</span>
        </button>
        <button class="serp-tb-btn" id="serp-btn-category" title="智能选择分类">
            <span class="tb-icon">🏷️</span>
            <span class="tb-label">分类</span>
        </button>
        <button class="serp-tb-btn" id="serp-btn-fill" title="智能填充表单">
            <span class="tb-icon">✍️</span>
            <span class="tb-label">填充</span>
        </button>
        <div class="serp-product-info" id="serp-product-info">
            <div class="pi-label">已选产品</div>
            <div class="pi-skc" id="serp-pi-skc"></div>
            <div class="pi-title" id="serp-pi-title"></div>
            <div class="pi-clear" id="serp-pi-clear">清除</div>
        </div>
    `;
    document.body.appendChild(toolbar);

    // Toast
    const toast = document.createElement('div');
    toast.id = 'serp-toast';
    document.body.appendChild(toast);

    // 进度条
    const progressBar = document.createElement('div');
    progressBar.id = 'serp-progress-bar';
    document.body.appendChild(progressBar);

    // 弹窗
    const modalOverlay = document.createElement('div');
    modalOverlay.id = 'serp-modal-overlay';
    modalOverlay.innerHTML = `
        <div id="serp-modal">
            <div id="serp-modal-header">
                <h3>📋 选择产品</h3>
                <button id="serp-modal-close">✕</button>
            </div>
            <div id="serp-modal-search">
                <input type="text" id="serp-search-input" placeholder="搜索产品名称或 SKC 编码..." />
            </div>
            <div id="serp-modal-list">
                <div id="serp-modal-empty">正在加载产品列表...</div>
            </div>
        </div>
    `;
    document.body.appendChild(modalOverlay);

    // ==================== DOM 引用 ====================
    const btnSelect = document.getElementById('serp-btn-select');
    const btnCategory = document.getElementById('serp-btn-category');
    const btnFill = document.getElementById('serp-btn-fill');
    const productInfo = document.getElementById('serp-product-info');
    const piSkc = document.getElementById('serp-pi-skc');
    const piTitle = document.getElementById('serp-pi-title');
    const piClear = document.getElementById('serp-pi-clear');

    // ==================== 工具函数 ====================
    function showToast(msg, type) {
        type = type || 'info';
        toast.textContent = msg;
        toast.className = type;
        toast.style.display = 'block';
        clearTimeout(toast._hideTimer);
        toast._hideTimer = setTimeout(function() {
            toast.style.display = 'none';
        }, 4000);
    }

    function setProgress(pct) {
        progressBar.style.width = Math.min(100, Math.max(0, pct)) + '%';
        if (pct >= 100) {
            setTimeout(function() { progressBar.style.width = '0%'; }, 1000);
        }
    }

    function setBtnLoading(btn, loading) {
        if (loading) {
            btn.classList.add('loading');
        } else {
            btn.classList.remove('loading');
        }
    }

    function sleep(ms) {
        return new Promise(function(resolve) { setTimeout(resolve, ms); });
    }

    function updateProductUI() {
        if (selectedProduct) {
            productInfo.classList.add('visible');
            piSkc.textContent = selectedProduct.skc || '';
            piTitle.textContent = selectedProduct.title || '未命名产品';
            btnSelect.classList.add('has-product');
        } else {
            productInfo.classList.remove('visible');
            piSkc.textContent = '';
            piTitle.textContent = '';
            btnSelect.classList.remove('has-product');
        }
    }

    // ==================== 店铺检测 ====================
    function detectStoreId() {
        var storeItems = document.querySelectorAll('.shop-form-item .ant-select-selection-item');
        if (!storeItems || storeItems.length === 0) return null;
        var name = (storeItems[0].getAttribute('title') || storeItems[0].textContent || '').trim();
        for (var key in STORE_CN_MAP) {
            if (STORE_CN_MAP.hasOwnProperty(key) && name.indexOf(key) !== -1) {
                return STORE_CN_MAP[key];
            }
        }
        // fallback: try to extract from the store name directly
        // e.g. "Ozon anling" → "ozon_anling"
        var lowerName = name.toLowerCase().replace(/\s+/g, '_');
        if (lowerName.indexOf('ozon_') !== -1) return lowerName;
        return null;
    }

    // ==================== 获取产品列表 ====================
    async function fetchProducts() {
        try {
            var res = await fetch(API_PRODUCTS);
            if (!res.ok) throw new Error('获取产品列表失败');
            var data = await res.json();
            return data.products || [];
        } catch (e) {
            showToast('无法连接到 sERP 后端: ' + e.message, 'error');
            return [];
        }
    }

    // ==================== 产品选择弹窗 ====================
    function renderProductList(products) {
        var listEl = document.getElementById('serp-modal-list');
        if (products.length === 0) {
            listEl.innerHTML = '<div id="serp-modal-empty">没有找到匹配的产品</div>';
            return;
        }

        listEl.innerHTML = products.map(function(p) {
            var isSelected = selectedProduct && selectedProduct.skc === p.skc;
            var cls = 'serp-product-item' + (isSelected ? ' selected' : '');
            return '<div class="' + cls + '" data-skc="' + (p.skc || '') + '">' +
                '<span class="skc-badge">' + (p.skc || '—') + '</span>' +
                '<div class="product-info">' +
                    '<div class="product-title">' + (p.title || '未命名产品') + '</div>' +
                    '<div class="product-meta">' +
                        (p.category || '其他') + ' · ' + (p.platform || '未知平台') +
                        (p.price ? ' · ' + p.price : '') +
                    '</div>' +
                '</div>' +
                '<span class="product-status">' + (p.store_status ? Object.values(p.store_status).filter(function(s) { return s === '已上架'; }).length + ' 店已上架' : '') + '</span>' +
            '</div>';
        }).join('');

        // 点击事件
        listEl.querySelectorAll('.serp-product-item').forEach(function(item) {
            item.addEventListener('click', function() {
                var skc = item.dataset.skc;
                var product = allProducts.find(function(p) { return p.skc === skc; });
                if (product) {
                    selectedProduct = product;
                    updateProductUI();
                    modalOverlay.classList.remove('active');
                    showToast('已选择产品: ' + (product.skc || ''), 'success');
                }
            });
        });
    }

    // ==================== 智能选择分类 ====================
    async function doMatchCategory() {
        if (!selectedProduct) {
            showToast('请先点击"选品"选择一个产品', 'error');
            return;
        }

        var storeId = detectStoreId();
        if (!storeId) {
            showToast('无法识别当前店铺，请在店小秘页面选择 Ozon 店铺后再试', 'error');
            return;
        }

        setBtnLoading(btnCategory, true);
        showToast('正在匹配 Ozon 品类...', 'info');

        try {
            var prodData = selectedProduct.product_data || {};
            var description = (prodData.about_item || '') + ' ' + (prodData.product_description || '');

            var res = await fetch(FLASK_BASE + '/api/ozon/' + storeId + '/match-category', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    product_title: selectedProduct.title || '',
                    product_category: selectedProduct.category || '',
                    product_description: description.trim()
                })
            });

            var data = await res.json();

            if (!res.ok || !data.success || !data.best_match || !data.best_match.id) {
                showToast('品类匹配失败: ' + (data.error || data.warning || '无匹配结果'), 'error');
                return;
            }

            var matched = data.best_match;
            showToast('已匹配品类: ' + (matched.path || matched.name) + ' (ID: ' + matched.id + ')', 'success');

            // 尝试填写品类下拉框
            await fillCategorySelect(matched);

        } catch (e) {
            console.error('品类匹配异常:', e);
            showToast('品类匹配失败: ' + e.message, 'error');
        } finally {
            setBtnLoading(btnCategory, false);
        }
    }

    async function fillCategorySelect(matched) {
        var catWrapper = document.querySelector('.category-item .ant-select');
        if (!catWrapper) {
            showToast('未找到品类下拉框，请手动选择: ' + (matched.path || matched.name), 'error');
            return;
        }

        // 打开下拉
        var selector = catWrapper.querySelector('.ant-select-selector');
        if (!selector) {
            showToast('品类组件异常，请手动选择', 'error');
            return;
        }
        selector.click();
        await sleep(350);

        // 在搜索框输入品类名称（俄语名）
        var searchInput = catWrapper.querySelector('.ant-select-selection-search-input');
        if (searchInput) {
            var nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
            nativeSetter.call(searchInput, matched.name || '');
            searchInput.dispatchEvent(new Event('input', { bubbles: true }));
            searchInput.dispatchEvent(new Event('change', { bubbles: true }));
        }
        await sleep(600);

        // 查找并点击匹配的选项
        var dropdown = document.querySelector('.ant-select-dropdown:not(.ant-select-dropdown-hidden)');
        if (dropdown) {
            var options = dropdown.querySelectorAll('.ant-select-item-option');
            if (options.length > 0) {
                // 优先找文本精确匹配的
                var bestOption = null;
                var matchName = (matched.name || '').toLowerCase();
                options.forEach(function(opt) {
                    var text = (opt.textContent || '').toLowerCase();
                    if (text.indexOf(matchName) !== -1 && !bestOption) {
                        bestOption = opt;
                    }
                });
                if (!bestOption) bestOption = options[0];

                bestOption.click();
                await sleep(300);

                // 验证是否选中
                var selectedItem = catWrapper.querySelector('.ant-select-selection-item');
                if (selectedItem) {
                    var newVal = selectedItem.getAttribute('title') || selectedItem.textContent || '';
                    if (newVal.indexOf(matched.name) !== -1 || matched.name.indexOf(newVal) !== -1) {
                        showToast('品类已自动选中: ' + newVal, 'success');
                        return;
                    }
                }
            }
        }

        // 如果未能自动选中，给用户提示
        document.body.click(); // 关闭下拉
        showToast('请手动选择品类: 搜索 "' + (matched.name || '') + '" (ID: ' + matched.id + ')', 'error');
    }

    // ==================== 智能填充（表单字段） ====================

    function findLabel(el) {
        if (el.id) {
            var label = document.querySelector('label[for="' + el.id + '"]');
            if (label) return label.textContent.trim();
        }
        var parent = el.parentElement;
        while (parent) {
            if (parent.tagName === 'LABEL') {
                return parent.textContent.trim();
            }
            var prev = parent.previousElementSibling;
            if (prev && prev.tagName === 'LABEL') {
                return prev.textContent.trim();
            }
            parent = parent.parentElement;
        }
        parent = el.closest('.ant-form-item, .el-form-item, .form-group, .vxe-form-item');
        if (parent) {
            var labelEl = parent.querySelector('label, .ant-form-item-label, .el-form-item__label');
            if (labelEl) return labelEl.textContent.trim();
        }
        return '';
    }

    function buildSelector(el) {
        if (el.id) return '#' + CSS.escape(el.id);
        if (el.name) {
            var tag = el.tagName.toLowerCase();
            return tag + '[name="' + el.name + '"]';
        }
        var tag = el.tagName.toLowerCase();
        var classes = Array.from(el.classList).filter(function(c) {
            return !c.startsWith('ant-') && !c.startsWith('el-') && !c.startsWith('vxe-') && !c.startsWith('css-');
        });
        if (classes.length > 0) {
            return tag + '.' + classes.map(function(c) { return CSS.escape(c); }).join('.');
        }
        var parent = el.parentElement;
        if (parent) {
            var idx = Array.from(parent.children).indexOf(el) + 1;
            return tag + ':nth-child(' + idx + ')';
        }
        return tag;
    }

    function collectFormFields() {
        var fields = [];

        document.querySelectorAll('input:not([type="hidden"]):not([type="file"])').forEach(function(el) {
            var label = findLabel(el);
            fields.push({
                tag: 'input',
                type: el.type || 'text',
                name: el.name || '',
                id: el.id || '',
                class: el.className || '',
                label: label,
                placeholder: el.placeholder || '',
                currentValue: el.value || '',
                selector: buildSelector(el)
            });
        });

        document.querySelectorAll('select').forEach(function(el) {
            var label = findLabel(el);
            var options = Array.from(el.options).map(function(o) {
                return { value: o.value, text: o.text };
            });
            fields.push({
                tag: 'select',
                name: el.name || '',
                id: el.id || '',
                class: el.className || '',
                label: label,
                currentValue: el.value || '',
                options: options,
                selector: buildSelector(el)
            });
        });

        document.querySelectorAll('textarea').forEach(function(el) {
            var label = findLabel(el);
            fields.push({
                tag: 'textarea',
                name: el.name || '',
                id: el.id || '',
                class: el.className || '',
                label: label,
                placeholder: el.placeholder || '',
                currentValue: el.value || '',
                selector: buildSelector(el)
            });
        });

        return fields;
    }

    function fillFormField(selector, value) {
        if (!value && value !== 0) return false;
        value = String(value);

        try {
            var el = null;

            if (selector.startsWith('#')) {
                el = document.querySelector(selector);
            } else if (selector.indexOf('[name=') !== -1) {
                var match = selector.match(/^(\w+)\[name="([^"]+)"\]$/);
                if (match) {
                    el = document.querySelector(match[1] + '[name="' + match[2] + '"]');
                }
            }

            if (!el) {
                var parts = selector.split('.');
                var tag = parts[0];
                if (parts.length > 1) {
                    var cls = parts.slice(1).join('.');
                    el = document.querySelector(tag + '.' + cls);
                }
            }

            if (!el) {
                var m2 = selector.match(/^(\w+):nth-child\((\d+)\)$/);
                if (m2) {
                    var parent = document.querySelector('body ' + m2[1] + ':nth-child(' + m2[2] + ')');
                    if (parent) el = parent;
                }
            }

            if (!el) return false;

            var tag = el.tagName.toLowerCase();

            if (tag === 'input') {
                var inputType = el.type || 'text';
                if (inputType === 'checkbox' || inputType === 'radio') {
                    el.checked = (value === 'true' || value === '1' || value === 'yes');
                } else {
                    var nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                        window.HTMLInputElement.prototype, 'value'
                    ).set;
                    nativeInputValueSetter.call(el, value);
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                    el.dispatchEvent(new Event('blur', { bubbles: true }));
                }
                return true;
            }

            if (tag === 'select') {
                var options = Array.from(el.options);
                var matched = false;
                var exactValue = options.find(function(o) { return o.value === value; });
                if (exactValue) {
                    el.value = value;
                    matched = true;
                }
                if (!matched) {
                    var fuzzyText = options.find(function(o) {
                        return o.text.toLowerCase().indexOf(value.toLowerCase()) !== -1 ||
                               value.toLowerCase().indexOf(o.text.toLowerCase()) !== -1;
                    });
                    if (fuzzyText) {
                        el.value = fuzzyText.value;
                        matched = true;
                    }
                }
                if (matched) {
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                }
                return matched;
            }

            if (tag === 'textarea') {
                var nativeSetter = Object.getOwnPropertyDescriptor(
                    window.HTMLTextAreaElement.prototype, 'value'
                ).set;
                nativeSetter.call(el, value);
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
                return true;
            }

            if (el.isContentEditable) {
                el.textContent = value;
                el.dispatchEvent(new Event('input', { bubbles: true }));
                return true;
            }

            return false;
        } catch (e) {
            console.warn('填充失败:', selector, e);
            return false;
        }
    }

    async function analyzeWithDeepSeek(product, formFields) {
        var payload = {
            skc: product.skc,
            product_title: product.title,
            product_data: product.product_data || {},
            manual_data: product.manual_data || {},
            form_fields: formFields
        };

        try {
            var res = await fetch(API_AUTO_FILL, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            if (!res.ok) {
                var err = await res.json();
                throw new Error(err.error || '分析失败');
            }

            return await res.json();
        } catch (e) {
            showToast('DeepSeek 分析失败: ' + e.message, 'error');
            return null;
        }
    }

    async function doAutoFill() {
        if (!selectedProduct) {
            showToast('请先点击"选品"选择一个产品', 'error');
            return;
        }

        setBtnLoading(btnFill, true);
        setProgress(10);
        showToast('正在分析产品 ' + selectedProduct.skc + ' 的表单字段...', 'info');

        // 1. 采集表单字段
        var formFields = collectFormFields();
        setProgress(30);
        console.log('[sERP] 采集到表单字段:', formFields.length);

        // 2. 调用 DeepSeek
        showToast('正在调用 DeepSeek 分析 ' + formFields.length + ' 个表单字段...', 'info');
        var result = await analyzeWithDeepSeek(selectedProduct, formFields);
        setProgress(60);

        if (!result || !result.mappings) {
            setBtnLoading(btnFill, false);
            setProgress(0);
            showToast('分析失败，请重试', 'error');
            return;
        }

        // 3. 执行填充
        var mappings = result.mappings;
        var filledCount = 0;
        var totalCount = mappings.length;

        showToast('正在填充 ' + totalCount + ' 个字段...', 'info');

        mappings.forEach(function(mapping, index) {
            var success = fillFormField(mapping.selector, mapping.value);
            if (success) filledCount++;
            setProgress(60 + (index / totalCount) * 35);
        });

        setProgress(100);

        if (filledCount > 0) {
            showToast('填充完成！成功填充 ' + filledCount + '/' + totalCount + ' 个字段', 'success');
        } else {
            showToast('未能自动填充任何字段，请手动检查', 'error');
        }

        setBtnLoading(btnFill, false);
    }

    // ==================== 事件绑定 ====================

    // 选品按钮
    btnSelect.addEventListener('click', async function() {
        setBtnLoading(btnSelect, true);
        modalOverlay.classList.add('active');

        var listEl = document.getElementById('serp-modal-list');
        listEl.innerHTML = '<div id="serp-modal-empty">正在加载产品列表...</div>';

        allProducts = await fetchProducts();
        setBtnLoading(btnSelect, false);

        if (allProducts.length === 0) {
            listEl.innerHTML = '<div id="serp-modal-empty">没有找到正式产品，请先在 sERP 中采集并保存产品</div>';
            return;
        }

        renderProductList(allProducts);
    });

    // 智能分类按钮
    btnCategory.addEventListener('click', function() {
        doMatchCategory();
    });

    // 智能填充按钮
    btnFill.addEventListener('click', function() {
        doAutoFill();
    });

    // 清除已选产品
    piClear.addEventListener('click', function() {
        selectedProduct = null;
        updateProductUI();
        showToast('已清除产品选择', 'info');
    });

    // 弹窗关闭
    document.getElementById('serp-modal-close').addEventListener('click', function() {
        modalOverlay.classList.remove('active');
    });
    modalOverlay.addEventListener('click', function(e) {
        if (e.target === modalOverlay) {
            modalOverlay.classList.remove('active');
        }
    });

    // 搜索过滤
    document.getElementById('serp-search-input').addEventListener('input', function(e) {
        var keyword = e.target.value.toLowerCase().trim();
        if (!keyword) {
            renderProductList(allProducts);
            return;
        }
        var filtered = allProducts.filter(function(p) {
            return (p.skc || '').toLowerCase().indexOf(keyword) !== -1 ||
                   (p.title || '').toLowerCase().indexOf(keyword) !== -1 ||
                   (p.category || '').toLowerCase().indexOf(keyword) !== -1;
        });
        renderProductList(filtered);
    });

    // 键盘快捷键: Ctrl+Shift+S 选品, Ctrl+Shift+C 分类, Ctrl+Shift+F 填充
    document.addEventListener('keydown', function(e) {
        if (!e.ctrlKey || !e.shiftKey) return;
        switch (e.key.toLowerCase()) {
            case 's':
                e.preventDefault();
                btnSelect.click();
                break;
            case 'c':
                e.preventDefault();
                btnCategory.click();
                break;
            case 'f':
                e.preventDefault();
                btnFill.click();
                break;
        }
    });

    // ==================== 启动 ====================
    console.log('[sERP] 店小秘 Ozon 智能助手 v2.0 已加载');
    console.log('[sERP] 左侧工具栏: 选品 → 分类 → 填充');
    console.log('[sERP] 快捷键: Ctrl+Shift+S 选品 | Ctrl+Shift+C 分类 | Ctrl+Shift+F 填充');
})();
