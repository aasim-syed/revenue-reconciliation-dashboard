import csv
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import cgi

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = os.environ.get("DATABASE_PATH", str(BASE_DIR / "revenue_audit.db"))
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
USE_POSTGRES = bool(DATABASE_URL)
APP_SECRET = os.environ.get("APP_SECRET", "dev-secret-change-me")
FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "http://127.0.0.1:5173")
EXTRA_ORIGINS = {o.strip() for o in os.environ.get("EXTRA_ALLOWED_ORIGINS", "").split(",") if o.strip()}
ALLOWED_ORIGINS = {FRONTEND_ORIGIN, "http://127.0.0.1:5173", "http://localhost:5173"} | EXTRA_ORIGINS
SESSION_COOKIE = "audit_session"
AMOUNT_TOLERANCE = Decimal("0.01")
# Cross-origin deployments (separate frontend/backend hosts) need SameSite=None; Secure
# for the browser to send the session cookie on credentialed fetches. Local dev stays on
# plain http, so it keeps SameSite=Lax without Secure. Derived from FRONTEND_ORIGIN's
# scheme rather than a second env var, since the two must already agree.
COOKIE_SECURE = FRONTEND_ORIGIN.startswith("https://")

if USE_POSTGRES:
    import psycopg2
    import psycopg2.extras

    IntegrityError = psycopg2.IntegrityError
else:
    class IntegrityError(Exception):
        """Never raised in SQLite mode; sqlite3.IntegrityError is used instead."""


def load_dotenv(path):
    env_path = Path(path)
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value

load_dotenv(BASE_DIR.parent / ".env")
load_dotenv(BASE_DIR / ".env")


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


class PgConnection:
    """Wraps a psycopg2 connection so callers can keep using '?' placeholders,
    dict-like rows, and a sqlite3-style context manager (commit-or-rollback then close)."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=()):
        cur = self._conn.cursor()
        cur.execute(sql.replace("?", "%s"), params)
        return cur

    def executemany(self, sql, seq):
        cur = self._conn.cursor()
        cur.executemany(sql.replace("?", "%s"), seq)
        return cur

    def executescript(self, sql):
        cur = self._conn.cursor()
        cur.execute(sql)
        return cur

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self._conn.commit()
        else:
            self._conn.rollback()
        self._conn.close()
        return False


def connect():
    if USE_POSTGRES:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
        return PgConnection(conn)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    order_id TEXT NOT NULL,
    order_date TEXT,
    customer_email TEXT,
    currency TEXT,
    gross_amount TEXT,
    discount TEXT,
    net_amount TEXT,
    status TEXT,
    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    transaction_ref TEXT NOT NULL,
    processed_at TEXT,
    order_reference TEXT,
    currency TEXT,
    amount TEXT,
    fee TEXT,
    net_settled TEXT,
    type TEXT,
    status TEXT,
    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS explanations (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    fingerprint TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, fingerprint)
);
"""

POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS orders (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    order_id TEXT NOT NULL,
    order_date TEXT,
    customer_email TEXT,
    currency TEXT,
    gross_amount TEXT,
    discount TEXT,
    net_amount TEXT,
    status TEXT,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS payments (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    transaction_ref TEXT NOT NULL,
    processed_at TEXT,
    order_reference TEXT,
    currency TEXT,
    amount TEXT,
    fee TEXT,
    net_settled TEXT,
    type TEXT,
    status TEXT,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS explanations (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    fingerprint TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, fingerprint)
);
"""


def init_db():
    with connect() as db:
        db.executescript(POSTGRES_SCHEMA if USE_POSTGRES else SQLITE_SCHEMA)


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 240_000)
    return f"pbkdf2_sha256${salt}${digest.hex()}"


def verify_password(password, stored):
    try:
        _, salt, _ = stored.split("$", 2)
    except ValueError:
        return False
    return hmac.compare_digest(hash_password(password, salt), stored)


def sign_token(token):
    sig = hmac.new(APP_SECRET.encode(), token.encode(), hashlib.sha256).hexdigest()
    return f"{token}.{sig}"


def unsign_token(value):
    if not value or "." not in value:
        return None
    token, sig = value.rsplit(".", 1)
    expected = hmac.new(APP_SECRET.encode(), token.encode(), hashlib.sha256).hexdigest()
    return token if hmac.compare_digest(sig, expected) else None


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
    required_orders = {"order_id", "order_date", "customer_email", "currency", "gross_amount", "discount", "net_amount", "status"}
    required_payments = {"transaction_ref", "processed_at", "order_reference", "currency", "amount", "fee", "net_settled", "type", "status"}
    if set(orders_reader.fieldnames or []) != required_orders:
        raise ValueError("orders.csv does not match the expected export columns")
    if set(payments_reader.fieldnames or []) != required_payments:
        raise ValueError("payments.csv does not match the expected export columns")

    orders = [normalize_order(r) for r in orders_reader if any((v or "").strip() for v in r.values())]
    payments = [normalize_payment(r) for r in payments_reader if any((v or "").strip() for v in r.values())]
    with connect() as db:
        db.execute("DELETE FROM orders WHERE user_id = ?", (user_id,))
        db.execute("DELETE FROM payments WHERE user_id = ?", (user_id,))
        db.execute("DELETE FROM explanations WHERE user_id = ?", (user_id,))
        db.executemany(
            """
            INSERT INTO orders (user_id, order_id, order_date, customer_email, currency, gross_amount, discount, net_amount, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [(user_id, r["order_id"], r["order_date"], r["customer_email"], r["currency"], r["gross_amount"], r["discount"], r["net_amount"], r["status"]) for r in orders],
        )
        db.executemany(
            """
            INSERT INTO payments (user_id, transaction_ref, processed_at, order_reference, currency, amount, fee, net_settled, type, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [(user_id, r["transaction_ref"], r["processed_at"], r["order_reference"], r["currency"], r["amount"], r["fee"], r["net_settled"], r["type"], r["status"]) for r in payments],
        )
    return len(orders), len(payments)


def load_data(user_id):
    with connect() as db:
        orders = [dict(r) for r in db.execute("SELECT * FROM orders WHERE user_id = ? ORDER BY order_id, id", (user_id,))]
        payments = [dict(r) for r in db.execute("SELECT * FROM payments WHERE user_id = ? ORDER BY order_reference, id", (user_id,))]
    return orders, payments


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
    orders, payments = load_data(user_id)
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


def fingerprint(rows):
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()


def render_llm_json(parsed):
    summary = parsed.get("summary", "")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("Model response 'summary' was not a non-empty string")
    causes = parsed.get("likely_causes", [])
    actions = parsed.get("recommended_actions", [])
    if not isinstance(causes, list):
        causes = [str(causes)]
    if not isinstance(actions, list):
        actions = [str(actions)]
    return {"summary": summary.strip(), "likely_causes": [str(c) for c in causes[:5]], "recommended_actions": [str(a) for a in actions[:5]]}


def humanize(value):
    return str(value or "").replace("_", " ").strip()


def deterministic_explanation(rows, prefix=None):
    selected = rows[:12]
    if not selected:
        summary = "No discrepancies are visible in the current view."
        if prefix:
            summary = f"{prefix} {summary}"
        return {"summary": summary, "likely_causes": [], "recommended_actions": []}

    total_risk = sum((money(row.get("amount_at_risk")) for row in selected), Decimal("0.00"))
    by_type = Counter(row.get("type", "unknown") for row in selected)
    by_severity = Counter(row.get("severity", "unknown") for row in selected)
    top_type, top_count = by_type.most_common(1)[0]
    critical_count = by_severity.get("critical", 0)
    high_count = by_severity.get("high", 0)
    summary = (
        f"Current view contains {len(selected)} discrepancy records with {money(total_risk)} at risk. "
        f"The most common issue is {humanize(top_type)} ({top_count} records), with "
        f"{critical_count} critical and {high_count} high-priority records in scope."
    )
    if prefix:
        summary = f"{prefix} {summary}"

    causes = []
    for dtype, _ in by_type.most_common(5):
        notes = [row.get("note", "") for row in selected if row.get("type") == dtype and row.get("note")]
        cause = notes[0] if notes else f"{humanize(dtype).capitalize()} appears in the filtered records."
        causes.append(f"{humanize(dtype).capitalize()}: {cause}")

    actions = [
        "Start with critical records and the largest amount-at-risk values.",
        "Compare each affected order against the payment processor timeline before issuing refunds or capture adjustments.",
        "Export or save the filtered discrepancy list as the audit work queue for finance review.",
    ]
    if any(row.get("type") in {"duplicate_charge", "overpaid", "charged_cancelled_order"} for row in selected):
        actions.insert(1, "Prioritize customer-impacting overcollection issues before revenue leakage items.")
    if any(row.get("type") in {"missing_payment", "underpaid", "unsettled_payment"} for row in selected):
        actions.insert(1, "Verify fulfillment status before retrying collection or contacting customers.")

    return {"summary": summary, "likely_causes": causes, "recommended_actions": actions[:5]}


def explain_with_llm(user_id, rows):
    selected = rows[:12]
    fp = fingerprint(selected)
    with connect() as db:
        cached = db.execute("SELECT content FROM explanations WHERE user_id = ? AND fingerprint = ?", (user_id, fp)).fetchone()
        if cached:
            content = json.loads(cached["content"])
            summary = str(content.get("summary", ""))
            stale_error = "explanation service returned" in summary.lower() or "http error 403" in summary.lower()
            if not stale_error:
                return content, True
            db.execute("DELETE FROM explanations WHERE user_id = ? AND fingerprint = ?", (user_id, fp))
    groq_key = os.environ.get("GROQ_API_KEY", "").strip()
    openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
    providers = []
    if groq_key:
        providers.append({
            "api_key": groq_key,
            "endpoint": os.environ.get("GROQ_CHAT_COMPLETIONS_URL", "https://api.groq.com/openai/v1/chat/completions"),
            "model": os.environ.get("GROQ_MODEL", "llama-3.1-8b-instant"),
            "name": "Groq",
        })
    if openai_key:
        providers.append({
            "api_key": openai_key,
            "endpoint": "https://api.openai.com/v1/chat/completions",
            "model": os.environ.get("OPENAI_MODEL", "gpt-4.1-mini"),
            "name": "OpenAI",
        })
    if not providers:
        return deterministic_explanation(selected, "AI explanations are not configured; showing a deterministic summary."), False

    for provider in providers:
        body = {
            "model": provider["model"],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": f"You explain deterministic revenue reconciliation results using {provider['name']}. Return JSON with keys summary, likely_causes, recommended_actions. Do not change classifications or amounts."},
                {"role": "user", "content": json.dumps({"discrepancies": selected}, indent=2)},
            ],
        }
        req = urllib.request.Request(provider["endpoint"], data=json.dumps(body).encode(), headers={"Authorization": f"Bearer {provider['api_key']}", "Content-Type": "application/json", "User-Agent": "revenue-audit-local-dev/1.0"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.loads(resp.read().decode())
            parsed = render_llm_json(json.loads(payload["choices"][0]["message"]["content"]))
            with connect() as db:
                if USE_POSTGRES:
                    db.execute(
                        """
                        INSERT INTO explanations (user_id, fingerprint, content) VALUES (?, ?, ?)
                        ON CONFLICT (user_id, fingerprint) DO UPDATE SET content = EXCLUDED.content
                        """,
                        (user_id, fp, json.dumps(parsed)),
                    )
                else:
                    db.execute("INSERT OR REPLACE INTO explanations (user_id, fingerprint, content) VALUES (?, ?, ?)", (user_id, fp, json.dumps(parsed)))
            return parsed, False
        except (urllib.error.HTTPError, urllib.error.URLError, KeyError, IndexError, json.JSONDecodeError, TimeoutError, ValueError):
            continue

    return deterministic_explanation(selected, "AI explanation is temporarily unavailable; showing a deterministic summary."), False

class Handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_cors()
        self.end_headers()

    def do_GET(self):
        user = self.current_user()
        path = urlparse(self.path).path
        if path == "/api/health":
            self.json({"ok": True})
        elif path == "/api/me":
            self.json({"user": user})
        elif path == "/api/dashboard":
            if not self.require_user(user):
                return
            self.json(reconcile(user["id"]))
        else:
            self.json({"error": "Not found"}, 404)

    def do_POST(self):
        user = self.current_user()
        path = urlparse(self.path).path
        if path in {"/api/signup", "/api/login"}:
            self.handle_auth(path)
        elif path == "/api/logout":
            self.handle_logout(user)
        elif path == "/api/import":
            if self.require_user(user):
                self.handle_import(user)
        elif path == "/api/explain":
            if self.require_user(user):
                self.handle_explain(user)
        else:
            self.json({"error": "Not found"}, 404)

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode())

    def handle_auth(self, path):
        try:
            data = self.read_json()
        except json.JSONDecodeError:
            self.json({"error": "Malformed JSON"}, 400)
            return
        email = str(data.get("email", "")).strip().lower()
        password = str(data.get("password", ""))
        if not email or len(password) < 8:
            self.json({"error": "Use a valid email and a password of at least 8 characters."}, 400)
            return
        with connect() as db:
            if path == "/api/signup":
                try:
                    if USE_POSTGRES:
                        cur = db.execute("INSERT INTO users (email, password_hash) VALUES (?, ?) RETURNING id", (email, hash_password(password)))
                        user_id = cur.fetchone()["id"]
                    else:
                        cur = db.execute("INSERT INTO users (email, password_hash) VALUES (?, ?)", (email, hash_password(password)))
                        user_id = cur.lastrowid
                except (sqlite3.IntegrityError, IntegrityError):
                    self.json({"error": "That email is already registered."}, 409)
                    return
            else:
                row = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
                if not row or not verify_password(password, row["password_hash"]):
                    self.json({"error": "Invalid email or password."}, 401)
                    return
                user_id = row["id"]
            token = secrets.token_urlsafe(32)
            db.execute("INSERT INTO sessions (token, user_id) VALUES (?, ?)", (token, user_id))
        self.json({"user": {"id": user_id, "email": email}}, cookie_value=sign_token(token))

    def handle_logout(self, user):
        jar = cookies.SimpleCookie(self.headers.get("Cookie"))
        morsel = jar.get(SESSION_COOKIE)
        token = unsign_token(morsel.value) if morsel else None
        if token:
            with connect() as db:
                db.execute("DELETE FROM sessions WHERE token = ?", (token,))
        self.json({"ok": True}, cookie_value="deleted", max_age=0)

    def handle_import(self, user):
        try:
            form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": self.headers.get("Content-Type")})
            orders_text = form["orders"].file.read().decode("utf-8-sig")
            payments_text = form["payments"].file.read().decode("utf-8-sig")
            order_count, payment_count = import_csvs(user["id"], orders_text, payments_text)
        except Exception as exc:
            self.json({"error": str(exc)}, 400)
            return
        self.json({"orders": order_count, "payments": payment_count, "dashboard": reconcile(user["id"])})

    def handle_explain(self, user):
        try:
            data = self.read_json()
        except json.JSONDecodeError:
            self.json({"error": "Malformed JSON"}, 400)
            return
        rows = data.get("rows") or reconcile(user["id"])["rows"]
        explanation, cached = explain_with_llm(user["id"], rows)
        self.json({"cached": cached, "explanation": explanation})

    def current_user(self):
        jar = cookies.SimpleCookie(self.headers.get("Cookie"))
        morsel = jar.get(SESSION_COOKIE)
        token = unsign_token(morsel.value) if morsel else None
        if not token:
            return None
        with connect() as db:
            row = db.execute("SELECT users.id, users.email FROM sessions JOIN users ON users.id = sessions.user_id WHERE sessions.token = ?", (token,)).fetchone()
        return dict(row) if row else None

    def require_user(self, user):
        if user:
            return True
        self.json({"error": "Authentication required"}, 401)
        return False

    def send_cors(self):
        origin = self.headers.get("Origin")
        self.send_header("Access-Control-Allow-Origin", origin if origin in ALLOWED_ORIGINS else FRONTEND_ORIGIN)
        self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Credentials", "true")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def json(self, payload, status=200, cookie_value=None, max_age=None):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if cookie_value is not None:
            cookie = f"{SESSION_COOKIE}={cookie_value}; Path=/; HttpOnly; SameSite={'None' if COOKIE_SECURE else 'Lax'}"
            if COOKIE_SECURE:
                cookie += "; Secure"
            if max_age is not None:
                cookie += f"; Max-Age={max_age}"
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        return


def main():
    init_db()
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"Backend serving on http://127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
