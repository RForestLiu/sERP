/**
 * sERP Collector — multi-platform product extraction
 * Supports: Amazon, 1688, Wildberries, Ozon
 * Injects floating buttons, extracts on demand, traverses variants
 */
(function () {
  "use strict";

  const SERP_URL = "http://127.0.0.1:5000/api/collect/browser_capture";

  // ==================== PLATFORM DETECTION ====================

  const host = window.location.hostname;
  const href = window.location.href;

  let PLATFORM = null;
  if (/amazon\./.test(host)) PLATFORM = "amazon";
  else if (/1688\.com/.test(host)) PLATFORM = "1688";
  else if (/wildberries\./.test(host)) PLATFORM = "wildberries";
  else if (/ozon\.ru/.test(host)) PLATFORM = "ozon";

  if (!PLATFORM) return;

  // ==================== HELPERS ====================

  function $(sel, root) {
    return (root || document).querySelector(sel);
  }
  function $$(sel, root) {
    return Array.from((root || document).querySelectorAll(sel));
  }
  function text(el) {
    return el ? el.textContent.trim() : "";
  }
  /** 克隆元素并剔除 <style>/<script> 后取纯文本 */
  function cleanText(el) {
    if (!el) return "";
    var clone = el.cloneNode(true);
    clone.querySelectorAll("style, script, noscript, [style*='display:none'], [style*='display: none'], .aplus-carousel-nav, .aplus-pagination-dots").forEach(function (n) { n.remove(); });
    return clone.textContent.replace(/[\s​‌]+/g, " ").trim();
  }
  function attr(el, name) {
    return el ? el.getAttribute(name) || "" : "";
  }

  /** Wait for DOM to stabilize after a variant click */
  function waitForUpdate(timeout) {
    timeout = timeout || 2500;
    return new Promise(function (resolve) {
      var start = Date.now();
      var observer;
      var done = false;
      function finish() {
        if (done) return;
        done = true;
        if (observer) observer.disconnect();
        resolve();
      }
      observer = new MutationObserver(function () {
        start = Date.now();
      });
      observer.observe(document.body, { childList: true, subtree: true, attributes: true });
      var timer = setInterval(function () {
        if (Date.now() - start > 800) {
          clearInterval(timer);
          finish();
        }
      }, 200);
      setTimeout(function () {
        clearInterval(timer);
        finish();
      }, timeout);
    });
  }

  /** Get a fingerprint of the current visible image data for change detection */
  function getImageFingerprint() {
    var fp = "";
    var items = document.querySelectorAll(
      ".desktop-media-mainView .item.image:not(.a-hidden) [data-a-dynamic-image]," +
      ".desktop-media-mainView .item.image:not(.a-hidden) [data-old-hires]," +
      "#imageBlock [data-old-hires]"
    );
    items.forEach(function (el) {
      var dyn = el.getAttribute("data-a-dynamic-image");
      if (dyn) {
        try {
          fp += Object.keys(JSON.parse(dyn)).sort().slice(0, 3).join(",");
        } catch (e) {}
      }
      var hires = el.getAttribute("data-old-hires");
      if (hires) fp += hires.slice(-40);
    });
    return fp;
  }

  /** After variant click, wait until image data attributes are populated AND changed from oldFingerprint */
  function waitForImageData(timeout, oldFingerprint) {
    timeout = timeout || 6000;
    return new Promise(function (resolve) {
      var start = Date.now();
      var timer = setInterval(function () {
        var items = document.querySelectorAll(
          ".desktop-media-mainView .item.image:not(.a-hidden) [data-a-dynamic-image]," +
          ".desktop-media-mainView .item.image:not(.a-hidden) [data-old-hires]," +
          "#imageBlock [data-old-hires]"
        );
        var elapsed = Date.now() - start;

        if (oldFingerprint) {
          // Fingerprint change is the strongest signal — resolve regardless of count
          var curFp = getImageFingerprint();
          if (curFp && curFp !== oldFingerprint) {
            clearInterval(timer);
            resolve(true);
            return;
          }
        } else if (items.length >= 3) {
          // No old fingerprint (first variant) — just need enough elements
          clearInterval(timer);
          resolve(true);
          return;
        }

        if (elapsed > timeout) {
          clearInterval(timer);
          resolve(false);
        }
      }, 300);
    });
  }

  /** Convert standard image URL to high-res */
  function toHires(url) {
    if (!url) return url;
    // Amazon thumbnail → full size
    url = url.replace(/\._[A-Z0-9_]+_\./, "._SL1500_.");
    // 1688 size params
    url = url.replace(/\.(400x400|300x300|200x200|100x100|60x60)\./, ".");
    url = url.replace(/\?x-oss-process=image[^&"]*/, "");
    // WB size prefix in path
    url = url.replace(/\/c\d+x\d+\/new\//, "/c2460x3280/new/");
    return url;
  }

  // ==================== PLATFORM EXTRACTORS ====================

  var EXTRACTORS = {};

  // ---------- Amazon ----------
  EXTRACTORS.amazon = {
    isProductPage: function () {
      return /\/dp\//i.test(href) || /\/gp\/product\//i.test(href);
    },

    extractTitle: function () {
      return text($("#productTitle"));
    },

    extractPrice: function () {
      var el = $(".a-price .a-offscreen") || $("#corePrice_desktop .a-offscreen") || $("#corePrice_feature_div .a-offscreen");
      if (el) return text(el);
      // Also check apex price in variant swatches
      el = $(".apex-pricetopay-value .a-offscreen") || $(".apex-core-price-identifier [class*='priceToPay']");
      if (el) return text(el);
      var whole = $(".a-price-whole");
      if (whole) {
        var frac = $(".a-price-fraction");
        var sym = $(".a-price-symbol");
        return text(sym) + text(whole) + (frac ? "." + text(frac) : "");
      }
      return "";
    },

    extractImages: function () {
      var images = [], seenIds = {};

      /** Extract unique image ID from Amazon CDN URL and build hi-res */
      function addById(url) {
        if (!url) return;
        // Amazon image URL: .../images/I/IMAGEID._XX_SIZE_.jpg
        var m = url.match(/\/images\/I\/([A-Za-z0-9+%_-]+?)(?:\._|$)/);
        if (!m) return;
        var id = decodeURIComponent(m[1]);
        if (!seenIds[id]) {
          seenIds[id] = true;
          images.push("https://m.media-amazon.com/images/I/" + id + "._SL1500_.jpg");
        }
      }

      // 1. Main view items — each has data-a-dynamic-image with all size variants
      var mainItems = $$(".desktop-media-mainView [data-a-dynamic-image]");
      mainItems.forEach(function (el) {
        var dyn = el.getAttribute("data-a-dynamic-image");
        if (dyn) {
          try {
            Object.keys(JSON.parse(dyn)).forEach(function (url) { addById(url); });
          } catch (e) { /* ignore parse errors */ }
        }
      });

      // 2. Fallback: data-old-hires on main view items (scoped, not global)
      if (images.length === 0) {
        $$(".desktop-media-mainView [data-old-hires]").forEach(function (el) {
          addById(el.getAttribute("data-old-hires"));
        });
      }

      // 3. Landing image
      var main = document.getElementById("landingImage");
      if (main) {
        var hires = main.getAttribute("data-old-hires");
        if (hires) addById(hires);
        addById(main.src);
      }

      // 4. Last resort: altImages thumbnails (only if still empty)
      if (images.length === 0) {
        $$("#altImages img").forEach(function (img) {
          addById(img.src);
        });
      }

      return images;
    },

    extractVariants: function () {
      var v = {}, seen = {};

      // NEW structure: inline-twister (Amazon's current UI)
      var newItems = $$("#inline-twister-row-color_name li[data-asin]");
      if (newItems.length) {
        v.colors = [];
        newItems.forEach(function (el) {
          var img = $("img", el);
          var name = (img ? attr(img, "alt") : text(el)).trim();
          if (name && !seen[name]) { seen[name] = true; v.colors.push(name); }
        });
      }

      // OLD structure: variation_color_name
      if (!v.colors || !v.colors.length) {
        var oldItems = $$("#variation_color_name li");
        if (oldItems.length) {
          v.colors = [];
          oldItems.forEach(function (el) {
            var name = (text($("img", el)) || text(el)).trim();
            if (name && !seen[name]) { seen[name] = true; v.colors.push(name); }
          });
        }
      }

      // Size variants — support both old and new structures
      var sizeSeen = {};
      var sizeItems = $$("#variation_size_name li, #inline-twister-row-size_name li[data-asin]");
      if (sizeItems.length) {
        v.sizes = [];
        sizeItems.forEach(function (el) {
          var t = text(el).trim();
          if (t && t !== "Select" && t !== "Size" && !sizeSeen[t]) { sizeSeen[t] = true; v.sizes.push(t); }
        });
      }

      return v;
    },

    getCurrentVariant: function () {
      var parts = [];
      // NEW: selected color in inline-twister
      var color = $("#inline-twister-row-color_name .image-swatch-button-with-slots.a-button-selected img");
      if (!color) color = $("#inline-twister-row-color_name li[data-initiallyselected='true'] img");
      // OLD: variation_color_name
      if (!color) color = $("#variation_color_name .selected img");
      if (color) parts.push(attr(color, "alt") || text(color));
      // Size
      var size = $("#inline-twister-row-size_name .a-button-selected .a-button-text, #variation_size_name .selected");
      if (size) parts.push(text(size));
      return parts.join(" / ") || "default";
    },

    clickVariant: function (type, value) {
      if (type === "color") {
        // Click the swatch image (img.swatch-image) inside the li.
        // Amazon's a-button-group uses event delegation on the ul:
        //   event.target.closest('.a-button-toggle')
        // The img is inside .a-button-toggle → closest() finds it.
        // We do NOT click the li directly (closest goes UP, not down).
        var lis = $$("#inline-twister-row-color_name li[data-asin]");
        for (var i = 0; i < lis.length; i++) {
          var img = $("img", lis[i]);
          var name = (img ? attr(img, "alt") : text(lis[i])).trim();
          if (name === value) {
            img.click();
            return true;
          }
        }
        // OLD: click #variation_color_name li
        var items = $$("#variation_color_name li");
        for (var j = 0; j < items.length; j++) {
          var oimg = $("img", items[j]);
          var oname = (oimg ? attr(oimg, "alt") : text(items[j])).trim();
          if (oname === value) { items[j].click(); return true; }
        }
      } else if (type === "size") {
        // NEW: size li
        var slis = $$("#inline-twister-row-size_name li[data-asin]");
        for (var k = 0; k < slis.length; k++) {
          if (text(slis[k]).trim().indexOf(value) !== -1) { slis[k].click(); return true; }
        }
        // OLD: size li
        var sItems = $$("#variation_size_name li");
        for (var l = 0; l < sItems.length; l++) {
          if (text(sItems[l]).trim() === value) { sItems[l].click(); return true; }
        }
      }
      return false;
    },

    extractBrand: function () {
      var t = text($("#bylineInfo"));
      return t.replace(/^Brand:\s*/i, "").replace(/^Visit the\s+/i, "");
    },

    extractCategory: function () {
      return $$("#wayfinding-breadcrumbs_feature_div .a-link-normal, #breadcrumb-link").map(function (el) { return text(el); }).join(" > ");
    },

    extractRating: function () {
      return text($("#acrPopover .a-icon-alt") || $(".a-icon-alt"));
    },

    extractBullets: function () {
      // Try multiple selectors for "About this item" bullets
      var selectors = [
        "#pqv-feature-bullets li span.a-list-item",
        "#pqv-feature-bullets .a-list-item",
        "#feature-bullets .a-list-item",
        "#feature-bullets li",
        "#feature-bullets .a-section.a-spacing-small",
        "#featurebullets_feature_div .a-list-item",
        "#featurebullets_feature_div li",
        "[data-a-expander-name='feature_bullets'] .a-list-item"
      ];
      var items = null;
      for (var i = 0; i < selectors.length; i++) {
        items = $$(selectors[i]);
        if (items.length) break;
      }
      if (!items || !items.length) return [];
      return items.map(function (el) { return text(el); }).filter(Boolean).slice(0, 15);
    },

    /** Product Description — 产品描述正文（A+ 内容等） */
    extractProductDescription: function () {
      // A+ content first (richer description with images), then product description
      var el = document.querySelector("#aplus_feature_div, #aplus .aplus-v2-description, [data-aplus]");
      if (el) { var t = cleanText(el); if (t.length > 50 && t.indexOf("Previous page") === -1 && t.indexOf("Product description") !== t.length - 18) return t; }
      // Product description section — use .a-section children, not the wrapper
      el = document.querySelector("#productDescription .a-section, #productDescription_feature_div .a-section");
      if (el) { var t2 = cleanText(el); if (t2 && t2.indexOf("Previous page") === -1 && t2 !== "Product description") return t2; }
      el = document.getElementById("productDescription");
      if (el) { var t3 = cleanText(el); if (t3.length > 50 && t3.indexOf("Previous page") === -1) return t3; }
      // A+ narrative cards
      var cards = $$("#aplus_feature_div .card-content, #aplus_feature_div .aplus-module-content");
      if (cards.length) return cards.map(function (c) { return cleanText(c); }).filter(Boolean).join("\n");
      return "";
    },

    /** Product Details / Technical Specs — 返回结构化 JSON */
    extractProductDetails: function () {
      var result = {};

      // 转为 key:value 的通用函数
      function parseLines(text) {
        var lines = text.split(/\n/);
        lines.forEach(function (line) {
          line = line.replace(/[‏‎]/g, "").trim();
          if (!line) return;
          var idx = line.indexOf(":");
          if (idx === -1) return;
          var key = line.slice(0, idx).replace(/[‏‎]/g, "").trim();
          var val = line.slice(idx + 1).replace(/[‏‎]/g, "").trim();
          if (!key || !val) return;
          var normKey = key.replace(/\s+/g, "_").replace(/[^a-zA-Z0-9_]/g, "").toLowerCase();
          if (normKey && val && !result[normKey]) result[normKey] = val;
        });
      }

      // 1. 现代 Voyager 布局表格
      var trs = $$("#prodDetails table.prodDetTable tr, .prodDetTable tr, #productDetails_techSpec_section_1 tr, #productDetails_detailBullets_sections1 tr, #detailBullets_feature_div tr");
      for (var i = 0; i < trs.length; i++) {
        var th = trs[i].querySelector("th");
        var td = trs[i].querySelector("td");
        if (th && td) {
          var tKey = cleanText(th).replace(/\s+/g, "_").replace(/[^a-zA-Z0-9_]/g, "").toLowerCase();
          var tVal = cleanText(td);
          if (tKey && tVal && !result[tKey]) result[tKey] = tVal;
        }
      }
      if (Object.keys(result).length) return result;

      // 2. detail-bullets 列表 → 按行解析 key:value
      var bullets = $$("#detailBulletsWrapper_feature_div .a-list-item, #detailBullets_feature_div .a-list-item");
      if (bullets.length) {
        parseLines(bullets.map(function (el) { return cleanText(el); }).filter(Boolean).join("\n"));
        if (Object.keys(result).length) return result;
      }

      // 3. 最后兜底：尝试从 #prodDetails 全文解析（可能有隐藏的表格文本）
      var prodDetailsEl = document.getElementById("prodDetails");
      if (prodDetailsEl) {
        parseLines(cleanText(prodDetailsEl));
      }

      return result;
    },

    extractAll: function () {
      return {
        title: this.extractTitle(),
        price: this.extractPrice(),
        brand: this.extractBrand(),
        rating: this.extractRating(),
        category: this.extractCategory(),
        images: this.extractImages(),
        variants: this.extractVariants(),
        bullets: this.extractBullets(),
        product_description: this.extractProductDescription(),
        product_details: this.extractProductDetails(),
        currentVariant: this.getCurrentVariant(),
      };
    },
  };

  // ---------- 1688 (Alibaba China) ----------
  EXTRACTORS["1688"] = {
    isProductPage: function () {
      return /detail\.1688\.com\/offer\//.test(href);
    },

    extractTitle: function () {
      return text($(".offer-title-text") || $("h1.d-title") || $("meta[property='og:title']")) ||
        text($("h1"));
    },

    extractPrice: function () {
      // Single price
      var el = $(".price-original .value") ||
               $(".offer-price .value-content") ||
               $(".mod-price .price") ||
               $(".cost-price");
      return text(el);
    },

    extractImages: function () {
      var images = [], seen = {};
      function add(url) {
        if (!url || seen[url] || /\.(gif|png)\b.*(loading|icon|loadingImage)/i.test(url)) return;
        seen[url] = true;
        images.push(url);
      }
      // Main image
      var main = $(".tab-img img") || $(".detail-gallery-img") || $(".main-image-container img");
      if (main) add(attr(main, "data-src") || main.src);
      // Gallery thumbnails
      $$(".nav-img-list img, .image-nav img, .tab-img img, .detail-gallery-img").forEach(function (img) {
        add(attr(img, "data-src") || attr(img, "src"));
      });
      // Data attributes in DOM
      $$("[data-imgs]").forEach(function (el) {
        try {
          var imgs = JSON.parse(attr(el, "data-imgs"));
          if (Array.isArray(imgs)) imgs.forEach(function (u) { add(u); });
        } catch (e) {}
      });
      return images;
    },

    extractVariants: function () {
      var v = {};
      // 1688 uses .prop-items for property groups
      $$(".prop-items, .prop-item-wrapper, .sku-item-wrapper").forEach(function (group) {
        var label = text($(".prop-title, .prop-name, .title", group) || group.previousElementSibling);
        var items = $$(".prop-item, .item, li", group).map(function (el) { return text(el); }).filter(Boolean);
        if (!label) label = text(group.previousElementSibling);
        if (items.length) {
          var key = /color|颜色|色/i.test(label) ? "colors" :
                    /size|尺码|规格/i.test(label) ? "sizes" :
                    /style|款式|类型/i.test(label) ? "styles" : null;
          if (key) v[key] = (v[key] || []).concat(items);
        }
      });
      // Also check for .sku-item data attributes
      if (!v.colors && !v.sizes) {
        var skuItems = $$("[data-sku-id], .sku-item");
        if (skuItems.length) v.skus = skuItems.map(function (el) { return text(el); }).filter(Boolean).slice(0, 50);
      }
      return v;
    },

    getCurrentVariant: function () {
      var parts = [];
      $$(".prop-item.active, .prop-item.selected, .sku-item.selected").forEach(function (el) {
        parts.push(text(el));
      });
      return parts.join(" / ") || "default";
    },

    clickVariant: function (type, value) {
      var groups = $$(".prop-items, .prop-item-wrapper, .sku-item-wrapper");
      for (var g = 0; g < groups.length; g++) {
        var label = text($(".prop-title, .prop-name", groups[g]) || groups[g].previousElementSibling);
        var match = false;
        if (type === "color") match = /颜色|色|color/i.test(label);
        else if (type === "size") match = /尺码|规格|size/i.test(label);
        if (match || !label) {
          var items = $$(".prop-item, .item, li", groups[g]);
          for (var i = 0; i < items.length; i++) {
            if (text(items[i]).trim() === value) {
              items[i].click();
              return true;
            }
          }
        }
      }
      return false;
    },

    extractBrand: function () {
      // 1688 brand is often in the store name or not present
      var el = $(".company-name") || $(".supplier-name") || $(".shop-name");
      return text(el);
    },

    extractCategory: function () {
      return $$(".breadcrumb a, .breadcrumb span").map(function (el) { return text(el); }).join(" > ");
    },

    extractDescription: function () {
      return "";
    },

    extractAll: function () {
      return {
        title: this.extractTitle(),
        price: this.extractPrice(),
        brand: this.extractBrand(),
        rating: "",
        category: this.extractCategory(),
        images: this.extractImages(),
        variants: this.extractVariants(),
        bullets: [],
        currentVariant: this.getCurrentVariant(),
        description: this.extractDescription(),
      };
    },
  };

  // ---------- Wildberries (2026 refresh) ----------
  EXTRACTORS.wildberries = {
    isProductPage: function () {
      return /\/catalog\/\d+\/detail\.aspx/.test(href);
    },

    /** 从 URL 提取当前产品 ID */
    extractProductId: function () {
      var m = href.match(/\/catalog\/(\d+)\/detail\.aspx/);
      return m ? m[1] : "";
    },

    /** 从 <title> 提取产品名，移除 "купить за N ₽ ..." 后缀 */
    extractTitle: function () {
      var t = document.title || "";
      var m = t.match(/^(.+?)\s+купить\s+за\s+\d/);
      if (m) return m[1].trim();
      return t;
    },

    /** 从 .priceWrap--pxdH1 提取最终售价 */
    extractPrice: function () {
      var el = $(".priceWrap--pxdH1");
      if (el) {
        return text(el).replace(/&nbsp;/g, "").replace(/[₽руб\s]/g, "").trim();
      }
      // 备选：b 标签含卢布符号
      var prices = $$("b[class*='danger']");
      for (var i = 0; i < prices.length; i++) {
        var s = text(prices[i]);
        if (/[₽руб]/.test(s)) {
          return s.replace(/&nbsp;/g, "").replace(/[₽руб\s]/g, "").trim();
        }
      }
      return "";
    },

    /** 从 WBBasket CDN URL 中提取当前产品图片并构造超清链接 */
    extractImages: function () {
      var currentPid = this.extractProductId();
      var byPid = {};

      var html = document.documentElement.outerHTML;
      var re = /https?:\/\/basket-\d+\.(?:wbbasket\.ru|wbcontent\.net)\/vol\d+\/part\d+\/(\d+)\/images\/(\w+)\/(\d+)\./g;
      var m;
      while ((m = re.exec(html)) !== null) {
        var pid = m[1], size = m[2], num = parseInt(m[3]);
        if (currentPid && pid !== currentPid) continue;
        if (!byPid[pid]) {
          byPid[pid] = { base: m[0].substring(0, m[0].lastIndexOf("/images/")), maxNum: 0, hasBig: false };
        }
        byPid[pid].maxNum = Math.max(byPid[pid].maxNum, num);
        if (size === "big") byPid[pid].hasBig = true;
      }

      var mainPid = null, bestScore = 0;
      for (var pid in byPid) {
        var score = byPid[pid].maxNum + (byPid[pid].hasBig ? 100 : 0);
        if (score > bestScore) { bestScore = score; mainPid = pid; }
      }

      if (mainPid) {
        var images = [];
        var base = byPid[mainPid].base;
        for (var n = 1; n <= byPid[mainPid].maxNum; n++) {
          images.push(base + "/images/big/" + n + ".webp");
        }
        return images;
      }
      return [];
    },

    /** 从颜色变体滑块中提取变体列表（仅 data-nm-id 锚点，排除推荐商品卡片） */
    extractVariants: function () {
      var v = {};
      var colors = [];
      var urls = {};
      var seen = {};

      var links = $$("a[data-nm-id]");
      links.forEach(function (a) {
        var img = $("img", a);
        var alt = img ? attr(img, "alt") : "";
        if (!alt) return;
        // alt 格式: "Кошелек маленький серый из экозамши"
        // 提取颜色词: 去掉 "из <material>" 后缀，取最后一个词
        var name = alt.replace(/\s+из\s+\S+$/i, "").split(/\s+/).pop();
        if (name && !seen[name]) {
          seen[name] = true;
          colors.push(name);
          urls[name] = a.href;
        }
      });

      if (colors.length) v.colors = colors;
      if (Object.keys(urls).length) v.urls = urls;
      return v;
    },

    /** 从 title 标签解析当前颜色 */
    getCurrentVariant: function () {
      var t = document.title || "";
      // title 格式: "Кошелек маленький серый из экозамши Caserra 210344524 ..."
      var m = t.match(/Кошелек\s+(?:маленький|большой)\s+(\S+)/i);
      if (m) return m[1];
      return "default";
    },

    /** 点击颜色变体色块 → 导航到该颜色的产品页 */
    clickVariant: function (type, value) {
      if (type !== "color") return false;
      var links = $$("a[data-nm-id]");
      for (var i = 0; i < links.length; i++) {
        var img = $("img", links[i]);
        var alt = img ? attr(img, "alt") : "";
        if (alt.indexOf(value) !== -1) {
          links[i].click();
          return true;
        }
      }
      return false;
    },

    /** 面包屑最后一项 = 品牌 */
    extractBrand: function () {
      var crumbs = $$("[itemprop='name']");
      if (crumbs.length > 0) return text(crumbs[crumbs.length - 1]);
      return "";
    },

    /** 面包屑中间项 = 分类路径（去掉"Главная"首项和品牌末项） */
    extractCategory: function () {
      var crumbs = $$("[itemprop='name']");
      var parts = [];
      for (var i = 1; i < crumbs.length - 1; i++) {
        parts.push(text(crumbs[i]));
      }
      return parts.join(" > ");
    },

    /** H1 含评分数字 */
    extractRating: function () {
      var h1 = text($("h1"));
      if (h1 && /^\d[\d,.]*$/.test(h1)) return h1;
      return "";
    },

    /** 点击 "Характеристики и описание" 按钮打开详情弹窗（如需要） */
    _drawerOpened: false,

    _ensureDrawerOpen: function () {
      if ($(".descriptionText--JBcnf")) return true;
      var btn = $(".btnDetailText--nrkiv");
      if (!btn) return false;
      btn.click();
      this._drawerOpened = !!$(".descriptionText--JBcnf");
      return this._drawerOpened;
    },

    /** product_additional_information 区域的 table > th/td 规格参数 */
    extractProductDetails: function () {
      var result = {};
      // 弹窗打开后优先从弹窗内读（字段更全），否则读主页面
      var section = $(".mo-drawer__paper [data-testid='product_additional_information']") || $("[data-testid='product_additional_information']");
      if (!section) return result;
      var rows = $$("tr", section);
      rows.forEach(function (row) {
        var th = $("th", row);
        var td = $("td", row);
        if (th && td) {
          var key = text(th).replace(/\s+/g, "_").replace(/[^a-zA-Z0-9_а-яё]/gi, "").toLowerCase();
          var val = text(td);
          if (key && val && !result[key]) result[key] = val;
        }
      });
      return result;
    },

    /** 从 "Характеристики и описание" 弹窗提取文字描述 */
    extractDescription: function () {
      this._ensureDrawerOpen();
      var descEl = $(".descriptionText--JBcnf");
      return descEl ? cleanText(descEl) : "";
    },

    extractAll: function () {
      // 先确保弹窗打开，再提取弹窗相关数据（描述+规格参数）
      this._ensureDrawerOpen();
      return {
        title: this.extractTitle(),
        price: this.extractPrice(),
        brand: this.extractBrand(),
        rating: this.extractRating(),
        category: this.extractCategory(),
        images: this.extractImages(),
        variants: this.extractVariants(),
        bullets: [],
        product_description: this.extractDescription(),
        product_details: this.extractProductDetails(),
        currentVariant: this.getCurrentVariant(),
      };
    },
  };

  // ---------- Ozon (basic) ----------
  EXTRACTORS.ozon = {
    isProductPage: function () {
      return /ozon\.ru\/product\//.test(href);
    },

    extractTitle: function () {
      return text($("h1[data-widget='webProductHeading']") || $("h1.xl3") || $("h1"));
    },

    extractPrice: function () {
      return text($(".vl9_2 span") || $(".ui-p6 span") || $("span[data-widget='webPrice']"));
    },

    extractImages: function () {
      var images = [], seen = {};
      function add(url) {
        if (!url || seen[url] || url.indexOf("data:image") === 0) return;
        seen[url] = true;
        images.push(url);
      }
      $$(".ui-g8 img, .ui-j6 img, img[src*='ir-3.ozone.ru']").forEach(function (img) {
        add(attr(img, "src") || img.src);
      });
      // Ozon uses picture > source elements sometimes
      $$("picture source").forEach(function (s) {
        var srcset = attr(s, "srcset");
        if (srcset) {
          srcset.split(",").forEach(function (part) {
            var url = part.trim().split(" ")[0];
            if (url) add(url);
          });
        }
      });
      return images;
    },

    extractVariants: function () {
      var v = {};
      $$("button[aria-label], div[role='radiogroup'] button, .sku-property button").forEach(function (btn) {
        var t = text(btn);
        if (!t) return;
        var parent = btn.closest("div");
        var groupLabel = text($("span, label", parent)) || text(parent.previousElementSibling);
        if (/цвет|color/i.test(groupLabel)) {
          if (!v.colors) v.colors = [];
          if (v.colors.indexOf(t) === -1) v.colors.push(t);
        } else if (/размер|size/i.test(groupLabel)) {
          if (!v.sizes) v.sizes = [];
          if (v.sizes.indexOf(t) === -1) v.sizes.push(t);
        }
      });
      return v;
    },

    getCurrentVariant: function () {
      return "";
    },

    clickVariant: function () {
      // Ozon variant traversal is complex (React modals), skip for now
      return false;
    },

    extractBrand: function () {
      return text($(".tsBodyS a[href*='/seller/']") || $("a[href*='seller']"));
    },

    extractCategory: function () {
      return $$("a[href*='/category/']").map(function (el) { return text(el); }).join(" > ");
    },

    extractRating: function () {
      return text($("span[data-widget='webRating']") || $(".rating-value"));
    },

    extractDescription: function () {
      return text($("div[data-widget='webDescription']") || $(".description"));
    },

    extractAll: function () {
      return {
        title: this.extractTitle(),
        price: this.extractPrice(),
        brand: this.extractBrand(),
        rating: this.extractRating(),
        category: this.extractCategory(),
        images: this.extractImages(),
        variants: this.extractVariants(),
        bullets: [],
        currentVariant: this.getCurrentVariant(),
        description: this.extractDescription(),
      };
    },
  };

  var X = EXTRACTORS[PLATFORM];
  if (!X || !X.isProductPage()) return;

  // ==================== UI INJECTION ====================

  var UI = {
    collecting: false,
    cancelled: false,
    total: 0,
    current: 0,
    container: null,
    statusEl: null,
    counterEl: null,
  };

  function injectUI() {
    if (document.getElementById("serp-collector-root")) return;

    var css = document.createElement("style");
    css.textContent = [
      "#serp-collector-root{position:fixed;bottom:20px;right:20px;z-index:2147483647;font:14px/1.4 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;}",
      "#serp-collector-panel{background:#1a1a2e;color:#eee;border-radius:8px;box-shadow:0 4px 24px rgba(0,0,0,.4);padding:10px 14px;min-width:180px;user-select:none;}",
      "#serp-collector-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;font-size:12px;color:#999;}",
      "#serp-collector-btns{display:flex;gap:6px;margin-bottom:6px;}",
      "#serp-collector-btns button{flex:1;padding:6px 8px;border:none;border-radius:4px;cursor:pointer;font-size:12px;font-weight:600;transition:all .15s;}",
      "#serp-collector-btns .btn-collect{background:#ff9900;color:#000;}",
      "#serp-collector-btns .btn-collect:hover{background:#ffaa22;}",
      "#serp-collector-btns .btn-all{background:#e74c3c;color:#fff;}",
      "#serp-collector-btns .btn-all:hover{background:#ff5c4c;}",
      ".btn-send-html{background:#27ae60;color:#fff;padding:6px 8px;border:none;border-radius:4px;cursor:pointer;font-size:12px;font-weight:600;width:100%;transition:all .15s;}",
      ".btn-send-html:hover{background:#2ecc71;}",
      "#serp-collector-btns button:disabled{opacity:.5;cursor:not-allowed;}",
      "#serp-collector-status{font-size:11px;color:#aaa;min-height:16px;}",
      "#serp-collector-minimize{background:none;border:none;color:#666;cursor:pointer;font-size:16px;padding:0 2px;}",
      "#serp-collector-minimize:hover{color:#fff;}",
      ".serp-toast{position:fixed;top:10px;right:10px;z-index:2147483647;background:#ff9900;color:#000;padding:8px 16px;border-radius:4px;font:14px Arial;opacity:0;transition:opacity .3s;}",
    ].join("\n");
    document.head.appendChild(css);

    UI.container = document.createElement("div");
    UI.container.id = "serp-collector-root";
    UI.container.innerHTML = [
      '<div id="serp-collector-panel">',
      '<div id="serp-collector-header"><span>sERP ' + PLATFORM + '</span><button id="serp-collector-minimize">&minus;</button></div>',
      '<div id="serp-collector-btns">',
      '<button class="btn-collect" id="serp-btn-collect">采集</button>',
      '<button class="btn-all" id="serp-btn-all">全部规格</button>',
      '</div>',
      '<button class="btn-send-html" id="serp-btn-send-html">发送HTML</button>',
      '<div id="serp-collector-status">就绪</div>',
      '</div>',
    ].join("");
    document.body.appendChild(UI.container);

    UI.statusEl = document.getElementById("serp-collector-status");
    UI.counterEl = document.getElementById("serp-collector-status");

    // Event handlers
    document.getElementById("serp-btn-collect").addEventListener("click", function () {
      if (UI.collecting) return;
      collectCurrent();
    });
    document.getElementById("serp-btn-all").addEventListener("click", function () {
      if (UI.collecting) return;
      collectAllVariants();
    });
    document.getElementById("serp-btn-send-html").addEventListener("click", function () {
      if (UI.collecting) return;
      sendHTMLToSERP();
    });
    document.getElementById("serp-collector-minimize").addEventListener("click", function () {
      var panel = document.getElementById("serp-collector-panel");
      var btns = document.getElementById("serp-collector-btns");
      var status = document.getElementById("serp-collector-status");
      if (btns.style.display === "none") {
        btns.style.display = "";
        status.style.display = "";
        this.textContent = "−";
      } else {
        btns.style.display = "none";
        status.style.display = "none";
        this.textContent = "+";
      }
    });
  }

  function setStatus(msg, isError) {
    UI.statusEl.textContent = msg;
    UI.statusEl.style.color = isError ? "#e74c3c" : "#aaa";
  }

  function setButtons(enabled) {
    var btns = document.querySelectorAll("#serp-collector-btns button");
    btns.forEach(function (b) { b.disabled = !enabled; });
  }

  function showToast(msg, isError) {
    var d = document.createElement("div");
    d.className = "serp-toast";
    d.textContent = msg;
    if (isError) d.style.background = "#e74c3c";
    document.body.appendChild(d);
    setTimeout(function () { d.style.opacity = "1"; }, 50);
    setTimeout(function () { d.style.opacity = "0"; }, 2500);
    setTimeout(function () { d.remove(); }, 3000);
  }

  // ==================== COMMUNICATION ====================

  function sendToSERP(data) {
    return fetch(SERP_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }).then(function (r) { return r.json(); })
      .then(function (result) {
        console.log("[sERP Collector] Response:", result);
        return result;
      });
  }

  // ==================== COLLECTION LOGIC ====================

  function buildPayload() {
    var d = X.extractAll();
    // 净化 variants：移除内部导航用的 urls，仅保留产品信息
    var cleanVariants = {};
    if (d.variants) {
      if (d.variants.colors) cleanVariants.colors = d.variants.colors;
      if (d.variants.sizes) cleanVariants.sizes = d.variants.sizes;
      if (d.variants.styles) cleanVariants.styles = d.variants.styles;
      if (d.variants.skus) cleanVariants.skus = d.variants.skus;
    }
    return {
      url: href,
      platform: PLATFORM,
      title: d.title || "",
      price: d.price || "",
      brand: d.brand || "",
      rating: d.rating || "",
      category: d.category || "",
      images: d.images || [],
      variants: cleanVariants,
      bullets: d.bullets || [],
      about_item: (d.bullets || []).join("\n"),
      product_description: d.product_description || "",
      product_details: d.product_details || {},
      description: d.description || "",
      currentVariant: d.currentVariant || "",
      collectedAt: new Date().toISOString(),
    };
  }

  function sendHTMLToSERP() {
    if (UI.collecting) return;
    UI.collecting = true;
    setButtons(false);
    setStatus("获取HTML中...");

    var html = document.documentElement.outerHTML;
    var payload = {
      url: href,
      platform: PLATFORM || "unknown",
      html: html,
      title: document.title,
      sentAt: new Date().toISOString(),
    };

    console.log("[sERP Collector] Sending HTML, size:", (html.length / 1024).toFixed(1), "KB");

    fetch(SERP_URL.replace("browser_capture", "send_html"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }).then(function (r) { return r.json(); })
      .then(function (result) {
        if (result && result.status === "ok") {
          showToast("HTML已发送 ✓ (" + (html.length / 1024).toFixed(0) + "KB)");
          setStatus("HTML已发送 ✓");
        } else {
          showToast("发送失败", true);
          setStatus("失败", true);
        }
        UI.collecting = false;
        setButtons(true);
      }).catch(function () {
        showToast("sERP 未运行", true);
        setStatus("sERP 未运行", true);
        UI.collecting = false;
        setButtons(true);
      });
  }

  function collectCurrent() {
    if (UI.collecting) return;
    UI.collecting = true;
    setButtons(false);
    setStatus("采集中...");

    var data = buildPayload();
    if (!data.title) {
      setStatus("未找到产品标题", true);
      setButtons(true);
      UI.collecting = false;
      return;
    }

    console.log("[sERP Collector] Collecting:", data.title.substring(0, 60));
    console.log("[sERP Collector] Platform:", PLATFORM, "Images:", data.images.length);

    sendToSERP(data).then(function (result) {
      if (result && result.status === "ok") {
        showToast("已采集: " + (result.title || data.title).substring(0, 40));
        setStatus("已采集 ✓");
      } else {
        showToast("采集失败", true);
        setStatus("失败", true);
      }
      UI.collecting = false;
      setButtons(true);
    }).catch(function () {
      showToast("sERP 未运行", true);
      setStatus("sERP 未运行", true);
      UI.collecting = false;
      setButtons(true);
    });
  }

  /** Fetch a variant ASIN page and extract images + price from HTML */
  function fetchVariantData(asin) {
    var base = window.location.origin;
    return fetch(base + "/dp/" + asin).then(function (res) {
      if (!res.ok) throw new Error("HTTP " + res.status);
      return res.text();
    }).then(function (html) {
      // Parse response into a DOM to use targeted selectors (avoids capturing
      // unrelated images from sponsored products / colorImages JSON / etc.)
      var doc = new DOMParser().parseFromString(html, "text/html");

      var seen = {};
      var images = [];

      function addById(url) {
        if (!url) return;
        var m = url.match(/\/images\/I\/([A-Za-z0-9+%_-]+?)(?:\._|$)/);
        if (!m) return;
        var id = decodeURIComponent(m[1]);
        if (!seen[id]) {
          seen[id] = true;
          images.push("https://m.media-amazon.com/images/I/" + id + "._SL1500_.jpg");
        }
      }

      // 1. Main view items (same logic as extractImages on live DOM)
      var mainItems = doc.querySelectorAll(".desktop-media-mainView [data-a-dynamic-image]");
      for (var i = 0; i < mainItems.length; i++) {
        var dyn = mainItems[i].getAttribute("data-a-dynamic-image");
        if (dyn) {
          try {
            Object.keys(JSON.parse(dyn)).forEach(function (url) { addById(url); });
          } catch (e) {}
        }
      }

      // 2. Fallback: data-old-hires on main view
      if (images.length === 0) {
        var oldHires = doc.querySelectorAll(".desktop-media-mainView [data-old-hires]");
        for (var j = 0; j < oldHires.length; j++) {
          addById(oldHires[j].getAttribute("data-old-hires"));
        }
      }

      // 3. Landing image
      var landing = doc.getElementById("landingImage");
      if (landing) {
        addById(landing.getAttribute("data-old-hires"));
        addById(landing.getAttribute("src"));
      }

      // 4. Last resort: altImages thumbnails
      if (images.length === 0) {
        var altImgs = doc.querySelectorAll("#altImages img");
        for (var k = 0; k < altImgs.length; k++) {
          addById(altImgs[k].getAttribute("src"));
        }
      }

      // Extract variant-specific price
      var price = "";
      var priceRe = /"priceToPay"\s*:\s*"([^"]+)"/;
      var priceMatch = priceRe.exec(html);
      if (priceMatch) price = priceMatch[1];
      if (!price) {
        var apexRe = /"apexPrice"\s*:\s*"([^"]+)"/;
        var apexMatch = apexRe.exec(html);
        if (apexMatch) price = apexMatch[1];
      }

      return { images: images, price: price };
    });
  }

  /** Get color-name → ASIN mapping from the current page DOM */
  function getColorToAsinFromDOM() {
    var map = {};
    var lis = $$("#inline-twister-row-color_name li[data-asin]");
    lis.forEach(function (li) {
      var asin = attr(li, "data-asin");
      var img = $("img", li);
      var name = (img ? attr(img, "alt") : text(li)).trim();
      if (name && asin) map[name] = asin;
    });
    return map;
  }

  /** Fetch WB variant page HTML and extract images + price */
  function fetchWBVariantData(url) {
    return fetch(url).then(function (res) {
      if (!res.ok) throw new Error("HTTP " + res.status);
      return res.text();
    }).then(function (html) {
      console.log("[sERP] fetchWBVariant: HTML size=" + html.length + " for " + url);

      var byPid = {};
      // Match both CDN domains, all image sizes (big/c246x328/tm)
      var re = /https?:\/\/basket-\d+\.(?:wbbasket\.ru|wbcontent\.net)\/vol\d+\/part\d+\/(\d+)\/images\/(big|c246x328|tm)\/(\d+)\.webp/g;
      var m;
      while ((m = re.exec(html)) !== null) {
        var pid = m[1], size = m[2], num = parseInt(m[3]);
        if (!byPid[pid]) byPid[pid] = { base: m[0].substring(0, m[0].lastIndexOf("/images/")), maxNum: 0, hasBig: false };
        byPid[pid].maxNum = Math.max(byPid[pid].maxNum, num);
        if (size === "big") byPid[pid].hasBig = true;
      }

      console.log("[sERP] fetchWBVariant: CDN product IDs found:", Object.keys(byPid).length, Object.keys(byPid));

      // Pick main product: prefer one with big images, then most images
      var mainPid = null, bestScore = 0;
      for (var pid in byPid) {
        var score = byPid[pid].maxNum + (byPid[pid].hasBig ? 100 : 0);
        if (score > bestScore) { bestScore = score; mainPid = pid; }
      }

      var images = [];
      if (mainPid) {
        var base = byPid[mainPid].base;
        for (var n = 1; n <= byPid[mainPid].maxNum; n++) {
          images.push(base + "/images/big/" + n + ".webp");
        }
      }

      console.log("[sERP] fetchWBVariant: images=" + images.length);

      // Extract price from JSON or priceWrap HTML
      var price = "";
      var pm = html.match(/"priceToPay"\s*:\s*"(\d+)"/);
      if (pm) price = pm[1];
      else {
        var pm2 = html.match(/priceWrap--pxdH1[^>]*>[^<]*<[^>]*>[^<]*<[^>]*>[\s\S]*?(\d[\d\s]*)₽/);
        if (pm2) price = pm2[1].replace(/\s/g, "");
      }
      console.log("[sERP] fetchWBVariant: price=" + price);

      return { images: images, price: price };
    });
  }

  function collectAllVariants() {
    var variants = X.extractAll().variants;
    var stack = [];
    if (variants.colors && variants.colors.length) {
      variants.colors.forEach(function (c) { stack.push({ type: "color", value: c }); });
    } else if (variants.sizes && variants.sizes.length) {
      variants.sizes.forEach(function (s) { stack.push({ type: "size", value: s }); });
    } else if (variants.styles && variants.styles.length) {
      variants.styles.forEach(function (s) { stack.push({ type: "style", value: s }); });
    } else if (variants.skus && variants.skus.length) {
      variants.skus.forEach(function (s) { stack.push({ type: "sku", value: s }); });
    }

    if (stack.length <= 1) {
      showToast("无可遍历的变体，直接采集");
      collectCurrent();
      return;
    }

    UI.collecting = true;
    UI.cancelled = false;
    setButtons(false);
    UI.total = stack.length;

    var allVariants = [];

    // idx 0: collect current variant from live DOM (already loaded)
    var currentData = buildPayload();
    allVariants.push({
      variantName: stack[0].value,
      url: window.location.href,
      price: currentData.price,
      images: currentData.images,
      variantInfo: stack[0],
      currentVariant: currentData.currentVariant
    });
    setStatus("变体 1/" + UI.total + ": " + stack[0].value + " ✓");
    console.log("[sERP] variant 1/" + UI.total + " (current):", stack[0].value, "(" + currentData.images.length + " images)");

    if (UI.total <= 1) {
      // Only one variant — send immediately
      var batch = buildPayload();
      batch.variantData = allVariants;
      sendToSERP(batch).then(function () {
        showToast("已采集 1 个变体");
        setStatus("完成 ✓");
        UI.collecting = false;
        setButtons(true);
      });
      return;
    }

    // Fetch remaining variants
    var variantUrls = variants.urls || {};
    var colorToAsin = PLATFORM === "amazon" ? getColorToAsinFromDOM() : {};
    console.log("[sERP] variant fetch mode:", PLATFORM === "amazon" ? "ASIN" : "URL", "colorToAsin:", JSON.stringify(colorToAsin), "urls:", JSON.stringify(variantUrls));

    var pending = [];
    for (var i = 1; i < stack.length; i++) {
      (function (variantName, asin, url, idx) {
      if (!asin && !url) {
        console.warn("[sERP] No ASIN/URL found for variant:", variantName);
        return;
      }

      setStatus("变体 " + (idx + 1) + "/" + UI.total + ": 请求 " + variantName + "...");

      var fetchFn, fetchArg, resultUrl;
      if (asin) {
        fetchFn = fetchVariantData;
        fetchArg = asin;
        resultUrl = window.location.origin + "/dp/" + asin;
      } else {
        fetchFn = fetchWBVariantData;
        fetchArg = url;
        resultUrl = url;
      }

      var promise = fetchFn(fetchArg).then(function (data) {
        allVariants.push({
          variantName: variantName,
          url: resultUrl,
          price: data.price,
          images: data.images,
          variantInfo: { type: "color", value: variantName }
        });
        setStatus("变体 " + (allVariants.length) + "/" + UI.total + ": " + variantName + " ✓ (" + data.images.length + " images)");
        console.log("[sERP] variant " + (allVariants.length) + "/" + UI.total + " (fetched):", variantName, "(" + data.images.length + " images)");
      }).catch(function (err) {
        console.error("[sERP] Failed to fetch variant", variantName, ":", err.message);
        allVariants.push({
          variantName: variantName,
          url: resultUrl,
          price: "",
          images: [],
          variantInfo: { type: "color", value: variantName },
          _error: err.message
        });
        setStatus("变体 " + (allVariants.length) + "/" + UI.total + ": " + variantName + " (获取失败)");
      });

      pending.push(promise);
      })(stack[i].value, colorToAsin[stack[i].value], variantUrls[stack[i].value], i);
    }

    Promise.all(pending).then(function () {
      // Sort by original stack order
      allVariants.sort(function (a, b) {
        var ai = stack.findIndex(function (s) { return s.value === a.variantName; });
        var bi = stack.findIndex(function (s) { return s.value === b.variantName; });
        return ai - bi;
      });

      // Send batch
      var batch = buildPayload();
      batch.variantData = allVariants;
      batch.images = [];  // Top-level images are per-variant now

      console.log("[sERP] Sending batch:", allVariants.length, "variants");
      sendToSERP(batch).then(function (result) {
        if (result && result.status === "ok") {
          showToast("已采集 " + allVariants.length + " 个变体 ✓");
          setStatus("完成 " + allVariants.length + " 变体 ✓");
        } else {
          setStatus("失败", true);
        }
        UI.collecting = false;
        setButtons(true);
      }).catch(function () {
        showToast("sERP 未运行", true);
        setStatus("sERP 未运行", true);
        UI.collecting = false;
        setButtons(true);
      });
    }).catch(function (err) {
      console.error("[sERP] Batch fetch error:", err);
      UI.collecting = false;
      setButtons(true);
      setStatus("采集出错", true);
    });
  }

  // ==================== MAIN ====================

  injectUI();
  console.log("[sERP Collector] Ready — " + PLATFORM + " product page");

})();
