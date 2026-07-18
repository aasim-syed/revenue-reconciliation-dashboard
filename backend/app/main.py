from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import ALLOWED_ORIGINS
from .db.connection import init_db
from .models.schemas import HealthResponse
from .routes import auth_routes, dashboard_routes, explain_routes, import_routes


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Revenue Audit API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(ALLOWED_ORIGINS),
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    # The frontend reads `payload.error`; keep that contract instead of FastAPI's default `detail` key.
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"error": "Malformed or missing request data."})


@app.get("/api/health", response_model=HealthResponse)
def health():
    return {"ok": True}


app.include_router(auth_routes.router)
app.include_router(dashboard_routes.router)
app.include_router(import_routes.router)
app.include_router(explain_routes.router)
