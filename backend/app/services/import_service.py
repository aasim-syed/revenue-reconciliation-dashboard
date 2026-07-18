import csv
from io import StringIO

from ..db.repositories import replace_user_data
from .reconciliation_service import money, parse_dt

REQUIRED_ORDER_COLUMNS = {"order_id", "order_date", "customer_email", "currency", "gross_amount", "discount", "net_amount", "status"}
REQUIRED_PAYMENT_COLUMNS = {"transaction_ref", "processed_at", "order_reference", "currency", "amount", "fee", "net_settled", "type", "status"}


def normalize_order(row):
    return {
        "order_id": row.get("order_id", "").strip().upper(),
        "order_date": parse_dt(row.get("order_date", "")),
        "customer_email": row.get("customer_email", "").strip().lower(),
        "currency": row.get("currency", "").strip().upper(),
        "gross_amount": str(money(row.get("gross_amount"))),
        "discount": str(money(row.get("discount"))),
        "net_amount": str(money(row.get("net_amount"))),
        "status": row.get("status", "").strip().lower(),
    }


def normalize_payment(row):
    return {
        "transaction_ref": row.get("transaction_ref", "").strip(),
        "processed_at": parse_dt(row.get("processed_at", "")),
        "order_reference": row.get("order_reference", "").strip().upper(),
        "currency": row.get("currency", "").strip().upper(),
        "amount": str(money(row.get("amount"))),
        "fee": str(money(row.get("fee"))),
        "net_settled": str(money(row.get("net_settled"))),
        "type": row.get("type", "").strip().lower(),
        "status": row.get("status", "").strip().lower(),
    }


def import_csvs(user_id, orders_text, payments_text):
    orders_reader = csv.DictReader(StringIO(orders_text))
    payments_reader = csv.DictReader(StringIO(payments_text))
    if set(orders_reader.fieldnames or []) != REQUIRED_ORDER_COLUMNS:
        raise ValueError("orders.csv does not match the expected export columns")
    if set(payments_reader.fieldnames or []) != REQUIRED_PAYMENT_COLUMNS:
        raise ValueError("payments.csv does not match the expected export columns")

    orders = [normalize_order(r) for r in orders_reader if any((v or "").strip() for v in r.values())]
    payments = [normalize_payment(r) for r in payments_reader if any((v or "").strip() for v in r.values())]
    replace_user_data(user_id, orders, payments)
    return len(orders), len(payments)
