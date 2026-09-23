"""
Shared pytest fixtures: an isolated in-memory SQLite DB per test (so tests
never touch dev.db or each other), wired into the FastAPI app via a
get_db override, plus a couple of small helpers used across test modules.
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 - registers every table on Base.metadata
from app.database import Base, get_db
from app.enums import AdminRoleLevel
from app.main import app
from app.models.admin import AdminUser
from app.security import hash_password


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def client(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def future_iso(days: int = 1) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def register_customer(client: TestClient, email: str = "jane@example.com", phone_number: str | None = None) -> str:
    body = {"email": email, "password": "Password123!", "first_name": "Jane", "last_name": "Doe"}
    if phone_number is not None:
        body["phone_number"] = phone_number
    resp = client.post("/api/v1/auth/customer/register", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"]


def register_business(client: TestClient, email: str = "salon@example.com", category: str = "Salon") -> str:
    resp = client.post(
        "/api/v1/auth/business/register",
        json={
            "email": email,
            "password": "Password123!",
            "business_name": "Sarah's Salon",
            "category": category,
            "city": "KL",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"]


def make_admin(db_session, email: str = "admin@example.com", password: str = "adminpass123") -> None:
    admin = AdminUser(email=email, password_hash=hash_password(password), role_level=AdminRoleLevel.SUPER_ADMIN)
    db_session.add(admin)
    db_session.commit()


def login_admin(client: TestClient, email: str = "admin@example.com", password: str = "adminpass123") -> str:
    resp = client.post("/api/v1/auth/admin/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def approve_business(client: TestClient, admin_token: str, business_id: int) -> None:
    resp = client.patch(
        f"/api/v1/admin/businesses/{business_id}",
        json={"approval_status": "Approved"},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text
