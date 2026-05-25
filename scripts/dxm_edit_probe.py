"""Read-only CDP probe for Dianxiaomi Ozon edit pages.

The probe inspects the already-open edit page in a Chrome instance launched
with --remote-debugging-port. It does not click buttons or submit data.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

import aiohttp


CDP_HOST = "127.0.0.1"
CDP_PORT = 9222
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "cdp_dump"


STORE_IDS = [
    "ozonProductAddStore",
    "ozonProductBasicStore",
    "ozonProductStore",
    "ozonProductSkuDataStore",
    "ozonProductDescStore",
    "ozonProductSkuAttrStore",
    "ozonProductDxmInfoStore",
    "ozonProductPointsInfoStore",
]


def safe_json_loads(value: Any, default: Any = None) -> Any:
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str):
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def extract_product_id(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query)
    values = query.get("id") or []
    return values[0] if values else ""


def _compact_values(values: Any) -> list[dict[str, Any]]:
    if not isinstance(values, list):
        return []
    compact = []
    for item in values:
        if not isinstance(item, dict):
            continue
        compact.append({
            "dictionary_value_id": item.get("dictionary_value_id"),
            "value": item.get("value"),
        })
    return compact


def _compact_attribute(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(item.get("id") or item.get("attribute_id") or item.get("attributeId") or ""),
        "complex_id": item.get("complex_id", item.get("complexId", 0)),
        "values": _compact_values(item.get("values")),
    }


def _split_images(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value if v]
    if not isinstance(value, str) or not value:
        return []
    return [part for part in value.split(";") if part]


def _compact_variant(item: dict[str, Any]) -> dict[str, Any]:
    attrs = safe_json_loads(item.get("variantAttribute"), [])
    warehouse = safe_json_loads(item.get("warehouseInventory"), [])
    images = _split_images(item.get("images"))
    return {
        "id": str(item.get("id") or item.get("idStr") or ""),
        "sku": item.get("sku"),
        "price": item.get("price"),
        "salePrice": item.get("salePrice"),
        "minPrice": item.get("minPrice"),
        "quantity": item.get("quantity"),
        "mainImage": item.get("mainImage"),
        "image_count": len(images),
        "variantAttribute": [_compact_attribute(attr) for attr in attrs if isinstance(attr, dict)],
        "warehouseInventory": warehouse if isinstance(warehouse, list) else [],
        "width": item.get("width"),
        "depth": item.get("depth"),
        "height": item.get("height"),
        "dimensionUnit": item.get("dimensionUnit"),
        "weight": item.get("weight"),
        "weightUnit": item.get("weightUnit"),
    }


def summarize_product_response(response: dict[str, Any]) -> dict[str, Any]:
    data = response.get("data") if isinstance(response, dict) else {}
    data = data if isinstance(data, dict) else {}
    product = data.get("product") if isinstance(data.get("product"), dict) else {}

    attrs = safe_json_loads(product.get("attribute"), [])
    merge_attrs = safe_json_loads(product.get("mergeAttribute"), [])
    category_list = safe_json_loads(data.get("categoryList"), [])
    variants = product.get("variantList") or safe_json_loads(product.get("variantListStr"), [])
    content = safe_json_loads(product.get("content"), None)

    return {
        "product": {
            "id": str(product.get("id") or ""),
            "shopId": str(product.get("shopId") or ""),
            "productId": str(product.get("productId") or ""),
            "offerId": product.get("offerId"),
            "name": product.get("name"),
            "brand": product.get("brand"),
            "brandId": product.get("brandId"),
            "dxmState": product.get("dxmState"),
            "productStatus": product.get("productStatus"),
        },
        "category": {
            "descriptionCategoryId": str(product.get("descriptionCategoryId") or ""),
            "typeId": str(product.get("typeId") or ""),
            "newCategoryId": str(product.get("newCategoryId") or ""),
            "categoryList": category_list if isinstance(category_list, list) else [],
        },
        "attributes": {
            "count": len(attrs) if isinstance(attrs, list) else 0,
            "items": [_compact_attribute(attr) for attr in attrs if isinstance(attr, dict)],
        },
        "merge_attributes": {
            "count": len(merge_attrs) if isinstance(merge_attrs, list) else 0,
            "items": [_compact_attribute(attr) for attr in merge_attrs if isinstance(attr, dict)],
        },
        "rich_content": {
            "present": isinstance(content, dict),
            "version": content.get("version") if isinstance(content, dict) else None,
            "block_count": len(content.get("content", [])) if isinstance(content, dict) and isinstance(content.get("content"), list) else 0,
        },
        "variants": {
            "count": len(variants) if isinstance(variants, list) else 0,
            "items": [_compact_variant(item) for item in variants if isinstance(item, dict)],
        },
    }


def infer_control_kind(attr: dict[str, Any]) -> str:
    dictionary_id = str(attr.get("dictionaryId") or attr.get("dictionaryIdStr") or "0")
    is_dictionary = dictionary_id not in ("", "0", "None")
    is_collection = bool(attr.get("collection")) or (attr.get("maxValueCount") or 0) not in (0, 1, "0", "1", None)
    is_remote = bool(attr.get("_remoteSearch")) or bool(attr.get("_searchFlag"))
    value_type = str(attr.get("type") or "").lower()

    if is_dictionary and is_collection and is_remote:
        return "dictionary-multiple-remote"
    if is_dictionary and is_collection:
        return "dictionary-multiple"
    if is_dictionary and is_remote:
        return "dictionary-single-remote"
    if is_dictionary:
        return "dictionary-single"
    if value_type in ("decimal", "integer", "number", "double"):
        return "number-input"
    return "text-input"


def _compact_attr_meta(attr: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(attr.get("id") or ""),
        "attributeId": str(attr.get("attributeId") or attr.get("attributeIdStr") or ""),
        "name": attr.get("name"),
        "nameCn": attr.get("nameCn"),
        "type": attr.get("type"),
        "collection": attr.get("collection"),
        "required": attr.get("required"),
        "dictionaryId": str(attr.get("dictionaryId") or attr.get("dictionaryIdStr") or "0"),
        "propertyType": attr.get("propertyType"),
        "optionsNum": attr.get("optionsNum"),
        "maxValueCount": attr.get("maxValueCount"),
        "_inputType": attr.get("_inputType"),
        "_compType": attr.get("_compType"),
        "_searchFlag": attr.get("_searchFlag"),
        "_remoteSearch": attr.get("_remoteSearch"),
        "controlKind": infer_control_kind(attr),
    }


def summarize_attrs_info(attrs_info: dict[str, Any]) -> dict[str, Any]:
    attrs_info = attrs_info if isinstance(attrs_info, dict) else {}
    groups: dict[str, dict[str, Any]] = {}
    for key in ("attrsList", "mergeAttrsList", "skuList"):
        items = attrs_info.get(key)
        if not isinstance(items, list):
            items = []
        groups[key] = {
            "count": len(items),
            "items": [_compact_attr_meta(item) for item in items if isinstance(item, dict)],
        }
    return {
        "flags": {
            "showProductVideo": bool(attrs_info.get("showProductVideo")),
            "showDesc": bool(attrs_info.get("showDesc")),
            "showQualification": bool(attrs_info.get("showQualification")),
            "showSizeTable": bool(attrs_info.get("showSizeTable")),
            "showRichJSON": bool(attrs_info.get("showRichJSON")),
        },
        "groups": groups,
    }


def summarize_store_state(store_snapshot: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for store_id, state in store_snapshot.items():
        if not isinstance(state, dict):
            out[store_id] = state
            continue
        out[store_id] = {
            "stateKeys": state.get("stateKeys", []),
            "fields": state.get("fields", {}),
        }
        attrs_info = state.get("attrsInfo")
        if store_id == "ozonProductAddStore" and isinstance(attrs_info, dict):
            out[store_id]["attrsInfo"] = summarize_attrs_info(attrs_info)
    return out


def _values_by_attribute(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    by_id: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        attr_id = str(item.get("id") or "")
        if attr_id:
            by_id[attr_id] = item.get("values") if isinstance(item.get("values"), list) else []
    return by_id


def _sku_values_by_attribute(variants: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    by_id: dict[str, list[dict[str, Any]]] = {}
    for variant in variants:
        sku = variant.get("sku")
        for attr in variant.get("variantAttribute", []):
            if not isinstance(attr, dict):
                continue
            attr_id = str(attr.get("id") or "")
            if not attr_id:
                continue
            by_id.setdefault(attr_id, []).append({
                "sku": sku,
                "values": attr.get("values") if isinstance(attr.get("values"), list) else [],
            })
    return by_id


def _field_from_meta(
    meta: dict[str, Any],
    source_group: str,
    current_values: list[dict[str, Any]] | None = None,
    sku_values: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    field = {
        "sourceGroup": source_group,
        "attributeId": str(meta.get("attributeId") or ""),
        "name": meta.get("name"),
        "nameCn": meta.get("nameCn"),
        "type": meta.get("type"),
        "required": meta.get("required"),
        "collection": meta.get("collection"),
        "dictionaryId": str(meta.get("dictionaryId") or "0"),
        "propertyType": meta.get("propertyType"),
        "optionsNum": meta.get("optionsNum"),
        "maxValueCount": meta.get("maxValueCount"),
        "_inputType": meta.get("_inputType"),
        "_compType": meta.get("_compType"),
        "_searchFlag": meta.get("_searchFlag"),
        "_remoteSearch": meta.get("_remoteSearch"),
        "controlKind": meta.get("controlKind") or infer_control_kind(meta),
    }
    if current_values is not None:
        field["currentValues"] = current_values
    if sku_values is not None:
        field["skuValues"] = sku_values
    return field


def build_field_model(report: dict[str, Any]) -> dict[str, Any]:
    product_summary = report.get("product_summary") if isinstance(report, dict) else {}
    product_summary = product_summary if isinstance(product_summary, dict) else {}
    store_summary = report.get("store_summary") if isinstance(report, dict) else {}
    store_summary = store_summary if isinstance(store_summary, dict) else {}
    attrs_info = (
        store_summary.get("ozonProductAddStore", {})
        .get("attrsInfo", {})
    )
    groups = attrs_info.get("groups", {}) if isinstance(attrs_info, dict) else {}

    product_attr_values = _values_by_attribute(product_summary.get("attributes", {}).get("items", []))
    merge_attr_values = _values_by_attribute(product_summary.get("merge_attributes", {}).get("items", []))
    sku_attr_values = _sku_values_by_attribute(product_summary.get("variants", {}).get("items", []))

    fields: list[dict[str, Any]] = []
    for group_name, current_map, sku_map in (
        ("attrsList", product_attr_values, None),
        ("mergeAttrsList", merge_attr_values, None),
        ("skuList", {}, sku_attr_values),
    ):
        items = groups.get(group_name, {}).get("items", [])
        if not isinstance(items, list):
            continue
        for meta in items:
            if not isinstance(meta, dict):
                continue
            attr_id = str(meta.get("attributeId") or "")
            fields.append(_field_from_meta(
                meta,
                group_name,
                current_values=current_map.get(attr_id, []) if sku_map is None else None,
                sku_values=sku_map.get(attr_id, []) if sku_map is not None else None,
            ))

    category = product_summary.get("category") if isinstance(product_summary.get("category"), dict) else {}
    rich_content = product_summary.get("rich_content") if isinstance(product_summary.get("rich_content"), dict) else {}
    return {
        "captured_at": report.get("captured_at"),
        "product_id": report.get("product_id"),
        "page_url": report.get("page_url"),
        "category": {
            "descriptionCategoryId": category.get("descriptionCategoryId", ""),
            "typeId": category.get("typeId", ""),
            "newCategoryId": category.get("newCategoryId", ""),
            "categoryList": category.get("categoryList", []),
        },
        "flags": {
            "richContentPresent": bool(rich_content.get("present")),
            "richContentBlockCount": rich_content.get("block_count", 0),
        },
        "counts": {
            "product_attributes": len(groups.get("attrsList", {}).get("items", []) or []),
            "merge_attributes": len(groups.get("mergeAttrsList", {}).get("items", []) or []),
            "sku_attributes": len(groups.get("skuList", {}).get("items", []) or []),
        },
        "fields": fields,
    }


def cdp_json_url(host: str, port: int) -> str:
    return f"http://{host}:{port}/json"


def load_targets(host: str = CDP_HOST, port: int = CDP_PORT) -> list[dict[str, Any]]:
    with urllib.request.urlopen(cdp_json_url(host, port), timeout=3) as resp:
        return json.loads(resp.read().decode("utf-8"))


def select_edit_target(targets: list[dict[str, Any]], product_id: str = "") -> dict[str, Any]:
    page_targets = [t for t in targets if t.get("type") == "page"]
    for target in page_targets:
        url = target.get("url", "")
        if "dianxiaomi.com/web/ozonProduct/edit" in url and (not product_id or product_id in url):
            return target
    raise RuntimeError("No Dianxiaomi Ozon edit page found on the CDP target list")


async def evaluate_json(ws: aiohttp.ClientWebSocketResponse, expression: str, msg_id: int) -> tuple[Any, int]:
    await ws.send_json({
        "id": msg_id,
        "method": "Runtime.evaluate",
        "params": {
            "expression": expression,
            "awaitPromise": True,
            "returnByValue": True,
        },
    })
    while True:
        msg = await ws.receive_json()
        if msg.get("id") != msg_id:
            continue
        result = msg.get("result", {}).get("result", {})
        if "exceptionDetails" in msg.get("result", {}):
            raise RuntimeError(str(msg["result"]["exceptionDetails"]))
        value = result.get("value")
        return safe_json_loads(value, value), msg_id + 1


def build_product_fetch_expression(product_id: str) -> str:
    url = f"https://www.dianxiaomi.com/api/ozonProduct/add.json?id={product_id}"
    return f"""
    (async () => {{
      const res = await fetch({json.dumps(url)}, {{ credentials: "include" }});
      const text = await res.text();
      let body;
      try {{ body = JSON.parse(text); }} catch (e) {{ body = {{ raw: text.slice(0, 1000) }}; }}
      return JSON.stringify({{ url: {json.dumps(url)}, status: res.status, body }});
    }})()
    """


def build_store_snapshot_expression(store_ids: list[str]) -> str:
    return f"""
    (() => {{
      const ids = {json.dumps(store_ids)};
      const appEl = document.querySelector("#app") || document.querySelector("[data-v-app]") || document.body.firstElementChild;
      const app = appEl && appEl.__vue_app__;
      const pinia = app && app.config && app.config.globalProperties && app.config.globalProperties.$pinia;
      function keys(o) {{ try {{ return Object.keys(o || {{}}); }} catch (e) {{ return []; }} }}
      function summarizeValue(v) {{
        if (Array.isArray(v)) return {{ type: "array", length: v.length, sampleKeys: keys(v[0]).slice(0, 40) }};
        if (v && typeof v === "object") return {{ type: "object", keys: keys(v).slice(0, 120) }};
        return {{ type: typeof v, value: typeof v === "string" ? v.slice(0, 120) : v }};
      }}
      function compactAttr(attr) {{
        if (!attr) return null;
        return {{
          id: attr.id,
          attributeId: attr.attributeId,
          attributeIdStr: attr.attributeIdStr,
          name: attr.name,
          nameCn: attr.nameCn,
          type: attr.type,
          collection: attr.collection,
          required: attr.required,
          dictionaryId: attr.dictionaryId,
          dictionaryIdStr: attr.dictionaryIdStr,
          propertyType: attr.propertyType,
          optionsNum: attr.optionsNum,
          maxValueCount: attr.maxValueCount,
          _inputType: attr._inputType,
          _compType: attr._compType,
          _searchFlag: attr._searchFlag,
          _remoteSearch: attr._remoteSearch
        }};
      }}
      function compactAttrsInfo(info) {{
        if (!info) return null;
        const out = {{
          showProductVideo: !!info.showProductVideo,
          showDesc: !!info.showDesc,
          showQualification: !!info.showQualification,
          showSizeTable: !!info.showSizeTable,
          showRichJSON: !!info.showRichJSON
        }};
        ["attrsList", "mergeAttrsList", "skuList"].forEach((key) => {{
          const items = Array.isArray(info[key]) ? info[key] : [];
          out[key] = items.map(compactAttr).filter(Boolean);
        }});
        return out;
      }}
      const out = {{}};
      ids.forEach((id) => {{
        const store = pinia && pinia._s && pinia._s.get(id);
        if (!store) {{ out[id] = null; return; }}
        const state = store.$state || {{}};
        const item = {{ stateKeys: keys(state), fields: {{}} }};
        ["formState", "dataState", "attrsInfo", "categoryInfo", "dxmFormState", "selectProps"].forEach((k) => {{
          if (state[k] !== undefined) item.fields[k] = summarizeValue(state[k]);
        }});
        if (id === "ozonProductAddStore" && state.attrsInfo) item.attrsInfo = compactAttrsInfo(state.attrsInfo);
        out[id] = item;
      }});
      return JSON.stringify(out);
    }})()
    """


async def run_probe(host: str, port: int, product_id: str = "") -> dict[str, Any]:
    targets = load_targets(host, port)
    target = select_edit_target(targets, product_id)
    page_url = target.get("url", "")
    resolved_product_id = product_id or extract_product_id(page_url)
    if not resolved_product_id:
        raise RuntimeError(f"Could not resolve product id from edit page URL: {page_url}")

    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(target["webSocketDebuggerUrl"]) as ws:
            msg_id = 1
            product_result, msg_id = await evaluate_json(
                ws, build_product_fetch_expression(resolved_product_id), msg_id
            )
            store_result, msg_id = await evaluate_json(
                ws, build_store_snapshot_expression(STORE_IDS), msg_id
            )

    product_body = product_result.get("body") if isinstance(product_result, dict) else {}
    return {
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "page_url": page_url,
        "product_id": resolved_product_id,
        "product_endpoint": product_result.get("url") if isinstance(product_result, dict) else "",
        "product_status": product_result.get("status") if isinstance(product_result, dict) else None,
        "product_summary": summarize_product_response(product_body if isinstance(product_body, dict) else {}),
        "store_summary": summarize_store_state(store_result if isinstance(store_result, dict) else {}),
    }


def write_report(report: dict[str, Any], output_dir: Path = OUTPUT_DIR) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    product_id = report.get("product_id") or "unknown"
    path = output_dir / f"dxm_edit_probe_{product_id}_{ts}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_field_model(field_model: dict[str, Any], output_dir: Path = OUTPUT_DIR) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    product_id = field_model.get("product_id") or "unknown"
    path = output_dir / f"dxm_field_model_{product_id}_{ts}.json"
    path.write_text(json.dumps(field_model, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only Dianxiaomi Ozon edit page probe via CDP")
    parser.add_argument("--host", default=CDP_HOST)
    parser.add_argument("--port", default=CDP_PORT, type=int)
    parser.add_argument("--product-id", default="", help="Optional edit product id to target")
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        report = asyncio.run(run_probe(args.host, args.port, args.product_id))
        path = write_report(report, Path(args.output_dir))
        field_model = build_field_model(report)
        field_model_path = write_field_model(field_model, Path(args.output_dir))
    except Exception as exc:
        print(f"[!] dxm_edit_probe failed: {exc}", file=sys.stderr)
        return 1
    print(f"[*] Probe written: {path}")
    print(f"[*] Field model written: {field_model_path}")
    print(json.dumps({
        "product_id": report.get("product_id"),
        "attributes": report.get("product_summary", {}).get("attributes", {}).get("count"),
        "variants": report.get("product_summary", {}).get("variants", {}).get("count"),
        "output": str(path),
        "field_model": str(field_model_path),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
