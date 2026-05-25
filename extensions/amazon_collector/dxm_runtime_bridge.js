(function () {
  "use strict";

  var RESPONSE_TYPE = "SERP_DXM_RUNTIME_FIELD_MODEL";
  var REQUEST_TYPE = "SERP_DXM_RUNTIME_REQUEST";

  function inferControlKind(attr) {
    if (!attr) return "unknown";
    var dictionaryId = String(attr.dictionaryId || attr.dictionaryIdStr || "0");
    var isDictionary = dictionaryId !== "" && dictionaryId !== "0" && dictionaryId !== "null" && dictionaryId !== "undefined";
    var maxValueCount = attr.maxValueCount;
    var isCollection = !!attr.collection || (maxValueCount !== undefined && maxValueCount !== null && String(maxValueCount) !== "0" && String(maxValueCount) !== "1");
    var isRemote = !!attr._remoteSearch || !!attr._searchFlag;
    var valueType = String(attr.type || "").toLowerCase();
    if (isDictionary && isCollection && isRemote) return "dictionary-multiple-remote";
    if (isDictionary && isCollection) return "dictionary-multiple";
    if (isDictionary && isRemote) return "dictionary-single-remote";
    if (isDictionary) return "dictionary-single";
    if (valueType === "decimal" || valueType === "integer" || valueType === "number" || valueType === "double") return "number-input";
    return "text-input";
  }

  function compactAttr(attr, sourceGroup) {
    if (!attr) return null;
    return {
      sourceGroup: sourceGroup,
      id: String(attr.id || ""),
      attributeId: String(attr.attributeId || attr.attributeIdStr || ""),
      name: attr.name || "",
      nameCn: attr.nameCn || "",
      type: attr.type || "",
      collection: attr.collection,
      required: attr.required,
      dictionaryId: String(attr.dictionaryId || attr.dictionaryIdStr || "0"),
      propertyType: attr.propertyType,
      optionsNum: attr.optionsNum,
      maxValueCount: attr.maxValueCount,
      _inputType: attr._inputType,
      _compType: attr._compType,
      _searchFlag: attr._searchFlag,
      _remoteSearch: attr._remoteSearch,
      dxmControlKind: inferControlKind(attr)
    };
  }

  function readRuntimeModel() {
    var appEl = document.querySelector("#app") || document.querySelector("[data-v-app]") || document.body.firstElementChild;
    var app = appEl && appEl.__vue_app__;
    var pinia = app && app.config && app.config.globalProperties && app.config.globalProperties.$pinia;
    var store = pinia && pinia._s && pinia._s.get && pinia._s.get("ozonProductAddStore");
    var attrsInfo = store && store.$state && store.$state.attrsInfo;
    var fields = [];
    ["attrsList", "mergeAttrsList", "skuList"].forEach(function (groupName) {
      var list = attrsInfo && Array.isArray(attrsInfo[groupName]) ? attrsInfo[groupName] : [];
      list.forEach(function (attr) {
        var meta = compactAttr(attr, groupName);
        if (meta && meta.attributeId) fields.push(meta);
      });
    });
    return {
      flags: {
        showProductVideo: !!(attrsInfo && attrsInfo.showProductVideo),
        showDesc: !!(attrsInfo && attrsInfo.showDesc),
        showQualification: !!(attrsInfo && attrsInfo.showQualification),
        showSizeTable: !!(attrsInfo && attrsInfo.showSizeTable),
        showRichJSON: !!(attrsInfo && attrsInfo.showRichJSON)
      },
      fields: fields
    };
  }

  function emitRuntimeModel() {
    try {
      window.postMessage({ type: RESPONSE_TYPE, model: readRuntimeModel() }, "*");
    } catch (e) {
      window.postMessage({ type: RESPONSE_TYPE, model: { flags: {}, fields: [] }, error: String(e && e.message || e) }, "*");
    }
  }

  window.addEventListener("message", function (event) {
    if (event.source !== window) return;
    var data = event.data || {};
    if (data.type === REQUEST_TYPE) emitRuntimeModel();
  });

  emitRuntimeModel();
  setTimeout(emitRuntimeModel, 800);
  setTimeout(emitRuntimeModel, 2500);
})();
