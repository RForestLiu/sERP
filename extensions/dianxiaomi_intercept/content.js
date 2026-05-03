/**
 * Content script — runs in isolated world on dianxiaomi.com pages.
 * Injects the interceptor into the page context and relays messages to background.
 */

console.log("[sERP Bridge] Content script loaded on:", window.location.href);

// Inject the interceptor script into the page context
function injectScript() {
  var script = document.createElement("script");
  script.src = chrome.runtime.getURL("inject.js");
  script.onload = function () {
    console.log("[sERP Bridge] inject.js loaded successfully");
    script.remove();
  };
  script.onerror = function () {
    console.error("[sERP Bridge] Failed to load inject.js!");
  };
  (document.head || document.documentElement).appendChild(script);
}

injectScript();

// Listen for messages from the injected page-context script
window.addEventListener("message", function (event) {
  if (event.source !== window) return;
  var data = event.data;
  if (data && data.source === "serp-dxm-bridge") {
    if (data.type === "dxm_api_response") {
      console.log("[sERP Bridge] Intercepted API call:", data.payload.url);
    }
    chrome.runtime.sendMessage(data).catch(function (err) {
      console.warn("[sERP Bridge] sendMessage failed:", err.message);
    });
  }
});
