from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from ..config import AMOUNT_TOLERANCE
from ..db.repositories import fetch_orders, fetch_payments


def money(value):
    if value is None:
        return Decimal("0.00")
    if isinstance(value, Decimal):
        return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    try:
        return Decimal(str(value).strip()).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, AttributeError):
        return Decimal("0.00")


def parse_dt(value):
    raw = str(value or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).isoformat(sep=" ")
        except ValueError:
            pass
    return raw


def severity_rank(value):
    return {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(value, 9)


def discrepancy(dtype, severity, order, payments, expected, actual, amount_at_risk, note):
    return {
        "type": dtype,
        "severity": severity,
        "order_id": order["order_id"] if order else (payments[0]["order_reference"] if payments else ""),
        "order_status": order["status"] if order else "",
        "payment_refs": ", ".join(p["transaction_ref"] for p in payments) if payments else "",
        "payment_statuses": ", ".join(sorted({p["status"] for p in payments})) if payments else "",
        "expected_amount": str(money(expected)),
        "actual_amount": str(money(actual)),
        "amount_at_risk": str(abs(money(amount_at_risk))),
        "currency": (order or payments[0]).get("currency", "USD") if (order or payments) else "USD",
        "note": note,
    }


def reconcile(user_id):
    orders = fetch_orders(user_id)
    payments = fetch_payments(user_id)
    payments_by_order = defaultdict(list)
    payment_refs = Counter()
    order_ids = Counter()
    for order in orders:
        order_ids[order["order_id"]] += 1
    for payment in payments:
        payments_by_order[payment["order_reference"]].append(payment)
        payment_refs[payment["transaction_ref"]] += 1

    rows = []
    matched_payment_ids = set()
    reconciled_value = Decimal("0.00")

    for order in sorted(orders, key=lambda r: (r["order_id"], r["id"])):
        oid = order["order_id"]
        linked = sorted(payments_by_order.get(oid, []), key=lambda r: (r["processed_at"] or "", r["transaction_ref"], r["id"]))
        charges = [p for p in linked if p["type"] == "charge" and p["status"] == "settled"]
        refunds = [p for p in linked if p["type"] == "refund" and p["status"] in {"settled", "succeeded"}]
        unsettled = [p for p in linked if p["status"] not in {"settled", "succeeded"}]
        order_net = money(order["net_amount"])
        charge_total = sum((money(p["amount"]) for p in charges), Decimal("0.00"))
        refund_total = sum((money(p["amount"]) for p in refunds), Decimal("0.00"))
        payment_total = charge_total - refund_total
        for p in linked:
            matched_payment_ids.add(p["id"])

        if order_ids[oid] > 1:
            rows.append(discrepancy("duplicate_order_id", "high", order, linked, order_net, payment_total, order_net, "The order export contains the same order id more than once."))
        elif order["status"] == "completed" and not linked:
            rows.append(discrepancy("missing_payment", "critical", order, [], order_net, Decimal("0.00"), order_net, "A completed order has no payment processor record."))
        elif order["status"] == "completed":
            if unsettled:
                rows.append(discrepancy("unsettled_payment", "high", order, unsettled, order_net, payment_total, order_net - payment_total, "The payment exists but is not settled."))
            elif not charges:
                rows.append(discrepancy("missing_charge", "critical", order, linked, order_net, payment_total, order_net, "The order only has non-charge payment activity."))
            elif len(charges) > 1:
                at_risk = abs(payment_total - order_net) if abs(payment_total - order_net) > AMOUNT_TOLERANCE else payment_total
                rows.append(discrepancy("duplicate_charge", "critical", order, charges, order_net, payment_total, at_risk, "More than one settled charge points at one order."))
            elif order["currency"] != charges[0]["currency"]:
                rows.append(discrepancy("currency_mismatch", "critical", order, linked, order_net, payment_total, order_net, "The order and payment currencies differ."))
            elif abs(payment_total - order_net) > AMOUNT_TOLERANCE:
                rows.append(discrepancy("underpaid" if payment_total < order_net else "overpaid", "critical", order, linked, order_net, payment_total, abs(order_net - payment_total), "The settled payment total does not equal the completed order value."))
            else:
                reconciled_value += order_net
        elif order["status"] in {"cancelled", "canceled"} and charge_total > AMOUNT_TOLERANCE:
            rows.append(discrepancy("charged_cancelled_order", "critical", order, linked, Decimal("0.00"), payment_total, payment_total, "A cancelled order still has captured payment activity."))
        elif order["status"] in {"refunded", "returned"} and abs(payment_total) > AMOUNT_TOLERANCE:
            rows.append(discrepancy("refund_not_balanced", "high", order, linked, Decimal("0.00"), payment_total, abs(payment_total), "A refunded order does not net to zero in the payment processor."))

    for payment in sorted(payments, key=lambda r: (r["order_reference"], r["transaction_ref"], r["id"])):
        if payment["id"] in matched_payment_ids:
            continue
        amount = money(payment["amount"])
        rows.append(discrepancy("orphan_payment" if payment["type"] == "charge" else "orphan_refund", "critical", None, [payment], Decimal("0.00"), amount, amount, "A payment references an order that is not present in the order export."))

    for ref, count in payment_refs.items():
        if count > 1:
            duplicates = [p for p in payments if p["transaction_ref"] == ref]
            rows.append(discrepancy("duplicate_transaction_ref", "high", None, duplicates, Decimal("0.00"), sum((money(p["amount"]) for p in duplicates), Decimal("0.00")), Decimal("0.00"), "The payment export contains the same transaction reference more than once."))

    rows.sort(key=lambda r: (severity_rank(r["severity"]), -float(r["amount_at_risk"]), r["order_id"] or "", r["payment_refs"]))
    collected = sum((money(p["amount"]) for p in payments if p["type"] == "charge" and p["status"] == "settled"), Decimal("0.00"))
    refunds = sum((money(p["amount"]) for p in payments if p["type"] == "refund" and p["status"] in {"settled", "succeeded"}), Decimal("0.00"))
    total_dispute = sum((money(r["amount_at_risk"]) for r in rows), Decimal("0.00"))
    by_type = Counter(r["type"] for r in rows)
    risk_by_type = defaultdict(Decimal)
    for row in rows:
        risk_by_type[row["type"]] += money(row["amount_at_risk"])
    return {
        "summary": {
            "total_orders": len(orders),
            "total_payments": len(payments),
            "total_reconciled": str(reconciled_value),
            "total_dispute": str(total_dispute),
            "money_at_risk": str(total_dispute),
            "net_collected": str(collected - refunds),
            "discrepancy_count": len(rows),
        },
        "by_type": dict(sorted(by_type.items())),
        "risk_by_type": {k: str(v) for k, v in sorted(risk_by_type.items())},
        "rows": rows,
        "has_data": bool(orders or payments),
    }
