from typing import Optional

from fastapi import Depends, HTTPException, Request

from .config import SESSION_COOKIE
from .services import auth_service
from .services.security import unsign_token


def get_session_token(request: Request) -> Optional[str]:
    raw = request.cookies.get(SESSION_COOKIE)
    return unsign_token(raw) if raw else None


def get_current_user(token: Optional[str] = Depends(get_session_token)) -> Optional[dict]:
    return auth_service.get_current_user_for_token(token)


def require_current_user(user: Optional[dict] = Depends(get_current_user)) -> dict:
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user
