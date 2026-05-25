import csv
from decimal import Decimal

from scripts.ozon_sku_profit_report import aggregate_transactions, cancellation_stats, write_detail_csv, write_summary_csv


def test_report_assigns_order_level_fees_to_posting_sku(tmp_path):
    operations = [
        {
            "posting": {"posting_number": "0112092302-0040-1"},
            "operation_type": "OperationAgentDeliveredToCustomer",
            "operation_type_name": "Delivered",
            "amount": "295.00",
            "accruals_for_sale": "400.00",
            "sale_commission": "-60.00",
            "services": [{"price": "-45.00"}],
            "items": [{"sku": "3289478411", "offer_id": "xbA-12-Red-C1", "name": "Red bag"}],
        },
        {
            "posting": {"posting_number": "0112092302-0040-1"},
            "operation_type": "MarketplaceRedistributionOfDeliveryServicesOperation",
            "operation_type_name": "Delivery service",
            "amount": "-105.46",
            "accruals_for_sale": "0",
            "sale_commission": "0",
            "services": [],
            "items": [],
        },
    ]

    rows_by_sku, detail_rows, unmatched = aggregate_transactions(operations)

    assert unmatched["operations_count"] == 0
    assert "0112092302-0040-1" not in rows_by_sku
    assert rows_by_sku["3289478411"]["sold_quantity"] == 1
    assert rows_by_sku["3289478411"]["return_quantity"] == 0
    assert rows_by_sku["3289478411"]["return_rate"] == Decimal("0")
    assert rows_by_sku["3289478411"]["net_settlement_rub"] == Decimal("189.54")
    assert detail_rows[1]["allocation_rule"] == "按订单号归属SKU"

    output = tmp_path / "summary.csv"
    write_summary_csv(output, [dict(rows_by_sku["3289478411"])])
    detail_output = tmp_path / "detail.csv"
    write_detail_csv(detail_output, detail_rows)

    with output.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        headers = next(reader)

    assert "Ozon SKU" in headers
    assert "退货率" in headers
    assert "销售数量" in headers

    with detail_output.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        detail_headers = next(reader)
    assert "费用/交易类型" in detail_headers
    assert "归属规则" in detail_headers


def test_cancellation_stats_groups_cancelled_postings_by_sku():
    postings = [
        {
            "posting_number": "0116357976-0115-1",
            "status": "cancelled",
            "products": [{"sku": 3289478411, "quantity": 1}],
        },
        {
            "posting_number": "45077885-0071-1",
            "status": "cancelled",
            "products": [{"sku": 3289477696, "quantity": 2}],
        },
    ]

    stats = cancellation_stats(postings)

    assert stats["3289478411"]["cancel_quantity"] == 1
    assert stats["3289477696"]["cancel_quantity"] == 2
