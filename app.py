import csv
import hashlib
import hmac
import html
import json
import os
import secrets
import sqlite3
import sys
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse
import cgi


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = os.environ.get("DATABASE_PATH", str(BASE_DIR / "revenue_audit.db"))
APP_SECRET = os.environ.get("APP_SECRET", "dev-secret-change-me")
SESSION_COOKIE = "audit_session"
AMOUNT_TOLERANCE = Decimal("0.01")


def money(value):
    if value is None:
        return Decimal("0.00")
    if isinstance(value, Decimal):
        return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    try:
        return Decimal(str(value).strip()).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, AttributeError):
        return Decimal("0.00")


def money_str(value):
    return f"{money(value):,.2f}"


def parse_dt(value):
    if not value:
        return ""
    raw = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).isoformat(sep=" ")
        except ValueError:
            pass
    return raw


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with connect() as db:
        db.executescript(
            """
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
        )


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 240_000)
    return f"pbkdf2_sha256${salt}${digest.hex()}"


def verify_password(password, stored):
    try:
        _, salt, digest = stored.split("$", 2)
    except ValueError:
        return False
    candidate = hash_password(password, salt)
    return hmac.compare_digest(candidate, stored)


def sign_token(token):
    sig = hmac.new(APP_SECRET.encode(), token.encode(), hashlib.sha256).hexdigest()
    return f"{token}.{sig}"


def unsign_token(value):
    if not value or "." not in value:
        return None
    token, sig = value.rsplit(".", 1)
    expected = hmac.new(APP_SECRET.encode(), token.encode(), hashlib.sha256).hexdigest()
    if hmac.compare_digest(sig, expected):
        return token
    return None


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
        missing = required_orders - set(orders_reader.fieldnames or [])
        raise ValueError(f"orders.csv is missing columns: {', '.join(sorted(missing))}")
    if set(payments_reader.fieldnames or []) != required_payments:
        missing = required_payments - set(payments_reader.fieldnames or [])
        raise ValueError(f"payments.csv is missing columns: {', '.join(sorted(missing))}")

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
    matched_order_ids = set()
    matched_payment_ids = set()
    reconciled_value = Decimal("0.00")

    for order in sorted(orders, key=lambda r: (r["order_id"], r["id"])):
        oid = order["order_id"]
        linked = sorted(payments_by_order.get(oid, []), key=lambda r: (r["processed_at"] or "", r["transaction_ref"], r["id"]))
        charges = [p for p in linked if p["type"] == "charge" and p["status"] == "settled"]
        refunds = [p for p in linked if p["type"] == "refund" and p["status"] in {"settled", "succeeded"}]
        pending_or_failed = [p for p in linked if p["status"] not in {"settled", "succeeded"}]
        order_net = money(order["net_amount"])
        charge_total = sum((money(p["amount"]) for p in charges), Decimal("0.00"))
        refund_total = sum((money(p["amount"]) for p in refunds), Decimal("0.00"))
        payment_total = charge_total - refund_total
        linked_ids = [p["id"] for p in linked]

        for p in linked:
            matched_payment_ids.add(p["id"])
        if linked:
            matched_order_ids.add(order["id"])

        if order_ids[oid] > 1:
            rows.append(discrepancy("duplicate_order_id", "high", order, linked, order_net, payment_total, order_net, "The order export contains the same order id more than once."))
        elif order["status"] == "completed" and not linked:
            rows.append(discrepancy("missing_payment", "critical", order, [], order_net, Decimal("0.00"), order_net, "A completed order has no payment processor record."))
        elif order["status"] == "completed":
            if pending_or_failed:
                rows.append(discrepancy("unsettled_payment", "high", order, pending_or_failed, order_net, payment_total, order_net - payment_total, "The payment exists but is not settled."))
            elif len(charges) == 0:
                rows.append(discrepancy("missing_charge", "critical", order, linked, order_net, payment_total, order_net, "The order only has non-charge payment activity."))
            elif len(charges) > 1:
                at_risk = abs(payment_total - order_net) if abs(payment_total - order_net) > AMOUNT_TOLERANCE else payment_total
                rows.append(discrepancy("duplicate_charge", "critical", order, charges, order_net, payment_total, at_risk, "More than one settled charge points at one order."))
            elif order["currency"] != charges[0]["currency"]:
                rows.append(discrepancy("currency_mismatch", "critical", order, linked, order_net, payment_total, order_net, "The order and payment currencies differ."))
            elif abs(payment_total - order_net) > AMOUNT_TOLERANCE:
                severity = "critical" if abs(payment_total - order_net) >= Decimal("25.00") else "high"
                dtype = "underpaid" if payment_total < order_net else "overpaid"
                rows.append(discrepancy(dtype, severity, order, linked, order_net, payment_total, abs(order_net - payment_total), "The settled payment total does not equal the completed order value."))
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
        dtype = "orphan_payment" if payment["type"] == "charge" else "orphan_refund"
        rows.append(discrepancy(dtype, "critical", None, [payment], Decimal("0.00"), amount, amount, "A payment references an order that is not present in the order export."))

    for ref, count in payment_refs.items():
        if count > 1:
            duplicates = [p for p in payments if p["transaction_ref"] == ref]
            rows.append(discrepancy("duplicate_transaction_ref", "high", None, duplicates, Decimal("0.00"), sum((money(p["amount"]) for p in duplicates), Decimal("0.00")), Decimal("0.00"), "The payment export contains the same transaction reference more than once."))

    rows.sort(key=lambda r: (severity_rank(r["severity"]), -float(r["amount_at_risk"]), r["order_id"] or "", r["payment_refs"]))
    total_orders = len(orders)
    total_payments = len(payments)
    total_dispute = sum((money(r["amount_at_risk"]) for r in rows), Decimal("0.00"))
    collected = sum((money(p["amount"]) for p in payments if p["type"] == "charge" and p["status"] == "settled"), Decimal("0.00"))
    refunds = sum((money(p["amount"]) for p in payments if p["type"] == "refund" and p["status"] in {"settled", "succeeded"}), Decimal("0.00"))
    by_type = Counter(r["type"] for r in rows)
    risk_by_type = defaultdict(Decimal)
    for row in rows:
        risk_by_type[row["type"]] += money(row["amount_at_risk"])
    return {
        "orders": orders,
        "payments": payments,
        "rows": rows,
        "summary": {
            "total_orders": total_orders,
            "total_payments": total_payments,
            "total_reconciled": str(reconciled_value),
            "total_dispute": str(total_dispute),
            "money_at_risk": str(total_dispute),
            "net_collected": str(collected - refunds),
            "discrepancy_count": len(rows),
        },
        "by_type": dict(sorted(by_type.items())),
        "risk_by_type": {k: str(v) for k, v in sorted(risk_by_type.items())},
    }


def severity_rank(value):
    return {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(value, 9)


def discrepancy(dtype, severity, order, payments, expected, actual, amount_at_risk, note):
    payment_refs = ", ".join(p["transaction_ref"] for p in payments) if payments else ""
    return {
        "type": dtype,
        "severity": severity,
        "order_id": order["order_id"] if order else (payments[0]["order_reference"] if payments else ""),
        "order_status": order["status"] if order else "",
        "payment_refs": payment_refs,
        "payment_statuses": ", ".join(sorted({p["status"] for p in payments})) if payments else "",
        "expected_amount": str(money(expected)),
        "actual_amount": str(money(actual)),
        "amount_at_risk": str(abs(money(amount_at_risk))),
        "currency": (order or payments[0]).get("currency", "USD") if (order or payments) else "USD",
        "note": note,
    }


def fingerprint(rows):
    body = json.dumps(rows, sort_keys=True)
    return hashlib.sha256(body.encode()).hexdigest()


def explain_with_llm(user_id, rows):
    selected = rows[:12]
    fp = fingerprint(selected)
    with connect() as db:
        cached = db.execute("SELECT content FROM explanations WHERE user_id = ? AND fingerprint = ?", (user_id, fp)).fetchone()
        if cached:
            return cached["content"], True

    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return "LLM explanations are not configured. Set OPENAI_API_KEY on the backend to enable this feature.", False

    model = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")
    prompt = {
        "model": model,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": "You explain deterministic revenue reconciliation results. Return JSON with keys summary, likely_causes, recommended_actions. Do not change classifications or amounts."},
            {"role": "user", "content": json.dumps({"discrepancies": selected}, indent=2)},
        ],
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(prompt).encode(),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode())
        content = payload["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        explanation = render_llm_json(parsed)
    except (urllib.error.URLError, KeyError, IndexError, json.JSONDecodeError, TimeoutError) as exc:
        explanation = f"The explanation service returned an unusable response. Deterministic results are still available. Error: {html.escape(str(exc))}"

    with connect() as db:
        db.execute("INSERT OR REPLACE INTO explanations (user_id, fingerprint, content) VALUES (?, ?, ?)", (user_id, fp, explanation))
    return explanation, False


def render_llm_json(parsed):
    summary = str(parsed.get("summary", "")).strip()
    causes = parsed.get("likely_causes", [])
    actions = parsed.get("recommended_actions", [])
    if not isinstance(causes, list):
        causes = [str(causes)]
    if not isinstance(actions, list):
        actions = [str(actions)]
    lines = []
    if summary:
        lines.append(summary)
    if causes:
        lines.append("Likely causes: " + "; ".join(str(x) for x in causes[:5]))
    if actions:
        lines.append("Recommended actions: " + "; ".join(str(x) for x in actions[:5]))
    return "\n\n".join(lines) or "No explanation returned."


def esc(value):
    return html.escape(str(value or ""))


def layout(title, body, user=None):
    auth = (
        f'<span>{esc(user["email"])}</span><a class="button ghost" href="/logout">Log out</a>'
        if user
        else '<a class="button ghost" href="/login">Log in</a><a class="button" href="/signup">Sign up</a>'
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(title)}</title>
  <link rel="stylesheet" href="/static/style.css">
</head>
<body>
  <header class="topbar">
    <a class="brand" href="/">Revenue Audit</a>
    <nav>{auth}</nav>
  </header>
  <main>{body}</main>
</body>
</html>"""


def login_form(mode, error=""):
    action = "/signup" if mode == "signup" else "/login"
    title = "Create account" if mode == "signup" else "Log in"
    alternate = '<a href="/login">Already have an account?</a>' if mode == "signup" else '<a href="/signup">Need an account?</a>'
    body = f"""
    <section class="auth-panel">
      <h1>{title}</h1>
      {'<p class="error">' + esc(error) + '</p>' if error else ''}
      <form method="post" action="{action}">
        <label>Email<input name="email" type="email" required autocomplete="email"></label>
        <label>Password<input name="password" type="password" required autocomplete="current-password" minlength="8"></label>
        <button class="button" type="submit">{title}</button>
      </form>
      <p>{alternate}</p>
    </section>"""
    return layout(title, body)


def dashboard(user, query):
    data = reconcile(user["id"])
    rows = data["rows"]
    type_filter = query.get("type", [""])[0]
    search = query.get("q", [""])[0].strip().lower()
    if type_filter:
        rows = [r for r in rows if r["type"] == type_filter]
    if search:
        rows = [r for r in rows if search in json.dumps(r).lower()]
    max_risk = max([money(v) for v in data["risk_by_type"].values()] or [Decimal("1.00")])
    bars = "".join(
        f'<div class="bar-row"><a href="/?type={urlencode({"": t})[1:]}">{esc(t.replace("_", " "))}</a><div class="bar-track"><span style="width:{float(money(v) / max_risk * 100):.1f}%"></span></div><strong>${money_str(v)}</strong></div>'
        for t, v in data["risk_by_type"].items()
    )
    options = '<option value="">All types</option>' + "".join(
        f'<option value="{esc(t)}" {"selected" if t == type_filter else ""}>{esc(t.replace("_", " "))}</option>'
        for t in sorted(data["by_type"])
    )
    table_rows = "".join(
        f"""<tr>
          <td><span class="pill {esc(r['severity'])}">{esc(r['severity'])}</span></td>
          <td>{esc(r['type'].replace('_', ' '))}</td>
          <td>{esc(r['order_id'])}</td>
          <td>{esc(r['payment_refs'])}</td>
          <td>${money_str(r['expected_amount'])}</td>
          <td>${money_str(r['actual_amount'])}</td>
          <td>${money_str(r['amount_at_risk'])}</td>
          <td>{esc(r['note'])}</td>
        </tr>"""
        for r in rows
    ) or '<tr><td colspan="8" class="empty">No discrepancies match this filter.</td></tr>'
    s = data["summary"]
    import_cta = "" if data["orders"] and data["payments"] else '<div class="notice">Upload both CSV files to populate the dashboard.</div>'
    body = f"""
    <section class="dashboard">
      <div class="heading">
        <div><h1>Revenue reconciliation</h1><p>Deterministic comparison of order records and processor activity.</p></div>
        <a class="button" href="/import">Import CSVs</a>
      </div>
      {import_cta}
      <section class="metrics">
        <article><span>Total orders</span><strong>{s['total_orders']}</strong></article>
        <article><span>Total payments</span><strong>{s['total_payments']}</strong></article>
        <article><span>Value reconciled</span><strong>${money_str(s['total_reconciled'])}</strong></article>
        <article><span>Value in dispute</span><strong>${money_str(s['total_dispute'])}</strong></article>
        <article><span>Money at risk</span><strong>${money_str(s['money_at_risk'])}</strong></article>
      </section>
      <section class="split">
        <article class="panel"><h2>Risk by discrepancy type</h2>{bars or '<p class="empty">No discrepancies yet.</p>'}</article>
        <article class="panel"><h2>Plain-language explanation</h2><p>Generate an explanation for the current filtered rows. The backend calls the model and caches the result.</p><form method="post" action="/explain"><input type="hidden" name="type" value="{esc(type_filter)}"><input type="hidden" name="q" value="{esc(search)}"><button class="button" type="submit">Explain current view</button></form></article>
      </section>
      <section class="panel">
        <div class="table-head">
          <h2>Discrepancy drill-down</h2>
          <form class="filters" method="get">
            <input name="q" value="{esc(search)}" placeholder="Search order, transaction, note">
            <select name="type">{options}</select>
            <button class="button ghost" type="submit">Filter</button>
          </form>
        </div>
        <div class="table-wrap"><table><thead><tr><th>Priority</th><th>Type</th><th>Order</th><th>Payment refs</th><th>Expected</th><th>Actual</th><th>At risk</th><th>Why it matters</th></tr></thead><tbody>{table_rows}</tbody></table></div>
      </section>
    </section>"""
    return layout("Revenue Audit", body, user)


def import_page(user, error="", message=""):
    body = f"""
    <section class="panel import">
      <h1>Import datasets</h1>
      <p>Upload the store order export and payment processor export. A new import replaces the current user's prior data.</p>
      {'<p class="error">' + esc(error) + '</p>' if error else ''}
      {'<p class="success">' + esc(message) + '</p>' if message else ''}
      <form method="post" enctype="multipart/form-data">
        <label>orders.csv<input name="orders" type="file" accept=".csv,text/csv" required></label>
        <label>payments.csv<input name="payments" type="file" accept=".csv,text/csv" required></label>
        <button class="button" type="submit">Import and reconcile</button>
      </form>
    </section>"""
    return layout("Import datasets", body, user)


def explanation_page(user, explanation):
    body = f"""
    <section class="panel explanation">
      <h1>Explanation</h1>
      <pre>{esc(explanation)}</pre>
      <a class="button" href="/">Back to dashboard</a>
    </section>"""
    return layout("Explanation", body, user)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        user = self.current_user()
        parsed = urlparse(self.path)
        if parsed.path == "/static/style.css":
            self.send_css()
        elif parsed.path == "/signup":
            self.send_html(login_form("signup"))
        elif parsed.path == "/login":
            self.send_html(login_form("login"))
        elif parsed.path == "/logout":
            self.logout()
        elif parsed.path == "/import":
            self.require_user(user) and self.send_html(import_page(user))
        elif parsed.path == "/":
            self.require_user(user) and self.send_html(dashboard(user, parse_qs(parsed.query)))
        else:
            self.not_found()

    def do_POST(self):
        user = self.current_user()
        parsed = urlparse(self.path)
        if parsed.path in {"/signup", "/login"}:
            self.handle_auth(parsed.path)
        elif parsed.path == "/import":
            self.require_user(user) and self.handle_import(user)
        elif parsed.path == "/explain":
            self.require_user(user) and self.handle_explain(user)
        else:
            self.not_found()

    def handle_auth(self, path):
        length = int(self.headers.get("Content-Length", "0"))
        data = parse_qs(self.rfile.read(length).decode())
        email = data.get("email", [""])[0].strip().lower()
        password = data.get("password", [""])[0]
        if not email or len(password) < 8:
            self.send_html(login_form("signup" if path == "/signup" else "login", "Use a valid email and a password of at least 8 characters."), 400)
            return
        with connect() as db:
            if path == "/signup":
                try:
                    cur = db.execute("INSERT INTO users (email, password_hash) VALUES (?, ?)", (email, hash_password(password)))
                    user_id = cur.lastrowid
                except sqlite3.IntegrityError:
                    self.send_html(login_form("signup", "That email is already registered."), 409)
                    return
            else:
                row = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
                if not row or not verify_password(password, row["password_hash"]):
                    self.send_html(login_form("login", "Invalid email or password."), 401)
                    return
                user_id = row["id"]
            token = secrets.token_urlsafe(32)
            db.execute("INSERT INTO sessions (token, user_id) VALUES (?, ?)", (token, user_id))
        self.redirect("/", cookie_value=sign_token(token))

    def handle_import(self, user):
        form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": self.headers.get("Content-Type")})
        try:
            orders_file = form["orders"]
            payments_file = form["payments"]
            orders_text = orders_file.file.read().decode("utf-8-sig")
            payments_text = payments_file.file.read().decode("utf-8-sig")
            order_count, payment_count = import_csvs(user["id"], orders_text, payments_text)
        except Exception as exc:
            self.send_html(import_page(user, error=str(exc)), 400)
            return
        self.send_html(import_page(user, message=f"Imported {order_count} orders and {payment_count} payments."))

    def handle_explain(self, user):
        length = int(self.headers.get("Content-Length", "0"))
        data = parse_qs(self.rfile.read(length).decode())
        rec = reconcile(user["id"])
        rows = rec["rows"]
        type_filter = data.get("type", [""])[0]
        search = data.get("q", [""])[0].strip().lower()
        if type_filter:
            rows = [r for r in rows if r["type"] == type_filter]
        if search:
            rows = [r for r in rows if search in json.dumps(r).lower()]
        explanation, _ = explain_with_llm(user["id"], rows)
        self.send_html(explanation_page(user, explanation))

    def current_user(self):
        jar = cookies.SimpleCookie(self.headers.get("Cookie"))
        morsel = jar.get(SESSION_COOKIE)
        token = unsign_token(morsel.value) if morsel else None
        if not token:
            return None
        with connect() as db:
            row = db.execute(
                "SELECT users.id, users.email FROM sessions JOIN users ON users.id = sessions.user_id WHERE sessions.token = ?",
                (token,),
            ).fetchone()
        return dict(row) if row else None

    def require_user(self, user):
        if user:
            return True
        self.redirect("/login")
        return False

    def logout(self):
        jar = cookies.SimpleCookie(self.headers.get("Cookie"))
        morsel = jar.get(SESSION_COOKIE)
        token = unsign_token(morsel.value) if morsel else None
        if token:
            with connect() as db:
                db.execute("DELETE FROM sessions WHERE token = ?", (token,))
        self.redirect("/login", cookie_value="deleted", max_age=0)

    def redirect(self, location, cookie_value=None, max_age=None):
        self.send_response(303)
        self.send_header("Location", location)
        if cookie_value is not None:
            value = f"{SESSION_COOKIE}={cookie_value}; Path=/; HttpOnly; SameSite=Lax"
            if max_age is not None:
                value += f"; Max-Age={max_age}"
            self.send_header("Set-Cookie", value)
        self.end_headers()

    def send_html(self, content, status=200):
        payload = content.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def send_css(self):
        payload = CSS.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/css; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def not_found(self):
        self.send_html(layout("Not found", '<section class="panel"><h1>Not found</h1></section>'), 404)

    def log_message(self, fmt, *args):
        return


CSS = """
:root { color-scheme: light; --ink:#18212f; --muted:#667085; --line:#d7dde7; --bg:#f7f8fa; --panel:#ffffff; --blue:#2563eb; --green:#12805c; --red:#be123c; --amber:#b45309; }
* { box-sizing: border-box; }
body { margin:0; font-family: Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, Arial, sans-serif; background:var(--bg); color:var(--ink); }
a { color:var(--blue); text-decoration:none; }
.topbar { height:64px; display:flex; align-items:center; justify-content:space-between; padding:0 28px; background:#fff; border-bottom:1px solid var(--line); position:sticky; top:0; z-index:2; }
.brand { font-weight:760; color:var(--ink); font-size:18px; }
nav { display:flex; align-items:center; gap:12px; color:var(--muted); }
main { max-width:1180px; margin:0 auto; padding:28px; }
h1 { margin:0; font-size:30px; line-height:1.1; letter-spacing:0; }
h2 { margin:0 0 16px; font-size:18px; }
p { color:var(--muted); line-height:1.55; }
.button { display:inline-flex; align-items:center; justify-content:center; min-height:40px; padding:0 14px; border-radius:6px; border:1px solid var(--blue); background:var(--blue); color:#fff; font-weight:680; cursor:pointer; }
.button.ghost { background:#fff; color:var(--ink); border-color:var(--line); }
.auth-panel, .panel { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:24px; box-shadow:0 1px 2px rgba(16,24,40,.04); }
.auth-panel { max-width:420px; margin:48px auto; }
form { display:grid; gap:16px; }
label { display:grid; gap:7px; font-size:14px; font-weight:650; color:#344054; }
input, select { width:100%; min-height:40px; border:1px solid var(--line); border-radius:6px; padding:8px 10px; font:inherit; background:#fff; }
.error { color:var(--red); background:#fff1f2; border:1px solid #fecdd3; padding:10px 12px; border-radius:6px; }
.success, .notice { color:var(--green); background:#ecfdf3; border:1px solid #abefc6; padding:10px 12px; border-radius:6px; }
.heading { display:flex; align-items:flex-start; justify-content:space-between; gap:20px; margin-bottom:22px; }
.metrics { display:grid; grid-template-columns:repeat(5, minmax(0,1fr)); gap:14px; margin:18px 0; }
.metrics article { background:#fff; border:1px solid var(--line); border-radius:8px; padding:16px; }
.metrics span { display:block; color:var(--muted); font-size:13px; margin-bottom:8px; }
.metrics strong { font-size:24px; letter-spacing:0; }
.split { display:grid; grid-template-columns:1.4fr .9fr; gap:18px; margin-bottom:18px; }
.bar-row { display:grid; grid-template-columns:180px 1fr 100px; align-items:center; gap:12px; margin:12px 0; font-size:14px; }
.bar-track { height:12px; background:#eef2f7; border-radius:99px; overflow:hidden; }
.bar-track span { display:block; height:100%; background:linear-gradient(90deg, #2563eb, #16a34a); }
.table-head { display:flex; align-items:start; justify-content:space-between; gap:16px; margin-bottom:12px; }
.filters { display:grid; grid-template-columns:220px 180px auto; gap:10px; }
.table-wrap { overflow:auto; border:1px solid var(--line); border-radius:8px; }
table { width:100%; border-collapse:collapse; min-width:980px; background:#fff; }
th, td { padding:11px 12px; border-bottom:1px solid var(--line); text-align:left; font-size:14px; vertical-align:top; }
th { background:#f2f4f7; color:#475467; font-size:12px; text-transform:uppercase; letter-spacing:.04em; }
.pill { display:inline-flex; border-radius:99px; padding:3px 8px; font-size:12px; font-weight:760; text-transform:capitalize; }
.pill.critical { color:#9f1239; background:#ffe4e6; }
.pill.high { color:#92400e; background:#fef3c7; }
.pill.medium { color:#175cd3; background:#dbeafe; }
.empty { color:var(--muted); text-align:center; padding:22px; }
.import { max-width:720px; margin:36px auto; }
.explanation pre { white-space:pre-wrap; font-family:inherit; color:#344054; line-height:1.55; background:#f9fafb; padding:16px; border-radius:8px; border:1px solid var(--line); }
@media (max-width: 900px) {
  main { padding:18px; }
  .heading, .table-head { display:grid; }
  .metrics { grid-template-columns:1fr 1fr; }
  .split { grid-template-columns:1fr; }
  .filters { grid-template-columns:1fr; }
  .bar-row { grid-template-columns:1fr; }
}
"""


def main():
    init_db()
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"Serving on http://127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()

