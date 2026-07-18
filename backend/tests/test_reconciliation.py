from pathlib import Path

from app.services.import_service import import_csvs
from app.services.reconciliation_service import reconcile

ORDER_HEADERS = ["order_id", "order_date", "customer_email", "currency", "gross_amount", "discount", "net_amount", "status"]
PAYMENT_HEADERS = ["transaction_ref", "processed_at", "order_reference", "currency", "amount", "fee", "net_settled", "type", "status"]

REPO_ROOT = Path(__file__).resolve().parents[2]


def _csv(headers, rows):
    lines = [",".join(headers)]
    for row in rows:
        lines.append(",".join(str(row.get(h, "")) for h in headers))
    return "\n".join(lines) + "\n"


def _seed(user_id, order_rows, payment_rows):
    import_csvs(user_id, _csv(ORDER_HEADERS, order_rows), _csv(PAYMENT_HEADERS, payment_rows))
    return reconcile(user_id)


def order(order_id, net_amount, status="completed", currency="USD"):
    return {
        "order_id": order_id,
        "order_date": "2026-01-01",
        "customer_email": "a@example.com",
        "currency": currency,
        "gross_amount": net_amount,
        "discount": "0",
        "net_amount": net_amount,
        "status": status,
    }


def payment(ref, order_reference, amount, ptype="charge", status="settled", currency="USD"):
    return {
        "transaction_ref": ref,
        "processed_at": "2026-01-02 00:00:00",
        "order_reference": order_reference,
        "currency": currency,
        "amount": amount,
        "fee": "0",
        "net_settled": amount,
        "type": ptype,
        "status": status,
    }


def test_clean_match_is_reconciled_not_flagged(user_id):
    result = _seed(user_id, [order("ORD-1", "100.00")], [payment("TXN-1", "ORD-1", "100.00")])
    assert result["rows"] == []
    assert result["summary"]["total_reconciled"] == "100.00"
    assert result["summary"]["discrepancy_count"] == 0


def test_missing_payment(user_id):
    result = _seed(user_id, [order("ORD-1", "50.00")], [])
    assert [r["type"] for r in result["rows"]] == ["missing_payment"]
    assert result["rows"][0]["severity"] == "critical"
    assert result["rows"][0]["amount_at_risk"] == "50.00"


def test_underpaid(user_id):
    result = _seed(user_id, [order("ORD-1", "100.00")], [payment("TXN-1", "ORD-1", "60.00")])
    assert result["rows"][0]["type"] == "underpaid"
    assert result["rows"][0]["amount_at_risk"] == "40.00"


def test_overpaid(user_id):
    result = _seed(user_id, [order("ORD-1", "100.00")], [payment("TXN-1", "ORD-1", "150.00")])
    assert result["rows"][0]["type"] == "overpaid"
    assert result["rows"][0]["amount_at_risk"] == "50.00"


def test_duplicate_charge(user_id):
    result = _seed(
        user_id,
        [order("ORD-1", "50.00")],
        [payment("TXN-1", "ORD-1", "50.00"), payment("TXN-2", "ORD-1", "50.00")],
    )
    assert result["rows"][0]["type"] == "duplicate_charge"


def test_currency_mismatch(user_id):
    result = _seed(
        user_id,
        [order("ORD-1", "100.00", currency="USD")],
        [payment("TXN-1", "ORD-1", "100.00", currency="EUR")],
    )
    assert result["rows"][0]["type"] == "currency_mismatch"


def test_charged_cancelled_order(user_id):
    result = _seed(user_id, [order("ORD-1", "0.00", status="cancelled")], [payment("TXN-1", "ORD-1", "75.00")])
    assert result["rows"][0]["type"] == "charged_cancelled_order"


def test_cancelled_order_with_no_charge_is_clean(user_id):
    result = _seed(user_id, [order("ORD-1", "0.00", status="cancelled")], [])
    assert result["rows"] == []


