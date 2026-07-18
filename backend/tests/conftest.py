import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("APP_SECRET", "test-secret")

from app import config  # noqa: E402


@pytest.fixture()
def db_path(tmp_path, monkeypatch):
    """Points the app at a throwaway SQLite file for the duration of one test."""
    path = tmp_path / "test.db"
    monkeypatch.setattr(config, "DB_PATH", str(path))
    monkeypatch.setattr(config, "USE_POSTGRES", False)
    from app.db.connection import init_db

    init_db()
    return str(path)


@pytest.fixture()
def user_id(db_path):
    from app.db.repositories import create_user

    return create_user("seed@example.com", "unused-hash")


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """The limiter is a process-global in-memory dict; tests must not leak into each other."""
    from app.services.rate_limit import _attempts

    _attempts.clear()
    yield
    _attempts.clear()


@pytest.fixture()
def no_llm_providers(monkeypatch):
    """Forces the deterministic fallback path so explain tests never call a real LLM API."""
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


@pytest.fixture()
def client(db_path):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
