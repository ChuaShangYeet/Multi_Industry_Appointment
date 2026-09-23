"""International phone number validation/normalization (schemas/validators.py)."""
import pytest

from app.schemas.validators import validate_phone_number
from tests.conftest import auth_headers


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("+14155552671", "+14155552671"),  # US
        ("+60123456789", "+60123456789"),  # Malaysia
        ("+442071838750", "+442071838750"),  # UK
        ("+6591234567", "+6591234567"),  # Singapore
        ("  +14155552671  ", "+14155552671"),  # surrounding whitespace trimmed
        (None, None),
        ("", None),
        ("   ", None),
    ],
)
def test_valid_numbers_normalize_to_e164(raw, expected):
    assert validate_phone_number(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "0123456789",  # no country code prefix
        "not-a-phone",
        "+1234",  # has a "+" but not a real, dialable number
    ],
)
def test_invalid_numbers_are_rejected(raw):
    with pytest.raises(ValueError):
        validate_phone_number(raw)


def test_customer_registration_rejects_number_without_country_code(client):
    resp = client.post(
        "/api/v1/auth/customer/register",
        json={
            "email": "jane@example.com",
            "password": "Password123!",
            "first_name": "Jane",
            "last_name": "Doe",
            "phone_number": "0123456789",
        },
    )
    assert resp.status_code == 422


def test_customer_registration_accepts_any_countrys_number(client):
    resp = client.post(
        "/api/v1/auth/customer/register",
        json={
            "email": "liam@example.com",
            "password": "Password123!",
            "first_name": "Liam",
            "last_name": "Smith",
            "phone_number": "+442071838750",  # UK number
        },
    )
    assert resp.status_code == 201

    token = resp.json()["access_token"]
    me = client.get("/api/v1/users/me", headers=auth_headers(token))
    assert me.json()["phone_number"] == "+442071838750"


def test_customer_can_update_phone_number_to_a_different_country(client):
    from tests.conftest import register_customer

    token = register_customer(client, "jane@example.com")
    resp = client.patch(
        "/api/v1/users/me", json={"phone_number": "+6591234567"}, headers=auth_headers(token)
    )
    assert resp.status_code == 200
    assert resp.json()["phone_number"] == "+6591234567"
