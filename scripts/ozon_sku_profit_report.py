from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import sys
import time
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests
from dotenv import load_dotenv


SELLER_BASE_URL = "https://api-seller.ozon.ru"
PERFORMANCE_BASE_URL = "https://api-performance.ozon.ru"


ZERO_COST_FIELDS = [
    "purchase_cost_cny",
    "first_leg_cost_cny",
    "packaging_cost_cny",
    "customs_cost_cny",
    "labor_cost_cny",
    "fx_cost_cny",
]


def parse_args() -> argparse.Namespace:
    today = dt.date.today()
    default_from = today - dt.timedelta(days=30)
    parser = argparse.ArgumentParser(description="Build Ozon SKU profit report.")
    parser.add_argument("--date-from", default=default_from.isoformat())
    parser.add_argument("--date-to", default=today.isoformat())
    parser.add_argument("--output", default="")
    parser.add_argument("--performance-client-id", default=os.getenv("OZON_PERFORMANCE_CLIENT_ID", ""))
    parser.add_argument("--performance-client-secret", default=os.getenv("OZON_PERFORMANCE_CLIENT_SECRET", ""))
    return parser.parse_args()


def money(value: Any) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    try:
        return Decimal(str(value).replace(",", "."))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def as_int(value: Any) -> int:
    try:
        return int(Decimal(str(value)))
    except (InvalidOperation, ValueError, TypeError):
        return 0


def seller_headers() -> dict[str, str]:
    client_id = os.getenv("OZON_ANLING_CLIENT_ID", "").strip()
    api_key = os.getenv("OZON_ANLING_API_KEY", "").strip()
    if not client_id or not api_key:
        raise RuntimeError("Missing OZON_ANLING_CLIENT_ID or OZON_ANLING_API_KEY.")
    return {
        "Client-Id": client_id,
        "Api-Key": api_key,
        "Content-Type": "application/json",
    }


