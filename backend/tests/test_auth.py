from datetime import datetime, timedelta, timezone


def test_signup_then_me(client):
    r = client.post("/api/signup", json={"email": "a@example.com", "password": "password123"})
    assert r.status_code == 200
    assert r.json()["user"]["email"] == "a@example.com"

    me = client.get("/api/me")
    assert me.json()["user"]["email"] == "a@example.com"


def test_signup_rejects_short_password(client):
    r = client.post("/api/signup", json={"email": "a@example.com", "password": "short"})
    assert r.status_code == 400


def test_signup_duplicate_email_conflicts(client):
    client.post("/api/signup", json={"email": "dup@example.com", "password": "password123"})
    r = client.post("/api/signup", json={"email": "dup@example.com", "password": "password123"})
    assert r.status_code == 409


def test_login_wrong_password_rejected(client):
    client.post("/api/signup", json={"email": "a@example.com", "password": "password123"})
    r = client.post("/api/login", json={"email": "a@example.com", "password": "wrong-password"})
    assert r.status_code == 401


def test_logout_clears_session(client):
    client.post("/api/signup", json={"email": "a@example.com", "password": "password123"})
    client.post("/api/logout")
    assert client.get("/api/me").json()["user"] is None


def test_unauthenticated_dashboard_request_is_rejected(client):
    assert client.get("/api/dashboard").status_code == 401


def test_users_cannot_see_each_others_data(client, db_path):
    from fastapi.testclient import TestClient

    from app.main import app

    client.post("/api/signup", json={"email": "owner@example.com", "password": "password123"})
    orders = (
        "order_id,order_date,customer_email,currency,gross_amount,discount,net_amount,status\n"
        "ORD-1,2026-01-01,a@example.com,USD,10.00,0,10.00,completed\n"
    )
    payments = "transaction_ref,processed_at,order_reference,currency,amount,fee,net_settled,type,status\n"
    client.post(
        "/api/import",
        files={"orders": ("orders.csv", orders.encode(), "text/csv"), "payments": ("payments.csv", payments.encode(), "text/csv")},
    )

    with TestClient(app) as other:
        other.post("/api/signup", json={"email": "intruder@example.com", "password": "password123"})
        dashboard = other.get("/api/dashboard").json()
        assert dashboard["summary"]["total_orders"] == 0
        assert dashboard["has_data"] is False


def test_rate_limit_blocks_repeated_login_failures(client):
    from app import config

    for _ in range(config.RATE_LIMIT_MAX_ATTEMPTS):
        r = client.post("/api/login", json={"email": "nobody@example.com", "password": "wrongpassword"})
        assert r.status_code == 401

    blocked = client.post("/api/login", json={"email": "nobody@example.com", "password": "wrongpassword"})
    assert blocked.status_code == 429


def test_expired_session_is_rejected_and_deleted(client):
    from app.db.connection import connect
    from app.services import auth_service

    client.post("/api/signup", json={"email": "a@example.com", "password": "password123"})
    with connect() as db:
        token = db.execute("SELECT token FROM sessions LIMIT 1").fetchone()["token"]
        stale = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
        db.execute("UPDATE sessions SET created_at = ? WHERE token = ?", (stale, token))

    assert auth_service.get_current_user_for_token(token) is None

    with connect() as db:
        assert db.execute("SELECT 1 FROM sessions WHERE token = ?", (token,)).fetchone() is None


def test_fresh_session_is_accepted(client):
    from app.db.connection import connect
    from app.services import auth_service

    client.post("/api/signup", json={"email": "a@example.com", "password": "password123"})
    with connect() as db:
        token = db.execute("SELECT token FROM sessions LIMIT 1").fetchone()["token"]

    assert auth_service.get_current_user_for_token(token) is not None
