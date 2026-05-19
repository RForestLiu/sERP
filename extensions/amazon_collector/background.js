/**
 * sERP ExtensionHelper — Service Worker
 * Proxies fetch requests from content scripts to bypass CSP/CORS restrictions.
 */
chrome.runtime.onMessage.addListener(function (request, sender, sendResponse) {
  if (request.type === "fetch") {
    var url = request.url;
    var options = request.options || {};

    console.log("[sERP BG] fetch:", options.method || "GET", url);

    fetch(url, options)
      .then(function (res) {
        return res.text().then(function (body) {
          sendResponse({
            ok: res.ok,
            status: res.status,
            statusText: res.statusText,
            body: body,
            headers: { "content-type": res.headers.get("content-type") || "" }
          });
        });
      })
      .catch(function (err) {
        console.error("[sERP BG] fetch error:", err.message);
        sendResponse({ ok: false, status: 0, statusText: err.message, body: "" });
      });

    return true; // Keep channel open for async response
  }
});
