// ==UserScript==
// @name         店小秘 Ozon 产品自动填充助手
// @namespace    http://tampermonkey.net/
// @version      1.0.0
// @description  在店小秘 Ozon 添加产品页面，通过 Flask 后端获取产品数据并用 DeepSeek 自动填充表单
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

    // ==================== 样式 ====================
    GM_addStyle(`
        /* 悬浮按钮 */
        #serp-autofill-btn {
            position: fixed;
            bottom: 30px;
            right: 30px;
            z-index: 999999;
            padding: 14px 24px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 50px;
            font-size: 15px;
            font-weight: 600;
            cursor: pointer;
            box-shadow: 0 4px 20px rgba(102, 126, 234, 0.4);
            transition: all 0.3s ease;
            font-family: "Microsoft YaHei", sans-serif;
            letter-spacing: 0.5px;
        }
        #serp-autofill-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 25px rgba(102, 126, 234, 0.6);
        }
        #serp-autofill-btn:active {
            transform: translateY(0);
        }
        #serp-autofill-btn.loading {
            opacity: 0.7;
            pointer-events: none;
        }
        #serp-autofill-btn .spinner {
            display: inline-block;
            width: 16px;
            height: 16px;
            border: 2px solid rgba(255,255,255,0.3);
            border-top: 2px solid white;
            border-radius: 50%;
            animation: serp-spin 0.8s linear infinite;
            margin-right: 8px;
            vertical-align: middle;
        }
        @keyframes serp-spin {
            to { transform: rotate(360deg); }
        }

        /* 产品选择弹窗 */
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

        /* 填充状态提示 */
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
            max-width: 400px;
            transition: all 0.3s;
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

        /* 填充进度条 */
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

    // ==================== DOM 元素创建 ====================
    // 悬浮按钮
    const btn = document.createElement('button');
    btn.id = 'serp-autofill-btn';
    btn.innerHTML = '🚀 启用大模型填充数据';
    document.body.appendChild(btn);

    // Toast 提示
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
                <h3>📋 选择要填充的产品</h3>
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

    // ==================== 工具函数 ====================
    function showToast(msg, type = 'info') {
        toast.textContent = msg;
        toast.className = type;
        toast.style.display = 'block';
        clearTimeout(toast._hideTimer);
        toast._hideTimer = setTimeout(() => {
            toast.style.display = 'none';
        }, 4000);
    }

    function setProgress(pct) {
        progressBar.style.width = Math.min(100, Math.max(0, pct)) + '%';
        if (pct >= 100) {
            setTimeout(() => { progressBar.style.width = '0%'; }, 1000);
        }
    }

    function setLoading(isLoading) {
        if (isLoading) {
            btn.classList.add('loading');
            btn.innerHTML = '<span class="spinner"></span> 正在处理...';
        } else {
            btn.classList.remove('loading');
            btn.innerHTML = '🚀 启用大模型填充数据';
        }
    }

    // ==================== 获取产品列表 ====================
    async function fetchProducts() {
        try {
            const res = await fetch(API_PRODUCTS);
            if (!res.ok) throw new Error('获取产品列表失败');
            const data = await res.json();
            return data.products || [];
        } catch (e) {
            showToast('❌ 无法连接到 Flask 后端: ' + e.message, 'error');
            return [];
        }
    }

    // ==================== 采集页面表单字段 ====================
    function collectFormFields() {
        const fields = [];

        // 1. 收集所有 input
        document.querySelectorAll('input:not([type="hidden"]):not([type="file"])').forEach(el => {
            const label = findLabel(el);
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

        // 2. 收集所有 select
        document.querySelectorAll('select').forEach(el => {
            const label = findLabel(el);
            const options = Array.from(el.options).map(o => ({
                value: o.value,
                text: o.text
            }));
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

        // 3. 收集所有 textarea
        document.querySelectorAll('textarea').forEach(el => {
            const label = findLabel(el);
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

    function findLabel(el) {
        // 尝试通过 for 属性
        if (el.id) {
            const label = document.querySelector(`label[for="${el.id}"]`);
            if (label) return label.textContent.trim();
        }
        // 尝试找父级 label
        let parent = el.parentElement;
        while (parent) {
            if (parent.tagName === 'LABEL') {
                return parent.textContent.trim();
            }
            // 查找相邻的前一个 label
            const prev = parent.previousElementSibling;
            if (prev && prev.tagName === 'LABEL') {
                return prev.textContent.trim();
            }
            parent = parent.parentElement;
        }
        // 尝试找包含文本的父级 div/span
        parent = el.closest('.ant-form-item, .el-form-item, .form-group, .vxe-form-item');
        if (parent) {
            const labelEl = parent.querySelector('label, .ant-form-item-label, .el-form-item__label');
            if (labelEl) return labelEl.textContent.trim();
        }
        return '';
    }

    function buildSelector(el) {
        // 优先使用 id
        if (el.id) return `#${CSS.escape(el.id)}`;
        // 使用 name
        if (el.name) {
            const tag = el.tagName.toLowerCase();
            return `${tag}[name="${el.name}"]`;
        }
        // 使用 class + 索引
        const tag = el.tagName.toLowerCase();
        const classes = Array.from(el.classList).filter(c => !c.startsWith('ant-') && !c.startsWith('el-') && !c.startsWith('vxe-'));
        if (classes.length > 0) {
            return `${tag}.${classes.map(c => CSS.escape(c)).join('.')}`;
        }
        // 使用 nth-child
        const parent = el.parentElement;
        if (parent) {
            const idx = Array.from(parent.children).indexOf(el) + 1;
            return `${tag}:nth-child(${idx})`;
        }
        return tag;
    }

    // ==================== 填充表单 ====================
    function fillFormField(selector, value) {
        if (!value && value !== 0) return false;
        value = String(value);

        try {
            let el = null;

            // 尝试多种选择器
            if (selector.startsWith('#')) {
                el = document.querySelector(selector);
            } else if (selector.includes('[name=')) {
                const match = selector.match(/^(\w+)\[name="([^"]+)"\]$/);
                if (match) {
                    el = document.querySelector(`${match[1]}[name="${match[2]}"]`);
                }
            }

            if (!el) {
                // 尝试通过标签名 + class 查找
                const parts = selector.split('.');
                const tag = parts[0];
                if (parts.length > 1) {
                    const cls = parts.slice(1).join('.');
                    el = document.querySelector(`${tag}.${cls}`);
                }
            }

            if (!el) {
                // 最后尝试通过 nth-child
                const match = selector.match(/^(\w+):nth-child\((\d+)\)$/);
                if (match) {
                    const parent = document.querySelector(`body ${match[1]}:nth-child(${match[2]})`);
                    if (parent) el = parent;
                }
            }

            if (!el) return false;

            // 根据标签类型填充
            const tag = el.tagName.toLowerCase();

            if (tag === 'input') {
                const inputType = el.type || 'text';
                if (inputType === 'checkbox' || inputType === 'radio') {
                    el.checked = (value === 'true' || value === '1' || value === 'yes');
                } else {
                    // 触发原生 input 事件
                    const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
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
                // 尝试匹配选项
                const options = Array.from(el.options);
                let matched = false;

                // 精确匹配 value
                const exactValue = options.find(o => o.value === value);
                if (exactValue) {
                    el.value = value;
                    matched = true;
                }

                // 模糊匹配 text
                if (!matched) {
                    const fuzzyText = options.find(o =>
                        o.text.toLowerCase().includes(value.toLowerCase()) ||
                        value.toLowerCase().includes(o.text.toLowerCase())
                    );
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
                const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                    window.HTMLTextAreaElement.prototype, 'value'
                ).set;
                nativeInputValueSetter.call(el, value);
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
                return true;
            }

            // 对于富文本编辑器，尝试设置 contenteditable
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

    // ==================== 调用 DeepSeek 分析 ====================
    async function analyzeWithDeepSeek(product, formFields) {
        const payload = {
            skc: product.skc,
            product_title: product.title,
            product_data: product.product_data || {},
            manual_data: product.manual_data || {},
            form_fields: formFields
        };

        try {
            const res = await fetch(API_AUTO_FILL, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.error || '分析失败');
            }

            return await res.json();
        } catch (e) {
            showToast('❌ DeepSeek 分析失败: ' + e.message, 'error');
            return null;
        }
    }

    // ==================== 执行填充 ====================
    async function executeFill(product) {
        setLoading(true);
        setProgress(10);
        showToast(`🔄 正在分析产品 ${product.skc} 的表单字段...`, 'info');

        // 1. 采集表单字段
        const formFields = collectFormFields();
        setProgress(30);
        console.log('采集到表单字段:', formFields.length);

        // 2. 调用 DeepSeek 分析
        showToast(`🤖 正在调用 DeepSeek 分析 ${formFields.length} 个表单字段...`, 'info');
        const result = await analyzeWithDeepSeek(product, formFields);
        setProgress(60);

        if (!result || !result.mappings) {
            setLoading(false);
            setProgress(0);
            showToast('❌ 分析失败，请重试', 'error');
            return;
        }

        // 3. 执行填充
        const mappings = result.mappings;
        let filledCount = 0;
        let totalCount = mappings.length;

        showToast(`🔄 正在填充 ${totalCount} 个字段...`, 'info');

        mappings.forEach((mapping, index) => {
            const success = fillFormField(mapping.selector, mapping.value);
            if (success) filledCount++;
            setProgress(60 + (index / totalCount) * 35);
        });

        setProgress(100);

        // 4. 显示结果
        if (filledCount > 0) {
            showToast(`✅ 填充完成！成功填充 ${filledCount}/${totalCount} 个字段`, 'success');
        } else {
            showToast('⚠️ 未能自动填充任何字段，请手动检查', 'error');
        }

        setLoading(false);
    }

    // ==================== 弹窗逻辑 ====================
    let allProducts = [];

    function renderProductList(products) {
        const listEl = document.getElementById('serp-modal-list');
        if (products.length === 0) {
            listEl.innerHTML = '<div id="serp-modal-empty">没有找到匹配的产品</div>';
            return;
        }

        listEl.innerHTML = products.map(p => `
            <div class="serp-product-item" data-skc="${p.skc}">
                <span class="skc-badge">${p.skc}</span>
                <div class="product-info">
                    <div class="product-title">${p.title || '未命名产品'}</div>
                    <div class="product-meta">
                        ${p.category || '其他'} · ${p.platform || '未知平台'} · ${p.price || '—'}
                    </div>
                </div>
                <span class="product-status">${p.store_status ? Object.values(p.store_status).filter(s => s === '已上架').length + ' 店已上架' : ''}</span>
            </div>
        `).join('');

        // 点击事件
        listEl.querySelectorAll('.serp-product-item').forEach(item => {
            item.addEventListener('click', () => {
                const skc = item.dataset.skc;
                const product = allProducts.find(p => p.skc === skc);
                if (product) {
                    modalOverlay.classList.remove('active');
                    executeFill(product);
                }
            });
        });
    }

    // ==================== 事件绑定 ====================
    // 悬浮按钮点击
    btn.addEventListener('click', async () => {
        setLoading(true);
        modalOverlay.classList.add('active');

        const listEl = document.getElementById('serp-modal-list');
        listEl.innerHTML = '<div id="serp-modal-empty">正在加载产品列表...</div>';

        allProducts = await fetchProducts();
        setLoading(false);

        if (allProducts.length === 0) {
            listEl.innerHTML = '<div id="serp-modal-empty">⚠️ 没有找到正式产品，请先在 sERP 中采集并保存产品</div>';
            return;
        }

        renderProductList(allProducts);
    });

    // 关闭弹窗
    document.getElementById('serp-modal-close').addEventListener('click', () => {
        modalOverlay.classList.remove('active');
    });
    modalOverlay.addEventListener('click', (e) => {
        if (e.target === modalOverlay) {
            modalOverlay.classList.remove('active');
        }
    });

    // 搜索过滤
    document.getElementById('serp-search-input').addEventListener('input', (e) => {
        const keyword = e.target.value.toLowerCase().trim();
        if (!keyword) {
            renderProductList(allProducts);
            return;
        }
        const filtered = allProducts.filter(p =>
            (p.skc || '').toLowerCase().includes(keyword) ||
            (p.title || '').toLowerCase().includes(keyword) ||
            (p.category || '').toLowerCase().includes(keyword)
        );
        renderProductList(filtered);
    });

    // ==================== 初始化提示 ====================
    console.log('✅ 店小秘自动填充助手已加载');
    console.log('📌 点击右下角 "🚀 启用大模型填充数据" 按钮开始');
})();