def post_json(url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
    response = requests.post(url, headers=headers, json=payload, timeout=60)
    if response.status_code != 200:
        raise RuntimeError(f"{url} returned HTTP {response.status_code}: {response.text[:500]}")
    return response.json()


def seller_post(endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
    return post_json(f"{SELLER_BASE_URL}{endpoint}", seller_headers(), payload)


def load_products() -> dict[str, dict[str, Any]]:
    products: dict[str, dict[str, Any]] = {}
    last_id = ""
    while True:
        payload = {"filter": {"visibility": "ALL"}, "last_id": last_id, "limit": 1000}
        data = seller_post("/v3/product/list", payload)
        result = data.get("result", data)
        items = result.get("items", []) if isinstance(result, dict) else []
        for item in items:
            offer_id = str(item.get("offer_id", "")).strip()
            if offer_id:
                products[offer_id] = {
                    "offer_id": offer_id,
                    "product_id": item.get("product_id", ""),
                    "sku": item.get("sku", ""),
                    "name": item.get("name", ""),
                    "visible": item.get("visible", ""),
                    "status": item.get("status", ""),
                }
        next_last_id = str(result.get("last_id", "") if isinstance(result, dict) else "")
        if not items or not next_last_id or next_last_id == last_id:
            break
        last_id = next_last_id
    enrich_products(products)
    return products


def enrich_products(products: dict[str, dict[str, Any]]) -> None:
    offer_ids = list(products)
    for i in range(0, len(offer_ids), 100):
        chunk = offer_ids[i : i + 100]
        data = seller_post("/v3/product/info/list", {"offer_id": chunk})
        raw_items = data.get("items") or data.get("result", {}).get("items", [])
        for item in raw_items:
            offer_id = str(item.get("offer_id", "")).strip()
            if not offer_id or offer_id not in products:
                continue
            products[offer_id].update(
                {
                    "product_id": item.get("id", item.get("product_id", products[offer_id].get("product_id", ""))),
                    "sku": item.get("sku", products[offer_id].get("sku", "")),
                    "name": item.get("name") or item.get("title") or products[offer_id].get("name", ""),
                    "price": item.get("price", ""),
                    "marketing_price": item.get("marketing_price", ""),
                    "currency_code": item.get("currency_code", ""),
                }
            )
        time.sleep(0.2)


def iter_transactions(date_from: str, date_to: str) -> list[dict[str, Any]]:
    operations: list[dict[str, Any]] = []
    start = dt.date.fromisoformat(date_from)
    end = dt.date.fromisoformat(date_to)
    current = start
    while current <= end:
        chunk_end = min(current + dt.timedelta(days=29), end)
        operations.extend(iter_transaction_chunk(current.isoformat(), chunk_end.isoformat()))
        current = chunk_end + dt.timedelta(days=1)
    return operations


def iter_transaction_chunk(date_from: str, date_to: str) -> list[dict[str, Any]]:
    operations: list[dict[str, Any]] = []
    page = 1
    while True:
        payload = {
            "filter": {
                "date": {
                    "from": f"{date_from}T00:00:00.000Z",
                    "to": f"{date_to}T23:59:59.999Z",
                },
                "operation_type": [],
                "posting_number": "",
                "transaction_type": "all",
            },
            "page": page,
            "page_size": 1000,
        }
        data = seller_post("/v3/finance/transaction/list", payload)
        result = data.get("result", data)
        page_ops = result.get("operations", []) if isinstance(result, dict) else []
        operations.extend(page_ops)
        page_count = as_int(result.get("page_count")) if isinstance(result, dict) else 0
        if not page_ops or (page_count and page >= page_count):
            break
        page += 1
    return operations


def split_amount(total: Decimal, count: int) -> Decimal:
    if count <= 0:
        return Decimal("0")
    return total / Decimal(count)


def item_quantity(item: dict[str, Any], accrual_each: Decimal) -> int:
    quantity = as_int(item.get("quantity"))
    if quantity:
        return quantity
    if accrual_each > 0:
        return 1
    if accrual_each < 0:
        return -1
    return 0


def aggregate_transactions(operations: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = defaultdict(lambda: defaultdict(Decimal))
    for op in operations:
        items = op.get("items") or []
        if not items:
            key = str(op.get("posting", {}).get("posting_number") or "UNKNOWN")
            items = [{"sku": key, "name": ""}]
        item_count = max(len(items), 1)
        amount_each = split_amount(money(op.get("amount")), item_count)
        accrual_each = split_amount(money(op.get("accruals_for_sale")), item_count)
        commission_each = split_amount(money(op.get("sale_commission")), item_count)
        services_total = sum((money(s.get("price")) for s in op.get("services", [])), Decimal("0"))
        services_each = split_amount(services_total, item_count)

        for item in items:
            key = str(item.get("sku") or item.get("offer_id") or item.get("name") or "UNKNOWN").strip()
            row = rows[key]
            row["ozon_sku"] = key
            row["product_name"] = row.get("product_name") or item.get("name", "")
            row["operations_count"] = as_int(row.get("operations_count")) + 1
            row["gross_sales_rub"] = money(row.get("gross_sales_rub")) + accrual_each
            row["ozon_commission_rub"] = money(row.get("ozon_commission_rub")) + commission_each
            row["ozon_services_rub"] = money(row.get("ozon_services_rub")) + services_each
            row["net_settlement_rub"] = money(row.get("net_settlement_rub")) + amount_each
            row["quantity"] = as_int(row.get("quantity")) + item_quantity(item, accrual_each)
    return rows


def performance_token(client_id: str, client_secret: str) -> str:
    payload = {"client_id": client_id, "client_secret": client_secret, "grant_type": "client_credentials"}
    data = post_json(
        f"{PERFORMANCE_BASE_URL}/api/client/token",
        {"Content-Type": "application/json", "Accept": "application/json"},
        payload,
    )
    token = data.get("access_token", "")
    if not token:
        raise RuntimeError("Performance API did not return access_token.")
    return token


def performance_campaign_ids(token: str) -> list[str]:
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    response = requests.get(f"{PERFORMANCE_BASE_URL}/api/client/campaign", headers=headers, timeout=60)
    if response.status_code != 200:
        raise RuntimeError(f"campaign list returned HTTP {response.status_code}: {response.text[:500]}")
    data = response.json()
    campaigns = data.get("list") or data.get("campaigns") or data.get("items") or []
    ids: list[str] = []
    for campaign in campaigns:
        campaign_id = campaign.get("id") or campaign.get("campaignId") or campaign.get("campaign_id")
        if campaign_id:
            ids.append(str(campaign_id))
    return ids


def fetch_ad_spend(client_id: str, client_secret: str, date_from: str, date_to: str) -> tuple[dict[str, Decimal], str]:
    if not client_id or not client_secret:
        return {}, "Performance API credentials were not provided."
    try:
        token = performance_token(client_id, client_secret)
        campaign_ids = performance_campaign_ids(token)
        if not campaign_ids:
            return {}, "Performance API returned no campaigns."

        # Ozon builds statistics asynchronously. This keeps the report resilient:
        # if the endpoint shape changes, we still return Seller API numbers.
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept": "application/json"}
        spend_by_sku: dict[str, Decimal] = defaultdict(Decimal)
        for i in range(0, len(campaign_ids), 10):
            payload = {
                "campaigns": campaign_ids[i : i + 10],
                "dateFrom": date_from,
                "dateTo": date_to,
                "groupBy": "SKU",
            }
            response = requests.post(
                f"{PERFORMANCE_BASE_URL}/api/client/statistics/json",
                headers=headers,
                json=payload,
                timeout=60,
            )
            if response.status_code != 200:
                return spend_by_sku, f"Performance statistics returned HTTP {response.status_code}: {response.text[:300]}"
            data = response.json()
            if data.get("UUID"):
                data = download_performance_report(token, str(data["UUID"]))
            records = normalize_ad_records(data)
            for record in records:
                sku = str(record.get("sku") or record.get("SKU") or record.get("offerId") or "").strip()
                if not sku:
                    continue
                spend = record.get("moneySpent") or record.get("expense") or record.get("cost") or record.get("spend")
                spend_by_sku[sku] += money(spend)
        return spend_by_sku, ""
    except Exception as exc:
        return {}, f"Performance API failed: {exc}"


def download_performance_report(token: str, uuid: str) -> Any:
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    query = urlencode({"UUID": uuid})
    url = f"{PERFORMANCE_BASE_URL}/api/client/statistics/report?{query}"
    last_text = ""
    for _ in range(12):
        response = requests.get(url, headers=headers, timeout=60)
        last_text = response.text
        if response.status_code == 200 and response.text.strip():
            try:
                return response.json()
            except ValueError:
                return parse_semicolon_report(response.text)
        if response.status_code not in (200, 202, 204):
            raise RuntimeError(f"Performance report returned HTTP {response.status_code}: {response.text[:300]}")
        time.sleep(5)
    raise RuntimeError(f"Performance report was not ready: {last_text[:300]}")


def parse_semicolon_report(text: str) -> list[dict[str, str]]:
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return []
    delimiter = ";" if ";" in lines[0] else ","
    reader = csv.DictReader(lines, delimiter=delimiter)
    return list(reader)


def normalize_ad_records(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [record for record in data if isinstance(record, dict)]
    if not isinstance(data, dict):
        return []
    for key in ("rows", "items", "data"):
        value = data.get(key)
        if isinstance(value, list):
            return [record for record in value if isinstance(record, dict)]
    report = data.get("report")
    if isinstance(report, dict):
        return normalize_ad_records(report)
    return []


def decimal_text(value: Any) -> str:
    number = money(value).quantize(Decimal("0.01"))
    return format(number, "f")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "ozon_sku",
        "offer_id",
        "product_name",
        "quantity",
        "operations_count",
        "gross_sales_rub",
        "ozon_commission_rub",
        "ozon_services_rub",
        "ad_spend_rub",
        "net_settlement_rub",
        *ZERO_COST_FIELDS,
        "total_manual_cost_cny",
        "estimated_profit_before_manual_cost_rub",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})


def main() -> int:
    load_dotenv()
    args = parse_args()
    output = Path(args.output or f"outputs/ozon_anling_sku_profit_{args.date_from}_{args.date_to}.csv")

    products = load_products()
    sku_to_offer: dict[str, str] = {}
    for offer_id, product in products.items():
        sku = str(product.get("sku") or "").strip()
        if sku:
            sku_to_offer[sku] = offer_id

    operations = iter_transactions(args.date_from, args.date_to)
    rows_by_sku = aggregate_transactions(operations)
    ad_spend_by_sku, ad_warning = fetch_ad_spend(
        args.performance_client_id.strip(),
        args.performance_client_secret.strip(),
        args.date_from,
        args.date_to,
    )

    for sku, spend in ad_spend_by_sku.items():
        rows_by_sku[sku]["ozon_sku"] = sku
        rows_by_sku[sku]["ad_spend_rub"] = spend

    rows: list[dict[str, Any]] = []
    for sku, row in rows_by_sku.items():
        offer_id = sku_to_offer.get(str(sku), "")
        product = products.get(offer_id, {})
        if product:
            row["offer_id"] = offer_id
            row["product_name"] = row.get("product_name") or product.get("name", "")
        row["ad_spend_rub"] = money(row.get("ad_spend_rub"))
        for field in ZERO_COST_FIELDS:
            row[field] = "0.00"
        row["total_manual_cost_cny"] = "0.00"
        row["estimated_profit_before_manual_cost_rub"] = money(row.get("net_settlement_rub")) - money(row.get("ad_spend_rub"))
        for field in [
            "gross_sales_rub",
            "ozon_commission_rub",
            "ozon_services_rub",
            "ad_spend_rub",
            "net_settlement_rub",
            "estimated_profit_before_manual_cost_rub",
        ]:
            row[field] = decimal_text(row.get(field))
        rows.append(dict(row))

    rows.sort(key=lambda r: money(r.get("gross_sales_rub")), reverse=True)
    write_csv(output, rows)

    summary = {
        "output": str(output),
        "date_from": args.date_from,
        "date_to": args.date_to,
        "product_count": len(products),
        "transaction_count": len(operations),
        "sku_rows": len(rows),
        "ad_warning": ad_warning,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
