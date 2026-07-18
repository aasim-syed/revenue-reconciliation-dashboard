from typing import Optional

from fastapi import APIRouter, Depends, Request, Response

from ..config import COOKIE_SECURE, SESSION_COOKIE
from ..deps import get_current_user, get_session_token
from ..models.schemas import AuthRequest, AuthResponse, LogoutResponse, MeResponse
from ..services import auth_service
from ..services.rate_limit import check_rate_limit
from ..services.security import sign_token

router = APIRouter(prefix="/api", tags=["auth"])


def _attach_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=sign_token(token),
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="none" if COOKIE_SECURE else "lax",
        path="/",
    )


def _rate_limit_key(request: Request, email: str) -> str:
    ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else "unknown")
    return f"{ip}:{(email or '').strip().lower()}"


@router.post("/signup", response_model=AuthResponse)
def signup(payload: AuthRequest, request: Request, response: Response):
    check_rate_limit(_rate_limit_key(request, payload.email))
    user, token = auth_service.signup(payload.email, payload.password)
    _attach_session_cookie(response, token)
    return {"user": user}


@router.post("/login", response_model=AuthResponse)
def login(payload: AuthRequest, request: Request, response: Response):
    check_rate_limit(_rate_limit_key(request, payload.email))
    user, token = auth_service.login(payload.email, payload.password)
    _attach_session_cookie(response, token)
    return {"user": user}


@router.post("/logout", response_model=LogoutResponse)
def logout(response: Response, token: Optional[str] = Depends(get_session_token)):
    auth_service.logout(token)
    response.delete_cookie(key=SESSION_COOKIE, path="/", secure=COOKIE_SECURE, samesite="none" if COOKIE_SECURE else "lax")
    return {"ok": True}


@router.get("/me", response_model=MeResponse)
def me(user: Optional[dict] = Depends(get_current_user)):
    return {"user": user}
