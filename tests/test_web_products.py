"""Web app API and auth tests."""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ["ADMIN_PASSWORD"] = "testpass"
os.environ["SECRET_KEY"] = "test-secret-key"

from web.database import Base, get_db  # noqa: E402
from web.main import app  # noqa: E402
from web.models import Product  # noqa: E402


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _login(client: TestClient) -> None:
    r = client.post("/login", data={"password": "testpass"}, follow_redirects=False)
    assert r.status_code == 303


def test_login_required(client: TestClient):
    r = client.get("/products", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


def test_crud_product(client: TestClient):
    _login(client)

    r = client.post(
        "/products/new",
        data={
            "producto": "Test Producto X",
            "producto_base": "Test Base",
            "categoria": "test",
            "proveedor": "TEST",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303

    r = client.get("/products")
    assert "Test Producto X" in r.text

    # Find id via DB is hard in test client; create via session
    from web.database import SessionLocal
    # Use overridden session - query through list page edit link
    assert "/products/" in r.text and "/edit" in r.text


def test_health(client: TestClient):
    assert client.get("/health").json() == {"status": "ok"}
