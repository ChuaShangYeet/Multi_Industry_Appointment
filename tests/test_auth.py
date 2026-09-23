"""Authentication + RBAC login gates (PART 2.2)."""
from app.enums import AccountStatus
from app.models.user import User
from tests.conftest import auth_headers, register_business, register_customer


def test_customer_register_and_login(client):
    register_customer(client, "jane@example.com")

    resp = client.post(
        "/api/v1/auth/customer/login", json={"email": "jane@example.com", "password": "Password123!"}
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "customer"


def test_customer_login_wrong_password_rejected(client):
    register_customer(client, "jane@example.com")
    resp = client.post("/api/v1/auth/customer/login", json={"email": "jane@example.com", "password": "wrong"})
    assert resp.status_code == 401


def test_suspended_customer_is_blocked_at_login(client, db_session):
    register_customer(client, "jane@example.com")
    user = db_session.query(User).filter(User.email == "jane@example.com").first()
    user.account_status = AccountStatus.SUSPENDED
    db_session.commit()

    resp = client.post(
        "/api/v1/auth/customer/login", json={"email": "jane@example.com", "password": "Password123!"}
    )
    assert resp.status_code == 403


def test_suspended_customer_is_blocked_mid_session(client, db_session):
    """A token issued before suspension must stop working immediately, not just at the next login."""
    token = register_customer(client, "jane@example.com")
    user = db_session.query(User).filter(User.email == "jane@example.com").first()
    user.account_status = AccountStatus.BANNED
    db_session.commit()

    resp = client.get("/api/v1/users/me", headers=auth_headers(token))
    assert resp.status_code == 403


def test_business_self_registration_starts_pending(client):
    token = register_business(client, "salon@example.com")
    resp = client.get("/api/v1/businesses/me", headers=auth_headers(token))
    assert resp.status_code == 200
    assert resp.json()["approval_status"] == "Pending"


def test_pending_business_is_blocked_from_core_features(client):
    """PART 2.2: Pending/Suspended businesses get 403 on core features (here: managing services)."""
    token = register_business(client, "salon@example.com")
    resp = client.post(
        "/api/v1/businesses/me/services",
        json={"name": "Haircut", "duration_minutes": 30},
        headers=auth_headers(token),
    )
    assert resp.status_code == 403


def test_pending_business_can_still_view_and_edit_its_own_profile(client):
    """Login itself succeeds, and the business can see/update its own account while awaiting approval."""
    token = register_business(client, "salon@example.com")
    resp = client.patch(
        "/api/v1/businesses/me", json={"description": "Best salon in town"}, headers=auth_headers(token)
    )
    assert resp.status_code == 200
    assert resp.json()["description"] == "Best salon in town"


def test_unapproved_business_hidden_from_public_discovery(client):
    register_business(client, "salon@example.com")
    resp = client.get("/api/v1/businesses")
    assert resp.status_code == 200
    assert resp.json()["items"] == []
