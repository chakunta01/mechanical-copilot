"""Test configuration: isolated SQLite DB, offline LLM/embeddings, TestClient."""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ["DATABASE_URL"] = "sqlite:///./data/test_copilot.db"
os.environ["LLM_PROVIDER"] = "fake"
os.environ["EMBEDDINGS_PROVIDER"] = "hashing"
os.environ["EMBEDDINGS_DIM"] = "256"  # pin: .env must not leak real-model dim into tests
os.environ["HASHING_DIM"] = "256"
os.environ["UPLOAD_DIR"] = "./data/test_uploads"
os.environ["RATE_LIMIT_PER_MIN"] = "1000"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.db import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402
from app.services.vector_store import get_vector_store  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _setup_db():
    Path("./data").mkdir(exist_ok=True)
    # Fresh database per test run: no cross-run email collisions.
    if engine.url.get_backend_name() == "sqlite":
        db_file = engine.url.database
        if db_file and Path(db_file).exists():
            Path(db_file).unlink()
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture()
def clean_vector_store():
    store = get_vector_store()
    if hasattr(store, "_by_doc"):
        store._by_doc.clear()
    yield store
    if hasattr(store, "_by_doc"):
        store._by_doc.clear()


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def auth_headers(client) -> dict[str, str]:
    email = f"t_{uuid.uuid4().hex[:8]}@example.com"
    r = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "test-password-123", "full_name": "Test Engineer"},
    )
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
