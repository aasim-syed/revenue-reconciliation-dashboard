import os
from decimal import Decimal
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


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
