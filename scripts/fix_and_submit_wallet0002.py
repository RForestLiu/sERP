#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Fix WALLET-0002 Ozon listing draft and submit to Ozon.

Fixes applied:
  1. Brand (attr 85): dictionary_value_id=971068372 (Bostanten)
  2. Closure (attr 5344): dictionary_value_id=60850 (Molniya/Zipper)
  3. Target audience (attr 9390): dictionary_value_id=43241 (Vzroslaya/Adult)
  4. Color (attr 10096): dictionary_value_id=61574 (Chernyy/Black)
  5. Removed Rich Content (attr 11254) — invalid JSON format
  6. Weight/dimensions added at item level via Listing facade

Usage:
  ./venv/Scripts/python scripts/fix_and_submit_wallet0002.py
"""
import json, os, sys, time, requests

# ── Config ──
BASE_URL = "http://127.0.0.1:5000"
STORE_ID = "ozon_anling"
SKC = "WALLET-0002"
DRAFT_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "listings", f"{SKC}_{STORE_ID}.json")
PRODUCTS_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "products.json")

# ── Offer IDs per variant (already on Ozon from first submission) ──
SKUS = [
    {"name": "WALLET-0002-BLACK", "price": "78.27"},
    {"name": "WALLET-0002-DUSTYPINK", "price": "78.27"},
    {"name": "WALLET-0002-ROSERED", "price": "78.27"},
]

def load_draft():
    """Load the already-fixed draft JSON."""
    with open(DRAFT_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def flatten_draft_for_api(draft):
    """Flatten the nested draft structure into the format create_product expects."""
    bf = draft.get("basic_fields", {})

    data = {
        "skc": draft.get("skc", SKC),
        "name": bf.get("name", ""),
        "description": bf.get("description", ""),
        "price": bf.get("price", ""),
        "offer_id": bf.get("offer_id", ""),
        "barcode": bf.get("barcode", ""),
        "category_id": draft.get("category_id", 0),
        "type_id": draft.get("category_type_id"),
        "attributes": draft.get("attributes", []),
        "images": draft.get("images", []),
        "videos": draft.get("videos", []),
        "skus": SKUS,
    }

    return data

def submit_product(data):
    """Submit via the Listing facade's create_product endpoint."""
    url = f"{BASE_URL}/api/ozon/{STORE_ID}/product/create"
    print(f"\n>>> POST {url}")
    resp = requests.post(url, json=data, timeout=120)
    result = resp.json()
    print(f"<<< Status: {resp.status_code}")
    print(f"<<< Response: {json.dumps(result, ensure_ascii=False, indent=2)[:2000]}")
    return result

def check_import_status(task_id):
    """Check the import task status."""
    url = f"{BASE_URL}/api/ozon/{STORE_ID}/listing/check-import"
    print(f"\n>>> GET {url}?task_id={task_id}")
    resp = requests.get(url, params={"task_id": task_id}, timeout=30)
    result = resp.json()
    print(f"<<< Status: {resp.status_code}")

    if result.get("success"):
        print(f"    Summary: {result.get('summary', '')}")
        print(f"    All imported: {result.get('all_imported', False)}")
        print(f"    Total errors: {result.get('total_errors', 0)}")
        print(f"    Total warnings: {result.get('total_warnings', 0)}")
        for item in result.get("items", []):
            print(f"\n  [{item.get('offer_id')}] pid={item.get('product_id')} status={item.get('status')}")
            for e in item.get("errors", []):
                print(f"    ERROR [{e['level']}] {e['code']}: {e['description_cn']}")
            for w in item.get("warnings", []):
                print(f"    WARN [{w['level']}] {w['code']}: {w['description_cn']}")
            if not item.get("errors") and not item.get("warnings"):
                print(f"    No errors or warnings")
    else:
        print(f"    Error: {result}")

    return result

def main():
    print("=" * 60)
    print("WALLET-0002 Ozon Fix & Submit")
    print("=" * 60)

    # 1. Load the fixed draft
    print("\n[1] Loading fixed draft...")
    draft = load_draft()

    # Verify fixes
    attrs = draft.get("attributes", [])
    brand = next((a for a in attrs if a.get("attribute_id") == 85), None)
    closure = next((a for a in attrs if a.get("attribute_id") == 5344), None)
    target = next((a for a in attrs if a.get("attribute_id") == 9390), None)
    color = next((a for a in attrs if a.get("attribute_id") == 10096), None)
    rich = next((a for a in attrs if a.get("attribute_id") == 11254), None)

    print(f"  Brand (85):  dict_id={brand.get('dictionary_value_id') if brand else 'MISSING'} value={brand.get('value') if brand else 'MISSING'}")
    print(f"  Closure (5344): dict_id={closure.get('dictionary_value_id') if closure else 'MISSING'} value={closure.get('value') if closure else 'MISSING'}")
    print(f"  Target (9390): dict_id={target.get('dictionary_value_id') if target else 'MISSING'} value={target.get('value') if target else 'MISSING'}")
    print(f"  Color (10096): dict_id={color.get('dictionary_value_id') if color else 'MISSING'} value={color.get('value') if color else 'MISSING'}")
    print(f"  Rich Content (11254): {'REMOVED' if rich is None else 'STILL PRESENT'}")
    print(f"  Total attributes: {len(attrs)}")

    # 2. Show product weight/dimensions (these are auto-extracted by facade)
    print("\n[2] Product dimensions (auto-extracted from products.json by facade):")
    products = json.load(open(PRODUCTS_FILE, "r", encoding="utf-8"))
    product = next((p for p in products.get("产品列表", []) if p.get("skc") == SKC), None)
    if product:
        md = product.get("manual_data", {})
        print(f"  weight_g: {md.get('weight_g', 'N/A')}")
        print(f"  collected_size_cm: {md.get('collected_size_cm', [])}")
        print(f"  collected_weight_g: {md.get('collected_weight_g', 'N/A')}")
    else:
        print("  WARNING: Product not found in products.json!")

    # 3. Flatten for API
    print("\n[3] Preparing API payload...")
    api_data = flatten_draft_for_api(draft)
    print(f"  SKUs: {[s['name'] for s in api_data['skus']]}")

    # 4. Confirm and submit
    print("\n[4] Submitting to Ozon...")
    print("    WARNING: This will create/update real products on Ozon!")
    confirm = input("    Continue? [y/N] ").strip().lower()
    if confirm != "y":
        print("    Aborted.")
        return

    result = submit_product(api_data)

    if not result.get("success"):
        print(f"\n[FAIL] Submission failed: {result.get('error', 'Unknown error')}")
        return

    task_id = result.get("task_id", "")
    print(f"\n[OK] Submitted! task_id={task_id}")

    # 5. Wait and check import status
    print("\n[5] Waiting 10s then checking import status...")
    time.sleep(10)

    status = check_import_status(task_id)

    # 6. Summary
    print("\n" + "=" * 60)
    if status.get("success"):
        errors = status.get("total_errors", 0)
        warnings = status.get("total_warnings", 0)
        if errors == 0 and warnings == 0:
            print("[SUCCESS] All variants imported with no errors or warnings!")
        elif errors == 0:
            print(f"[OK] All variants imported with {warnings} warnings (non-blocking)")
        else:
            print(f"[NEEDS FIX] {errors} blocking errors remain, {warnings} warnings")
    else:
        print("[FAIL] Could not check import status")
    print("=" * 60)

if __name__ == "__main__":
    main()
