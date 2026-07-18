from typing import Optional

from fastapi import Depends, HTTPException, Request

from .config import SESSION_COOKIE
from .db.repositories import get_user_by_session_token
from .services.security import unsign_token


def get_session_token(request: Request) -> Optional[str]:
    raw = request.cookies.get(SESSION_COOKIE)
    return unsign_token(raw) if raw else None


def get_current_user(token: Optional[str] = Depends(get_session_token)) -> Optional[dict]:
    if not token:
        return None
    return get_user_by_session_token(token)


def require_current_user(user: Optional[dict] = Depends(get_current_user)) -> dict:
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user
