const puppeteer = require("C:/Users/Administrator/AppData/Roaming/npm/node_modules/@modelcontextprotocol/server-puppeteer/node_modules/puppeteer");
const path = require("path");
const fs = require("fs");

(async () => {
  const dir = __dirname;
  const testFile = path.resolve(dir, "test_ozon_fill.html");
  const extFile = path.resolve(dir, "dianxiaomi_ozon.js");

  console.log("Reading extension code...");
  let extCode = fs.readFileSync(extFile, "utf-8");
  // Strip outer IIFE: comment... (function () { "use strict"; ... })();
  // The file has a JSDoc comment before the IIFE, so don't anchor to ^
  var iifeIdx = extCode.indexOf("(function () {");
  if (iifeIdx >= 0) {
    extCode = extCode.substring(0, iifeIdx) + extCode.substring(iifeIdx + "(function () {".length);
  }
  // Remove trailing })();
  var iifeEnd = extCode.lastIndexOf("})();");
  if (iifeEnd >= 0) {
    extCode = extCode.substring(0, iifeEnd) + extCode.substring(iifeEnd + "})();".length);
  }
  extCode = extCode.replace(/["']use strict["'];\s*/, "");

  // Cut at the init/event-binding block (after all function definitions)
  var cutMarker = "// ==================== 事件绑定 ====================";
  var cutIdx = extCode.indexOf(cutMarker);
  if (cutIdx > 0) {
    extCode = extCode.substring(0, cutIdx).trimEnd();
    console.log("Stripped init block, kept", extCode.length, "chars");
  } else {
    console.log("WARNING: init block marker not found, using full code");
  }

  console.log("Launching browser...");
  const browser = await puppeteer.launch({
    headless: true,
    args: ["--no-sandbox", "--disable-setuid-sandbox"],
  });

  const page = await browser.newPage();

  // Collect console messages
  const logs = [];
  page.on("console", (msg) => {
    logs.push(`[${msg.type()}] ${msg.text()}`);
  });

  // Collect page errors
  const errors = [];
  page.on("pageerror", (err) => {
    errors.push(`PAGE ERROR: ${err.message}`);
  });

  try {
    console.log("Loading test page:", testFile);
    await page.goto("file:///" + testFile.replace(/\\/g, "/"), {
      waitUntil: "load",
    });

    // Inject extension code AFTER page load
    console.log("Injecting extension code...");
    await page.evaluate(extCode);
    console.log("Extension code injected");

    // Run the tests explicitly
    await page.evaluate(() => { runTests(); });
    console.log("Tests triggered");

    // Wait for tests to complete
    await new Promise((r) => setTimeout(r, 1000));

    // Extract test results from DOM
    const results = await page.evaluate(() => {
      const resultDivs = document.querySelectorAll("#results .result");
      const items = [];
      resultDivs.forEach((d) => {
        items.push(d.textContent.trim());
      });
      const passDivs = document.querySelectorAll("#results .pass");
      const failDivs = document.querySelectorAll("#results .fail");
      return {
        items,
        passCount: passDivs.length,
        failCount: failDivs.length,
      };
    });

    console.log("\n=== TEST RESULTS ===");
    results.items.forEach((line) => console.log(line));
    console.log(
      `\n=== SUMMARY: ${results.passCount} pass, ${results.failCount} fail ===`
    );

    // Show relevant console logs
    console.log("\n--- Console output ---");
    logs.forEach((l) => {
      if (
        l.includes("测试") ||
        l.includes("字段") ||
        l.includes("fill") ||
        l.includes("collect") ||
        l.includes("选择器") ||
        l.includes("ERROR") ||
        l.includes("error") ||
        l.includes("✅") ||
        l.includes("❌") ||
        l.includes("[test]") ||
        l.includes("[sERP]") ||
        l.includes("[mock]")
      ) {
        console.log(l);
      }
    });

    if (errors.length > 0) {
      console.log("\n--- Page Errors ---");
      errors.forEach((e) => console.log(e));
    }

    const failCount = results.failCount || 0;
    process.exit(failCount > 0 ? 1 : 0);
  } catch (err) {
    console.error("Test run failed:", err.message);
    console.error(err.stack);
    process.exit(2);
  } finally {
    await browser.close();
  }
})();
