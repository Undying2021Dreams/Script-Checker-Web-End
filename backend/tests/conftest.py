"""
Test fixtures.

Entra ID tokens can't be minted headlessly, so `get_current_user` is
overridden per-test to act as a given user. Everything below that — the
authorization rules, queries and DB constraints — is the real code path
against a real Postgres database.
"""

import os
import sys
import uuid
from pathlib import Path

# Point at the test database before anything imports `config`, whose
# module-level `settings` reads DATABASE_URL once at import time.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg2://webend:webend_dev_only@localhost:5434/webend_test",
)
os.environ.setdefault("AZURE_CLIENT_ID", "test-client-id")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from database import Base, SessionLocal, engine  # noqa: E402
from main import app  # noqa: E402
from models import User  # noqa: E402
from security import get_current_user  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _schema():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def _clean_tables():
    """Each test starts from an empty database."""
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.exec_driver_sql(f'TRUNCATE TABLE "{table.name}" CASCADE')
    yield


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def make_user(db):
    def _make(role: str = "student", display_name: str | None = None, email: str | None = None) -> User:
        suffix = uuid.uuid4().hex[:8]
        user = User(
            azure_oid=f"oid-{suffix}",
            email=email or f"{role}-{suffix}@example.edu",
            display_name=display_name or f"{role.title()} {suffix}",
            role=role,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    return _make


@pytest.fixture
def client():
    """A TestClient whose authenticated user can be switched via `as_user`."""

    class _Client(TestClient):
        def as_user(self, user: User):
            app.dependency_overrides[get_current_user] = lambda: user
            return self

    with _Client(app) as c:
        yield c
    app.dependency_overrides.clear()
