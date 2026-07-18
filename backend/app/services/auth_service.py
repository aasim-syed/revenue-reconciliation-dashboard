import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from .. import config
from ..db.connection import IntegrityError
from ..db.repositories import create_session, create_user, delete_session, get_user_by_email, get_user_by_session_token
from .security import hash_password, verify_password

SESSION_TIMESTAMP_FORMATS = ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S")


def _validate_credentials(email, password):
    email = (email or "").strip().lower()
    if not email or len(password or "") < 8:
        raise HTTPException(status_code=400, detail="Use a valid email and a password of at least 8 characters.")
    return email


def signup(email, password):
    email = _validate_credentials(email, password)
    try:
        user_id = create_user(email, hash_password(password))
    except (sqlite3.IntegrityError, IntegrityError):
        raise HTTPException(status_code=409, detail="That email is already registered.")
    token = secrets.token_urlsafe(32)
    create_session(user_id, token)
    return {"id": user_id, "email": email}, token


def login(email, password):
    email = _validate_credentials(email, password)
    row = get_user_by_email(email)
    if not row or not verify_password(password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    token = secrets.token_urlsafe(32)
    create_session(row["id"], token)
    return {"id": row["id"], "email": email}, token


def logout(token):
    if token:
        delete_session(token)


def _parse_created_at(value):
    """Sessions.created_at is a Postgres TIMESTAMPTZ (already a datetime) or SQLite TEXT.
    An unparseable value is treated as already-expired (fail closed) rather than trusted."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value or "")
    for fmt in SESSION_TIMESTAMP_FORMATS:
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return datetime.min.replace(tzinfo=timezone.utc)


def get_current_user_for_token(token):
    """Looks up the session and enforces a rolling max age; expired sessions are deleted
    on read so a stolen or forgotten cookie stops working instead of lasting forever."""
    if not token:
        return None
    row = get_user_by_session_token(token)
    if not row:
        return None
    created_at = _parse_created_at(row.get("created_at"))
    age = datetime.now(timezone.utc) - created_at
    if age > timedelta(days=config.SESSION_MAX_AGE_DAYS):
        delete_session(token)
        return None
    return {"id": row["id"], "email": row["email"]}
