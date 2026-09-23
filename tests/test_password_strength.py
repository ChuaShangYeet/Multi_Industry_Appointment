"""Password strength enforcement: 8+ chars, upper, lower, digit, symbol."""
import pytest

from app.schemas.validators import validate_password_strength


@pytest.mark.parametrize(
    "password",
    [
        "Password123!",
        "Str0ng&Pass",
        "aB3$aB3$",  # exactly 8 characters
    ],
)
def test_strong_passwords_pass(password):
    assert validate_password_strength(password) == password


@pytest.mark.parametrize(
    "password,expected_reason",
    [
        ("Ab1!", "at least 8 characters"),  # too short
        ("password123!", "uppercase"),  # no uppercase
        ("PASSWORD123!", "lowercase"),  # no lowercase
        ("Password!!!!", "number"),  # no digit
        ("Password1234", "symbol"),  # no symbol
    ],
)
def test_weak_passwords_are_rejected(password, expected_reason):
    with pytest.raises(ValueError, match=expected_reason):
        validate_password_strength(password)


def test_customer_registration_rejects_weak_password(client):
    resp = client.post(
        "/api/v1/auth/customer/register",
        json={"email": "jane@example.com", "password": "weak", "first_name": "Jane", "last_name": "Doe"},
    )
    assert resp.status_code == 422


def test_customer_registration_accepts_strong_password(client):
    resp = client.post(
        "/api/v1/auth/customer/register",
        json={"email": "jane@example.com", "password": "Password123!", "first_name": "Jane", "last_name": "Doe"},
    )
    assert resp.status_code == 201


def test_business_registration_rejects_weak_password(client):
    resp = client.post(
        "/api/v1/auth/business/register",
        json={
            "email": "salon@example.com",
            "password": "weak",
            "business_name": "Sarah's Salon",
            "category": "Salon",
        },
    )
    assert resp.status_code == 422


def test_admin_password_reset_rejects_weak_password(client, db_session):
    from tests.conftest import approve_business, auth_headers, login_admin, make_admin, register_business

    register_business(client, "salon@example.com")
    make_admin(db_session)
    admin_token = login_admin(client)
    business_id = client.get(
        "/api/v1/admin/businesses", headers=auth_headers(admin_token)
    ).json()["items"][0]["id"]

    resp = client.post(
        f"/api/v1/admin/businesses/{business_id}/reset-password",
        json={"new_password": "weak"},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 422


def test_login_still_works_without_strength_checks():
    """A login payload is never strength-checked - only registration/reset payloads are."""
    from app.schemas.auth import LoginRequest

    # This would fail validate_password_strength, but LoginRequest doesn't call it.
    login = LoginRequest(email="jane@example.com", password="weak")
    assert login.password == "weak"