def test_refund_not_balanced(user_id):
    # A charge with no offsetting refund on a refunded order should not net to zero.
    result = _seed(user_id, [order("ORD-1", "0.00", status="refunded")], [payment("TXN-1", "ORD-1", "40.00")])
    assert result["rows"][0]["type"] == "refund_not_balanced"


def test_refunded_order_that_nets_to_zero_is_clean(user_id):
    result = _seed(
        user_id,
        [order("ORD-1", "0.00", status="refunded")],
        [payment("TXN-1", "ORD-1", "40.00"), payment("TXN-2", "ORD-1", "40.00", ptype="refund")],
    )
    assert result["rows"] == []


def test_orphan_payment(user_id):
    result = _seed(user_id, [], [payment("TXN-1", "ORD-GHOST", "20.00")])
    assert result["rows"][0]["type"] == "orphan_payment"


def test_orphan_refund(user_id):
    result = _seed(user_id, [], [payment("TXN-1", "ORD-GHOST", "20.00", ptype="refund")])
    assert result["rows"][0]["type"] == "orphan_refund"


def test_duplicate_order_id(user_id):
    result = _seed(user_id, [order("ORD-1", "50.00"), order("ORD-1", "50.00")], [])
    types = [r["type"] for r in result["rows"]]
    assert types.count("duplicate_order_id") == 2


def test_duplicate_transaction_ref(user_id):
    result = _seed(
        user_id,
        [order("ORD-1", "50.00"), order("ORD-2", "50.00")],
        [payment("TXN-DUP", "ORD-1", "50.00"), payment("TXN-DUP", "ORD-2", "50.00")],
    )
    assert "duplicate_transaction_ref" in [r["type"] for r in result["rows"]]


def test_unsettled_payment(user_id):
    result = _seed(user_id, [order("ORD-1", "50.00")], [payment("TXN-1", "ORD-1", "50.00", status="pending")])
    assert result["rows"][0]["type"] == "unsettled_payment"


def test_unexpected_status_is_flagged_not_dropped(user_id):
    # Regression guard: an order status outside the recognized set used to fall through
    # every branch silently, vanishing from both the reconciled and disputed totals.
    result = _seed(user_id, [order("ORD-1", "50.00", status="processing")], [])
    assert result["rows"][0]["type"] == "unexpected_status"
    assert result["summary"]["discrepancy_count"] == 1
    assert result["summary"]["total_dispute"] == "50.00"


def test_amount_tolerance_boundary(user_id):
    within_tolerance = _seed(user_id, [order("ORD-1", "10.00")], [payment("TXN-1", "ORD-1", "10.01")])
    assert within_tolerance["rows"] == []

    over_tolerance = _seed(user_id, [order("ORD-2", "10.00")], [payment("TXN-2", "ORD-2", "10.02")])
    assert [r["type"] for r in over_tolerance["rows"]] == ["overpaid"]


def test_severity_and_risk_aggregates_cover_all_four_buckets(user_id):
    result = _seed(user_id, [order("ORD-1", "50.00")], [])  # missing_payment -> critical
    assert set(result["by_severity"]) == {"critical", "high", "medium", "low"}
    assert result["by_severity"]["critical"] == 1
    assert result["by_severity"]["low"] == 0
    assert result["risk_by_severity"]["critical"] == "50.00"
    assert result["risk_by_severity"]["low"] == "0.00"


def test_golden_dataset_matches_known_totals(user_id):
    """Regression test against the real supplied CSVs -- mirrors scripts/smoke_test.py."""
    orders_text = (REPO_ROOT / "orders.csv").read_text()
    payments_text = (REPO_ROOT / "payments.csv").read_text()

    imported = import_csvs(user_id, orders_text, payments_text)
    result = reconcile(user_id)

    assert imported == (185, 187)
    assert result["summary"]["total_orders"] == 185
    assert result["summary"]["total_payments"] == 187
    assert result["summary"]["discrepancy_count"] == 22
    assert result["summary"]["money_at_risk"] == "2233.13"
    assert result["by_type"]["missing_payment"] == 4
    assert result["by_type"]["orphan_payment"] == 3
