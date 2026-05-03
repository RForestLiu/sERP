/**
 * Background service worker.
 * Uses chrome.debugger to intercept network requests from shopping platform tabs.
 * This catches dianxiaomi extension API calls that page-injection can't see.
 */
const SERP_URL = "http://localhost:5000/api/collect/dxm_capture";

// Shopping platforms where dianxiaomi extension is used
const SHOPPING_DOMAINS = ["amazon.", "ozon.", "wildberries.", "ebay.", "aliexpress.", "temu.", "shopee.", "lazada."];

const DIANXIAOMI_PATTERN = /dianxiaomi\.com/i;

let attachedTabId = null;
let pendingRequests = {};
let msgId = 1;

function isShoppingSite(url) {
  if (!url) return false;
  var u = url.toLowerCase();
  return SHOPPING_DOMAINS.some(function (d) { return u.indexOf(d) !== -1; });
}

// Attach debugger to a shopping tab
function attachToTab(tabId) {
  if (attachedTabId === tabId) return;
  detachFromTab();

  chrome.debugger.attach({ tabId: tabId }, "1.3", function () {
    if (chrome.runtime.lastError) {
      console.log("[sERP Bridge] Debugger attach failed:", chrome.runtime.lastError.message);
      return;
    }
    attachedTabId = tabId;
    console.log("[sERP Bridge] Debugger attached to tab", tabId);

    chrome.debugger.sendCommand({ tabId: tabId }, "Network.enable", {}, function () {
      console.log("[sERP Bridge] Network.enable sent");
    });
  });
}

function detachFromTab() {
  if (attachedTabId !== null) {
    chrome.debugger.detach({ tabId: attachedTabId }, function () {
      if (chrome.runtime.lastError) {
        // Tab may already be closed
      }
    });
    attachedTabId = null;
    pendingRequests = {};
  }
}

// Auto-attach when user navigates to a shopping site
chrome.tabs.onUpdated.addListener(function (tabId, changeInfo, tab) {
  if (changeInfo.status === "complete" && isShoppingSite(tab.url)) {
    attachToTab(tabId);
  }
});

// Auto-attach when user switches to a shopping tab
chrome.tabs.onActivated.addListener(function (activeInfo) {
  chrome.tabs.get(activeInfo.tabId, function (tab) {
    if (chrome.runtime.lastError) return;
    if (isShoppingSite(tab.url)) {
      attachToTab(activeInfo.tabId);
    } else {
      detachFromTab();
    }
  });
});

// Detach when tab is closed
chrome.tabs.onRemoved.addListener(function (tabId) {
  if (tabId === attachedTabId) {
    attachedTabId = null;
    pendingRequests = {};
  }
});

// Handle debugger events
chrome.debugger.onEvent.addListener(function (source, method, params) {
  if (source.tabId !== attachedTabId) return;

  if (method === "Network.requestWillBeSent") {
    var req = params.request;
    if (req && DIANXIAOMI_PATTERN.test(req.url)) {
      pendingRequests[params.requestId] = {
        url: req.url,
        method: req.method,
        postData: params.request ? params.request.postData : null,
      };

      var postBody = null;
      if (req.postData) {
        try { postBody = JSON.parse(req.postData); } catch (e) { /* not JSON */ }
      }

      forwardToSERP({
        url: req.url,
        method: req.method,
        status: 0,
        requestBody: postBody,
        responseBody: null,
        capturedVia: "debugger",
        timestamp: new Date().toISOString(),
      });
    }
  }

  if (method === "Network.responseReceived") {
    if (pendingRequests[params.requestId]) {
      // Get response body
      chrome.debugger.sendCommand(
        { tabId: source.tabId },
        "Network.getResponseBody",
        { requestId: params.requestId },
        function (result) {
          if (chrome.runtime.lastError || !result) return;

          var info = pendingRequests[params.requestId];
          var text = result.body || "";
          var body = null;
          try { body = JSON.parse(text); } catch (e) { /* not JSON */ }

          forwardToSERP({
            url: info.url,
            method: info.method,
            status: params.response.status,
            requestBody: null,
            responseBody: body || null,
            responseText: body ? null : text.substring(0, 100000),
            capturedVia: "debugger",
            timestamp: new Date().toISOString(),
          });

          delete pendingRequests[params.requestId];
        }
      );
    }
  }
});

// Forward to sERP
function forwardToSERP(entry) {
  fetch(SERP_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(entry),
  }).then(function (r) {
    return r.json();
  }).then(function (result) {
    if (result.status === "ok") {
      console.log("[sERP Bridge] Captured:", result.title || entry.url.substring(0, 80));
    }
  }).catch(function (e) {
    // sERP not reachable — silent
  });
}

// Also listen for content script messages (dianxiaomi.com pages)
chrome.runtime.onMessage.addListener(function (message, sender, sendResponse) {
  if (message.type === "dxm_api_response") {
    forwardToSERP({
      url: message.payload.url,
      method: message.payload.method,
      status: message.payload.status,
      requestBody: message.payload.requestBody || null,
      responseBody: message.payload.responseBody || null,
      responseText: message.payload.responseText || null,
      capturedVia: "pageInjection",
      timestamp: new Date().toISOString(),
    });
  }
});

console.log("[sERP Bridge] Background started — debugger + page injection");
