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
    parser.add_argument("--cancel-date-from", default="")
    parser.add_argument("--cancel-date-to", default="")
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


def iter_cancelled_postings(date_from: str, date_to: str) -> list[dict[str, Any]]:
    postings: list[dict[str, Any]] = []
    offset = 0
    while True:
        payload = {
            "filter": {
                "since": f"{date_from}T00:00:00Z",
                "to": f"{date_to}T23:59:59Z",
                "status": "cancelled",
            },
            "limit": 1000,
            "offset": offset,
            "with": {"analytics_data": False, "financial_data": False},
        }
        data = seller_post("/v3/posting/fbs/list", payload)
        result = data.get("result", data)
        page_postings = result.get("postings", []) if isinstance(result, dict) else []
        postings.extend(page_postings)
        if len(page_postings) < 1000:
            break
        offset += len(page_postings)
    return postings


def cancellation_stats(postings: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    stats: dict[str, dict[str, Any]] = defaultdict(lambda: defaultdict(int))
    for posting in postings:
        cancelled_after_ship = bool((posting.get("cancellation") or {}).get("cancelled_after_ship"))
        metric = "undelivered_quantity" if cancelled_after_ship else "pre_ship_cancel_quantity"
        for product in posting.get("products") or []:
            sku = str(product.get("sku") or "").strip()
            if not sku:
                continue
            quantity = as_int(product.get("quantity")) or 1
            stats[sku][metric] += quantity
    return stats


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


def posting_items_map(operations: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    posting_items: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen: set[tuple[str, str]] = set()
    for op in operations:
        posting_number = str(op.get("posting", {}).get("posting_number") or "").strip()
        if not posting_number:
            continue
        for item in op.get("items") or []:
            sku = str(item.get("sku") or "").strip()
            if not sku:
                continue
            key = (posting_number, sku)
            if key in seen:
                continue
            posting_items[posting_number].append(item)
            seen.add(key)
    return posting_items


def aggregate_transactions(
    operations: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = defaultdict(lambda: defaultdict(Decimal))
    detail_rows: list[dict[str, Any]] = []
    unmatched: dict[str, Any] = defaultdict(Decimal)
    posting_items = posting_items_map(operations)
    for op in operations:
        items = op.get("items") or []
        posting_number = str(op.get("posting", {}).get("posting_number") or "").strip()
        allocation_rule = "交易自带SKU"
        if not items:
            items = posting_items.get(posting_number, [])
            allocation_rule = "按订单号归属SKU" if items else "未匹配SKU，按服务/订单级费用保留"
        item_count = max(len(items), 1)
        amount_each = split_amount(money(op.get("amount")), item_count)
        accrual_each = split_amount(money(op.get("accruals_for_sale")), item_count)
        commission_each = split_amount(money(op.get("sale_commission")), item_count)
        services_total = sum((money(s.get("price")) for s in op.get("services", [])), Decimal("0"))
        services_each = split_amount(services_total, item_count)
        order_level_fee_each = Decimal("0")
        if not op.get("items") and not money(op.get("accruals_for_sale")) and not money(op.get("sale_commission")):
            order_level_fee_each = amount_each

        if not items:
            unmatched["operations_count"] = as_int(unmatched.get("operations_count")) + 1
            unmatched["net_settlement_rub"] = money(unmatched.get("net_settlement_rub")) + money(op.get("amount"))
            detail_rows.append(
                {
                    "operation_date": op.get("operation_date", ""),
                    "posting_number": posting_number,
                    "ozon_sku": "",
                    "offer_id": "",
                    "product_name": "",
                    "operation_type": op.get("operation_type", ""),
                    "operation_type_name": op.get("operation_type_name", ""),
                    "transaction_group": op.get("type", ""),
                    "gross_sales_rub": decimal_text(op.get("accruals_for_sale")),
                    "commission_rub": decimal_text(op.get("sale_commission")),
                    "service_fee_rub": decimal_text(order_level_fee_each or services_total),
                    "net_settlement_rub": decimal_text(op.get("amount")),
                    "allocation_rule": allocation_rule,
                }
            )
            continue

        for item in items:
            key = str(item.get("sku") or item.get("offer_id") or item.get("name") or "UNKNOWN").strip()
            row = rows[key]
            row["ozon_sku"] = key
            row["product_name"] = row.get("product_name") or item.get("name", "")
            row["operations_count"] = as_int(row.get("operations_count")) + 1
            row["gross_sales_rub"] = money(row.get("gross_sales_rub")) + accrual_each
            row["ozon_commission_rub"] = money(row.get("ozon_commission_rub")) + commission_each
            row["ozon_services_rub"] = money(row.get("ozon_services_rub")) + services_each + order_level_fee_each
            row["net_settlement_rub"] = money(row.get("net_settlement_rub")) + amount_each
            row["quantity"] = as_int(row.get("quantity")) + item_quantity(item, accrual_each)
            if accrual_each > 0:
                row["sold_quantity"] = as_int(row.get("sold_quantity")) + item_quantity(item, accrual_each)
            elif accrual_each < 0:
                row["return_quantity"] = as_int(row.get("return_quantity")) + abs(item_quantity(item, accrual_each))
            sold_quantity = as_int(row.get("sold_quantity"))
            return_quantity = as_int(row.get("return_quantity"))
            row["return_rate"] = Decimal(return_quantity) / Decimal(sold_quantity) if sold_quantity else Decimal("0")
            detail_rows.append(
                {
                    "operation_date": op.get("operation_date", ""),
                    "posting_number": posting_number,
                    "ozon_sku": key,
                    "offer_id": item.get("offer_id", ""),
                    "product_name": item.get("name", ""),
                    "operation_type": op.get("operation_type", ""),
                    "operation_type_name": op.get("operation_type_name", ""),
                    "transaction_group": op.get("type", ""),
                    "gross_sales_rub": decimal_text(accrual_each),
                    "commission_rub": decimal_text(commission_each),
                    "service_fee_rub": decimal_text(services_each + order_level_fee_each),
                    "net_settlement_rub": decimal_text(amount_each),
                    "allocation_rule": allocation_rule,
                }
            )
    return rows, detail_rows, unmatched


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


def percent_text(value: Any) -> str:
    number = (money(value) * Decimal("100")).quantize(Decimal("0.01"))
    return f"{number}%"


SUMMARY_COLUMNS = [
    ("ozon_sku", "Ozon SKU"),
    ("offer_id", "Offer ID"),
    ("product_name", "产品名称"),
    ("sold_quantity", "销售数量"),
    ("return_quantity", "退货数量"),
    ("pre_ship_cancel_quantity", "未发货取消数量"),
    ("undelivered_quantity", "未签收/拒收数量"),
    ("quantity", "净销售数量"),
    ("return_rate", "退货率"),
    ("pre_ship_cancel_rate", "未发货取消率"),
    ("undelivered_rate", "未签收/拒收率"),
    ("operations_count", "交易笔数"),
    ("gross_sales_rub", "销售额(RUB)"),
    ("ozon_commission_rub", "Ozon佣金(RUB)"),
    ("ozon_services_rub", "Ozon服务/订单级费用(RUB)"),
    ("ad_spend_rub", "广告费(RUB)"),
    ("net_settlement_rub", "Ozon结算净额(RUB)"),
    ("purchase_cost_cny", "采购成本(CNY)"),
    ("first_leg_cost_cny", "头程(CNY)"),
    ("packaging_cost_cny", "包装(CNY)"),
    ("customs_cost_cny", "关税(CNY)"),
    ("labor_cost_cny", "人工(CNY)"),
    ("fx_cost_cny", "汇损/换汇费(CNY)"),
    ("total_manual_cost_cny", "自有成本合计(CNY)"),
    ("estimated_profit_before_manual_cost_rub", "未扣自有成本利润(RUB)"),
]


DETAIL_COLUMNS = [
    ("operation_date", "交易日期"),
    ("posting_number", "订单号"),
    ("ozon_sku", "Ozon SKU"),
    ("offer_id", "Offer ID"),
    ("product_name", "产品名称"),
    ("operation_type", "费用/交易类型"),
    ("operation_type_name", "费用/交易名称"),
    ("transaction_group", "交易分组"),
    ("gross_sales_rub", "销售额(RUB)"),
    ("commission_rub", "佣金(RUB)"),
    ("service_fee_rub", "服务/订单级费用(RUB)"),
    ("net_settlement_rub", "结算金额(RUB)"),
    ("allocation_rule", "归属规则"),
]


def write_summary_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[label for _, label in SUMMARY_COLUMNS])
        writer.writeheader()
        for row in rows:
            output_row = {}
            for key, label in SUMMARY_COLUMNS:
                output_row[label] = (
                    percent_text(row.get(key))
                    if key in {"return_rate", "pre_ship_cancel_rate", "undelivered_rate"}
                    else row.get(key, "")
                )
            writer.writerow(output_row)


def write_detail_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[label for _, label in DETAIL_COLUMNS])
        writer.writeheader()
        for row in rows:
            writer.writerow({label: row.get(key, "") for key, label in DETAIL_COLUMNS})


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    write_summary_csv(path, rows)


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
    cancel_date_from = args.cancel_date_from or args.date_from
    cancel_date_to = args.cancel_date_to or args.date_to
    cancelled_postings = iter_cancelled_postings(cancel_date_from, cancel_date_to)
    cancelled_by_sku = cancellation_stats(cancelled_postings)
    rows_by_sku, detail_rows, unmatched = aggregate_transactions(operations)
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
        pre_ship_cancel_quantity = as_int(cancelled_by_sku.get(str(sku), {}).get("pre_ship_cancel_quantity"))
        undelivered_quantity = as_int(cancelled_by_sku.get(str(sku), {}).get("undelivered_quantity"))
        row["pre_ship_cancel_quantity"] = pre_ship_cancel_quantity
        row["undelivered_quantity"] = undelivered_quantity
        sold_quantity = as_int(row.get("sold_quantity"))
        row["pre_ship_cancel_rate"] = (
            Decimal(pre_ship_cancel_quantity) / Decimal(sold_quantity + pre_ship_cancel_quantity)
            if sold_quantity or pre_ship_cancel_quantity
            else Decimal("0")
        )
        row["undelivered_rate"] = (
            Decimal(undelivered_quantity) / Decimal(sold_quantity + undelivered_quantity)
            if sold_quantity or undelivered_quantity
            else Decimal("0")
        )
        for field in [
            "sold_quantity",
            "return_quantity",
            "pre_ship_cancel_quantity",
            "undelivered_quantity",
            "quantity",
            "operations_count",
        ]:
            row[field] = as_int(row.get(field))
        row["return_rate"] = money(row.get("return_rate"))
        row["pre_ship_cancel_rate"] = money(row.get("pre_ship_cancel_rate"))
        row["undelivered_rate"] = money(row.get("undelivered_rate"))
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

    for detail in detail_rows:
        sku = str(detail.get("ozon_sku") or "")
        offer_id = sku_to_offer.get(sku, "")
        product = products.get(offer_id, {})
        if offer_id:
            detail["offer_id"] = offer_id
        if product and not detail.get("product_name"):
            detail["product_name"] = product.get("name", "")

    rows.sort(key=lambda r: money(r.get("gross_sales_rub")), reverse=True)
    detail_output = output.with_name(f"{output.stem}_费用明细{output.suffix}")
    write_summary_csv(output, rows)
    write_detail_csv(detail_output, detail_rows)

    summary = {
        "output": str(output),
        "detail_output": str(detail_output),
        "date_from": args.date_from,
        "date_to": args.date_to,
        "cancel_date_from": cancel_date_from,
        "cancel_date_to": cancel_date_to,
        "product_count": len(products),
        "transaction_count": len(operations),
        "cancelled_posting_count": len(cancelled_postings),
        "sku_rows": len(rows),
        "detail_rows": len(detail_rows),
        "unmatched_operations": as_int(unmatched.get("operations_count")),
        "unmatched_net_settlement_rub": decimal_text(unmatched.get("net_settlement_rub")),
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
