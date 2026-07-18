import secrets
import sqlite3

from fastapi import HTTPException

from ..db.connection import IntegrityError
from ..db.repositories import create_session, create_user, delete_session, get_user_by_email
from .security import hash_password, verify_password


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
