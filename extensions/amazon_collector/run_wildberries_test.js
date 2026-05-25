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
    "  window.__serpTest = { buildPayload: buildPayload, extractor: X };\n" +
    extCode.substring(iifeEnd);

  const browser = await puppeteer.launch({ headless: true, args: ["--no-sandbox", "--disable-setuid-sandbox"] });
  const page = await browser.newPage();
  try {
    await page.goto("file:///" + testFile.replace(/\\/g, "/"), { waitUntil: "load" });
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
