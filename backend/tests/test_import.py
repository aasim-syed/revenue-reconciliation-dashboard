def _signup(client, email="a@example.com"):
    client.post("/api/signup", json={"email": email, "password": "password123"})


def test_import_rejects_wrong_columns(client):
    _signup(client)
    bad_orders = "order_id,status\nORD-1,completed\n"
    payments = "transaction_ref,processed_at,order_reference,currency,amount,fee,net_settled,type,status\n"
    r = client.post(
        "/api/import",
        files={"orders": ("orders.csv", bad_orders.encode(), "text/csv"), "payments": ("payments.csv", payments.encode(), "text/csv")},
    )
    assert r.status_code == 400


def test_reimport_replaces_previous_data(client):
    _signup(client)
    payments_empty = "transaction_ref,processed_at,order_reference,currency,amount,fee,net_settled,type,status\n"
    orders1 = (
        "order_id,order_date,customer_email,currency,gross_amount,discount,net_amount,status\n"
        "ORD-1,2026-01-01,a@example.com,USD,10.00,0,10.00,completed\n"
    )
    client.post(
        "/api/import",
        files={"orders": ("orders.csv", orders1.encode(), "text/csv"), "payments": ("payments.csv", payments_empty.encode(), "text/csv")},
    )

    orders2 = (
        "order_id,order_date,customer_email,currency,gross_amount,discount,net_amount,status\n"
        "ORD-2,2026-01-01,a@example.com,USD,20.00,0,20.00,completed\n"
        "ORD-3,2026-01-01,a@example.com,USD,30.00,0,30.00,completed\n"
    )
    r = client.post(
        "/api/import",
        files={"orders": ("orders.csv", orders2.encode(), "text/csv"), "payments": ("payments.csv", payments_empty.encode(), "text/csv")},
    )
    assert r.json()["dashboard"]["summary"]["total_orders"] == 2
