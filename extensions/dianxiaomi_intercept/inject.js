/**
 * Injected into ALL page contexts.
 * Intercepts XHR/fetch calls targeting dianxiaomi.com domains.
 */
(function () {
  var DIANXIAOMI_DOMAINS = /dianxiaomi\.com/i;
  var captureCount = 0;
  var MAX_BODY = 500000;

  function isDianxiaomiAPI(url) {
    return DIANXIAOMI_DOMAINS.test(url);
  }

  function forwardToSERP(data) {
    captureCount++;
    window.postMessage(
      { source: "serp-dxm-bridge", type: "dxm_api_response", payload: data },
      "*"
    );
  }

  function tryParseJSON(text) {
    if (!text || typeof text !== "string") return null;
    text = text.trim();
    if (!text.startsWith("{") && !text.startsWith("[")) return null;
    try { return JSON.parse(text); } catch (e) { return null; }
  }

  function buildEntry(url, method, status, reqBody, respText) {
    var entry = { url: url, method: method, status: status, requestBody: reqBody || null };
    var parsed = tryParseJSON(respText);
    if (parsed) {
      entry.responseBody = parsed;
    } else if (respText) {
      entry.responseText = respText.substring(0, MAX_BODY);
    }
    return entry;
  }

  // --- XHR ---
  var XHR = XMLHttpRequest.prototype;
  var origOpen = XHR.open;
  var origSend = XHR.send;

  XHR.open = function (method, url) {
    this._serp = { method: method, url: url };
    return origOpen.apply(this, arguments);
  };

  XHR.send = function (body) {
    var self = this;
    var meta = this._serp || {};
    meta.body = body;
    if (!isDianxiaomiAPI(meta.url)) return origSend.apply(this, arguments);

    this.addEventListener("load", function () {
      forwardToSERP(buildEntry(meta.url, meta.method, self.status, meta.body, self.responseText));
    });
    return origSend.apply(this, arguments);
  };

  // --- fetch ---
  var origFetch = window.fetch;
  window.fetch = function (input, init) {
    var url = typeof input === "string" ? input : (input && input.url);
    var method = (init && init.method) || "GET";
    var body = init && init.body;

    return origFetch.apply(this, arguments).then(function (response) {
      if (!isDianxiaomiAPI(url)) return response;
      var cloned = response.clone();
      cloned.text().then(function (text) {
        forwardToSERP(buildEntry(url, method, cloned.status, body, text));
      }).catch(function () {});
      return response;
    });
  };
})();
