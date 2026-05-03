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
        var hasEnough = items.length >= 3;
        var elapsed = Date.now() - start;

        if (hasEnough && oldFingerprint) {
          // Verify images actually changed from before the click
          var curFp = getImageFingerprint();
          if (curFp && curFp !== oldFingerprint) {
            clearInterval(timer);
            resolve(true);
            return;
          }
        } else if (hasEnough) {
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
        // NEW: click the swatch li or button (NOT the hidden submit input)
        var lis = $$("#inline-twister-row-color_name li[data-asin]");
        for (var i = 0; i < lis.length; i++) {
          var img = $("img", lis[i]);
          var name = (img ? attr(img, "alt") : text(lis[i])).trim();
          if (name === value) {
            // Click the li element, which has Amazon's JS handler attached
            lis[i].click();
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
      return $$("#feature-bullets .a-list-item, #feature-bullets li").map(function (el) { return text(el); }).filter(Boolean).slice(0, 10);
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

  // ---------- Wildberries ----------
  EXTRACTORS.wildberries = {
    isProductPage: function () {
      return /\/catalog\/\d+\/detail\.aspx/.test(href);
    },

    extractTitle: function () {
      return text($(".product-page__title") || $("h1.product-title") || $("h1"));
    },

    extractPrice: function () {
      // Final price (after discounts)
      var el = $(".price-block__final-price") ||
               $(".product-page__price-block .price-block__price") ||
               $(".final-price");
      if (!el) {
        // Try the main price block
        el = $(".price-block__price");
      }
      return text(el) || "";
    },

    extractImages: function () {
      var images = [], seen = {};
      function add(url) {
        if (!url || seen[url] || url.indexOf("data:image") === 0) return;
        // WB uses image buckets, try to get high-res
        var h = url.replace(/\/c\d+x\d+\/new\//, "/c2460x3280/new/");
        if (!seen[h]) { seen[h] = true; images.push(h); }
      }
      $$(".product-page__gallery img, .j-zoom-image, .photo-list img, .carousel img").forEach(function (img) {
        add(attr(img, "data-src") || attr(img, "src") || img.src);
      });
      // Also check background images in gallery
      $$(".product-page__gallery [style*='url']").forEach(function (el) {
        var m = (el.style.backgroundImage || "").match(/url\(["']?([^"')]+)["']?\)/);
        if (m) add(m[1]);
      });
      return images;
    },

    extractVariants: function () {
      var v = {};
      var colors = $$(".color-list .j-color, .colors-list__item, .product-page__color-selector li, .swiper-slide.j-color");
      if (colors.length) v.colors = colors.map(function (el) { return attr(el, "data-color-name") || attr(el, "title") || text(el); }).filter(Boolean);
      var sizes = $$(".sizes-list .j-size, .sizes-list__item, .product-page__size-selector li");
      if (sizes.length) v.sizes = sizes.map(function (el) { return attr(el, "data-size-name") || text(el); }).filter(Boolean);
      return v;
    },

    getCurrentVariant: function () {
      var parts = [];
      var color = $(".color-list .j-color.active, .colors-list__item.selected, .j-color.active");
      if (color) parts.push(attr(color, "data-color-name") || text(color));
      var size = $(".sizes-list .j-size.active, .sizes-list__item.selected, .j-size.active");
      if (size) parts.push(attr(size, "data-size-name") || text(size));
      return parts.join(" / ") || "default";
    },

    clickVariant: function (type, value) {
      var items;
      if (type === "color") {
        items = $$(".color-list .j-color, .colors-list__item, .j-color");
      } else if (type === "size") {
        items = $$(".sizes-list .j-size, .sizes-list__item, .j-size");
      }
      if (!items) return false;
      for (var i = 0; i < items.length; i++) {
        var name = attr(items[i], "data-color-name") || attr(items[i], "data-size-name") || text(items[i]);
        if (name.trim() === value || name.indexOf(value) !== -1) {
          items[i].click();
          return true;
        }
      }
      return false;
    },

    extractBrand: function () {
      return text($(".product-page__brand a") || $(".brand-link"));
    },

    extractCategory: function () {
      return $$(".breadcrumbs__list a, .breadcrumb a").map(function (el) { return text(el); }).join(" > ");
    },

    extractRating: function () {
      return text($(".product-rating .star-rate__count") || $(".product-page__rating span"));
    },

    extractDescription: function () {
      return $$(".product-details .product-params li").map(function (el) { return text(el); }).join("; ");
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
    return {
      url: href,
      platform: PLATFORM,
      title: d.title || "",
      price: d.price || "",
      brand: d.brand || "",
      rating: d.rating || "",
      category: d.category || "",
      images: d.images || [],
      variants: d.variants || {},
      bullets: d.bullets || [],
      description: d.description || "",
      currentVariant: d.currentVariant || "",
      collectedAt: new Date().toISOString(),
    };
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

    function run(idx) {
      if (UI.cancelled || idx >= stack.length) {
        // All collected — send one batch
        var batch = buildPayload();
        batch.variantData = allVariants;

        console.log("[sERP Collector] Sending batch:", UI.total, "variants");
        sendToSERP(batch).then(function (result) {
          if (result && result.status === "ok") {
            showToast("已采集 " + UI.total + " 个变体");
            setStatus("完成 " + UI.total + " 变体 ✓");
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
        return;
      }

      setStatus("变体 " + (idx + 1) + "/" + UI.total + ": " + stack[idx].value);

      // Capture image fingerprint BEFORE clicking (to detect actual change)
      var oldFp = null;
      if (idx > 0) {
        oldFp = getImageFingerprint();
        X.clickVariant(stack[idx].type, stack[idx].value);
      }

      waitForUpdate(3000).then(function () {
        return waitForImageData(5000, oldFp);
      }).then(function (changed) {
        if (idx > 0 && !changed) {
          console.warn("[sERP Collector] Images may not have changed for:", stack[idx].value);
        }
        var data = buildPayload();
        var entry = {
          variantName: stack[idx].value,
          url: window.location.href,
          price: data.price,
          images: data.images,
          variantInfo: stack[idx],
          currentVariant: data.currentVariant,
        };
        allVariants.push(entry);
        console.log("[sERP Collector] Variant " + (idx + 1) + "/" + UI.total + ":", entry.variantName, "(" + entry.images.length + " images)");

        setTimeout(function () { run(idx + 1); }, 600);
      });
    }

    showToast("采集全部 " + UI.total + " 个变体...");
    run(0);
  }

  // ==================== MAIN ====================

  injectUI();
  console.log("[sERP Collector] Ready — " + PLATFORM + " product page");

})();
