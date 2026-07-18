from .. import config
from .connection import connect


def create_user(email, password_hash):
    """Returns the new user id. Raises sqlite3.IntegrityError / IntegrityError on duplicate email."""
    with connect() as db:
        if config.USE_POSTGRES:
            cur = db.execute("INSERT INTO users (email, password_hash) VALUES (?, ?) RETURNING id", (email, password_hash))
            return cur.fetchone()["id"]
        cur = db.execute("INSERT INTO users (email, password_hash) VALUES (?, ?)", (email, password_hash))
        return cur.lastrowid


def get_user_by_email(email):
    with connect() as db:
        row = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    return dict(row) if row else None


def create_session(user_id, token):
    with connect() as db:
        db.execute("INSERT INTO sessions (token, user_id) VALUES (?, ?)", (token, user_id))


def delete_session(token):
    with connect() as db:
        db.execute("DELETE FROM sessions WHERE token = ?", (token,))


def get_user_by_session_token(token):
    with connect() as db:
        row = db.execute(
            "SELECT users.id, users.email FROM sessions JOIN users ON users.id = sessions.user_id WHERE sessions.token = ?",
            (token,),
        ).fetchone()
    return dict(row) if row else None


def replace_user_data(user_id, orders, payments):
    """Overwrites a user's orders/payments/cached explanations with a fresh import."""
    with connect() as db:
        db.execute("DELETE FROM orders WHERE user_id = ?", (user_id,))
        db.execute("DELETE FROM payments WHERE user_id = ?", (user_id,))
        db.execute("DELETE FROM explanations WHERE user_id = ?", (user_id,))
        db.executemany(
            """
            INSERT INTO orders (user_id, order_id, order_date, customer_email, currency, gross_amount, discount, net_amount, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (user_id, r["order_id"], r["order_date"], r["customer_email"], r["currency"], r["gross_amount"], r["discount"], r["net_amount"], r["status"])
                for r in orders
            ],
        )
        db.executemany(
            """
            INSERT INTO payments (user_id, transaction_ref, processed_at, order_reference, currency, amount, fee, net_settled, type, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (user_id, r["transaction_ref"], r["processed_at"], r["order_reference"], r["currency"], r["amount"], r["fee"], r["net_settled"], r["type"], r["status"])
                for r in payments
            ],
        )


def fetch_orders(user_id):
    with connect() as db:
        return [dict(r) for r in db.execute("SELECT * FROM orders WHERE user_id = ? ORDER BY order_id, id", (user_id,))]


def fetch_payments(user_id):
    with connect() as db:
        return [dict(r) for r in db.execute("SELECT * FROM payments WHERE user_id = ? ORDER BY order_reference, id", (user_id,))]


def get_cached_explanation(user_id, fingerprint):
    with connect() as db:
        row = db.execute("SELECT content FROM explanations WHERE user_id = ? AND fingerprint = ?", (user_id, fingerprint)).fetchone()
    return row["content"] if row else None


def delete_cached_explanation(user_id, fingerprint):
    with connect() as db:
        db.execute("DELETE FROM explanations WHERE user_id = ? AND fingerprint = ?", (user_id, fingerprint))


def save_explanation(user_id, fingerprint, content_json):
    with connect() as db:
        if config.USE_POSTGRES:
            db.execute(
                """
                INSERT INTO explanations (user_id, fingerprint, content) VALUES (?, ?, ?)
                ON CONFLICT (user_id, fingerprint) DO UPDATE SET content = EXCLUDED.content
                """,
                (user_id, fingerprint, content_json),
            )
        else:
            db.execute("INSERT OR REPLACE INTO explanations (user_id, fingerprint, content) VALUES (?, ?, ?)", (user_id, fingerprint, content_json))
