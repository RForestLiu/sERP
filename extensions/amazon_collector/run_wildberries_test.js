const puppeteer = require("C:/Users/Administrator/AppData/Roaming/npm/node_modules/@modelcontextprotocol/server-puppeteer/node_modules/puppeteer");
const path = require("path");
const fs = require("fs");

(async () => {
  const dir = __dirname;
  const testFile = path.resolve(dir, "test_wildberries_collect.html");
  const extFile = path.resolve(dir, "content.js");

  let extCode = fs.readFileSync(extFile, "utf-8");
  extCode = extCode.replace("  const host = window.location.hostname;", '  const host = "www.wildberries.ru";');
  extCode = extCode.replace("  const href = window.location.href;", '  const href = "https://www.wildberries.ru/catalog/156681979/detail.aspx?targetUrl=MI";');

  const mainIdx = extCode.indexOf("  // ==================== MAIN ====================");
  const iifeEnd = extCode.lastIndexOf("})();");
  if (mainIdx < 0 || iifeEnd < 0) throw new Error("Unable to locate content.js main block");
  extCode = extCode.substring(0, mainIdx) +
    "  window.__serpTest = { buildPayload: buildPayload, collectAllVariants: collectAllVariants, continueWBTraversal: continueWBTraversal, injectUI: injectUI, extractor: X };\n" +
    extCode.substring(iifeEnd);

  const browser = await puppeteer.launch({ headless: true, args: ["--no-sandbox", "--disable-setuid-sandbox"] });
  const page = await browser.newPage();
  try {
    await page.goto("file:///" + testFile.replace(/\\/g, "/"), { waitUntil: "load" });
    await page.evaluate(() => {
      window.__serpStorageSet = null;
      window.chrome = {
        storage: {
          local: {
            set(obj, cb) {
              window.__serpStorageSet = obj;
            },
            remove(_key, cb) {
              if (cb) cb();
            },
          },
        },
      };
    });
    await page.evaluate(extCode);
    const payload = await page.evaluate(() => window.__serpTest.buildPayload());

    const failures = [];
    function assert(name, condition, detail) {
      if (!condition) failures.push(name + (detail ? ": " + detail : ""));
    }

    assert("drawer button was clicked and description collected", payload.product_description.indexOf("Компактная сумка") !== -1, payload.product_description);
    assert("color spec collected", payload.product_details["цвет"] === "черный", JSON.stringify(payload.product_details));
    assert("material spec collected", payload.product_details["материал"] === "экокожа", JSON.stringify(payload.product_details));
    assert("height spec collected", payload.product_details["высота_предмета"] === "21 см", JSON.stringify(payload.product_details));
    assert("width spec collected", payload.product_details["ширина_предмета"] === "17 см", JSON.stringify(payload.product_details));
    assert("current product images only use current nm-id", payload.images.length === 2 && payload.images.every((url) => url.includes("/156681979/images/big/")) && payload.images.indexOf("https://basket-12.wbbasket.ru/vol1566/part156681/156681979/images/big/2.webp") === -1, JSON.stringify(payload.images));
    assert("all color links are kept as separate variants", payload.variants.colors.length === 8, JSON.stringify(payload.variants));
    assert("variant labels do not use material as color", payload.variants.colors.indexOf("кожа") === -1, JSON.stringify(payload.variants));
    assert("duplicate color variants get unique labels", payload.variants.colors.indexOf("черный") !== -1 && payload.variants.colors.indexOf("черный_175655484") !== -1, JSON.stringify(payload.variants));

    const traversalState = await page.evaluate(async () => {
      window.__serpTest.injectUI();
      window.__serpTest.collectAllVariants();
      await new Promise((resolve) => setTimeout(resolve, 50));
      const stateObj = window.__serpStorageSet || {};
      return stateObj.serp_wb_traversal || null;
    });
    const firstVariant = traversalState && traversalState.allVariants && traversalState.allVariants[0];
    assert("all specs traversal state created", !!traversalState, JSON.stringify(traversalState));
    assert("all specs current variant has product details", firstVariant && firstVariant.product_details && firstVariant.product_details["цвет"] === "черный", JSON.stringify(firstVariant));
    assert("all specs current variant has product description", firstVariant && firstVariant.product_description && firstVariant.product_description.indexOf("Компактная сумка") !== -1, JSON.stringify(firstVariant));

    const twoVariantBatch = await page.evaluate(async () => {
      window.__serpSentPayload = null;
      window.fetch = (_url, opts) => {
        window.__serpSentPayload = JSON.parse(opts.body);
        return Promise.resolve({ json: () => Promise.resolve({ status: "ok" }) });
      };
      const state = {
        platform: "wildberries",
        variantUrls: {
          first: "https://www.wildberries.ru/catalog/156681979/detail.aspx",
          second: "https://www.wildberries.ru/catalog/175655484/detail.aspx",
        },
        stack: [{ type: "color", value: "first" }, { type: "color", value: "second" }],
        allVariants: [{ variantName: "first", url: "about:blank", price: "", images: ["first.webp"], variantInfo: { type: "color", value: "first" } }],
        originalUrl: window.location.href.split("#")[0] + "#done",
        total: 2,
        nextIdx: 1,
      };
      window.__serpTest.continueWBTraversal(state);
      await new Promise((resolve) => setTimeout(resolve, 100));
      return window.__serpSentPayload;
    });
    assert("two variant traversal does not duplicate current variant", twoVariantBatch && twoVariantBatch.variantData && twoVariantBatch.variantData.length === 2, JSON.stringify(twoVariantBatch && twoVariantBatch.variantData));
    assert("two variant traversal collects the pending second variant", twoVariantBatch && twoVariantBatch.variantData && twoVariantBatch.variantData.map((v) => v.variantName).join(",") === "first,second", JSON.stringify(twoVariantBatch && twoVariantBatch.variantData));

    if (failures.length) {
      console.error("Wildberries collect test failed:");
      failures.forEach((failure) => console.error(" - " + failure));
      process.exit(1);
    }
    console.log("Wildberries collect test passed");
  } catch (err) {
    console.error("Wildberries collect test error:", err.message);
    console.error(err.stack);
    process.exit(2);
  } finally {
    await browser.close();
  }
})();
