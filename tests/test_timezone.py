"""
Timezone handling: businesses declare their own IANA timezone (which anchors
every appointment booked with them to a real instant), customers get a
display-only timezone preference, and the backend refuses to guess a
timezone for an ambiguous naive datetime.
"""
import pytest

from app.schemas.validators import validate_timezone
from tests.conftest import (
    approve_business,
    auth_headers,
    login_admin,
    make_admin,
    register_business,
    register_customer,
)


def test_validate_timezone_accepts_real_iana_zones():
    for tz in ["UTC", "Asia/Kuala_Lumpur", "America/New_York", "Europe/London"]:
        assert validate_timezone(tz) == tz


def test_validate_timezone_rejects_bogus_names():
    with pytest.raises(ValueError, match="not a recognized IANA timezone"):
        validate_timezone("Mars/Olympus_Mons")


def test_customer_registration_stores_chosen_timezone(client):
    resp = client.post(
        "/api/v1/auth/customer/register",
        json={
            "email": "jane@example.com",
            "password": "Password123!",
            "first_name": "Jane",
            "last_name": "Doe",
            "timezone": "Asia/Kuala_Lumpur",
        },
    )
    assert resp.status_code == 201
    token = resp.json()["access_token"]
    me = client.get("/api/v1/users/me", headers=auth_headers(token))
    assert me.json()["timezone"] == "Asia/Kuala_Lumpur"


def test_customer_registration_rejects_bogus_timezone(client):
    resp = client.post(
        "/api/v1/auth/customer/register",
        json={
            "email": "jane@example.com",
            "password": "Password123!",
            "first_name": "Jane",
            "last_name": "Doe",
            "timezone": "Not/A_Zone",
        },
    )
    assert resp.status_code == 422


def test_customer_defaults_to_utc_when_timezone_omitted(client):
    token = register_customer(client, "jane@example.com")
    me = client.get("/api/v1/users/me", headers=auth_headers(token))
    assert me.json()["timezone"] == "UTC"


def test_business_registration_stores_chosen_timezone_and_it_is_public(client):
    resp = client.post(
        "/api/v1/auth/business/register",
        json={
            "email": "salon@example.com",
            "password": "Password123!",
            "business_name": "Sarah's Salon",
            "category": "Salon",
            "timezone": "Asia/Kuala_Lumpur",
        },
    )
    assert resp.status_code == 201
    token = resp.json()["access_token"]
    mine = client.get("/api/v1/businesses/me", headers=auth_headers(token))
    assert mine.json()["timezone"] == "Asia/Kuala_Lumpur"


def test_business_can_update_its_own_timezone(client):
    token = register_business(client, "salon@example.com")
    resp = client.patch("/api/v1/businesses/me", json={"timezone": "America/New_York"}, headers=auth_headers(token))
    assert resp.status_code == 200
    assert resp.json()["timezone"] == "America/New_York"


def test_business_update_rejects_bogus_timezone(client):
    token = register_business(client, "salon@example.com")
    resp = client.patch("/api/v1/businesses/me", json={"timezone": "Nope"}, headers=auth_headers(token))
    assert resp.status_code == 422


def _setup_approved_salon_with_timezone(client, db_session, tz="Asia/Kuala_Lumpur"):
    biz_token = register_business(client, "salon@example.com")
    client.patch("/api/v1/businesses/me", json={"timezone": tz}, headers=auth_headers(biz_token))
    make_admin(db_session)
    admin_token = login_admin(client)
    business_id = client.get("/api/v1/admin/businesses", headers=auth_headers(admin_token)).json()["items"][0]["id"]
    approve_business(client, admin_token, business_id)
    client.post(
        "/api/v1/businesses/me/services",
        json={"name": "Haircut", "duration_minutes": 30},
        headers=auth_headers(biz_token),
    )
    client.post("/api/v1/businesses/me/staff", json={"name": "Sarah Lee"}, headers=auth_headers(biz_token))
    return biz_token, business_id


def test_appointment_rejects_naive_datetime(client, db_session):
    _, business_id = _setup_approved_salon_with_timezone(client, db_session)
    cust_token = register_customer(client)

    resp = client.post(
        "/api/v1/appointments",
        json={
            "business_id": business_id,
            "service_id": 1,
            "start_datetime": "2030-06-15T14:00:00",  # no UTC offset - ambiguous
            "general_service_details": {},
        },
        headers=auth_headers(cust_token),
    )
    assert resp.status_code == 422
    assert "UTC offset" in resp.text


def test_same_instant_expressed_in_different_timezones_still_conflicts(client, db_session):
    """
    The whole point of anchoring bookings to a real instant: 2030-06-15
    14:00 +08:00 (Kuala Lumpur) and 2030-06-15 06:00 Z (UTC) are the exact
    same moment. A second booking for that instant, expressed with a
    completely different UTC offset, must still be detected as a clash.
    """
    _, business_id = _setup_approved_salon_with_timezone(client, db_session)
    cust_token = register_customer(client)

    first = client.post(
        "/api/v1/appointments",
        json={
            "business_id": business_id,
            "service_id": 1,
            "start_datetime": "2030-06-15T14:00:00+08:00",
            "general_service_details": {},
        },
        headers=auth_headers(cust_token),
    )
    assert first.status_code == 201, first.text

    # Same instant, written as UTC with a "Z" suffix instead of a +08:00 offset.
    second = client.post(
        "/api/v1/appointments",
        json={
            "business_id": business_id,
            "service_id": 1,
            "start_datetime": "2030-06-15T06:00:00Z",
            "general_service_details": {},
        },
        headers=auth_headers(cust_token),
    )
    assert second.status_code == 409


def test_appointments_a_day_apart_in_wall_clock_time_across_offsets_do_not_clash(client, db_session):
    """Sanity check the other direction: genuinely different instants never falsely conflict."""
    _, business_id = _setup_approved_salon_with_timezone(client, db_session)
    cust_token = register_customer(client)

    first = client.post(
        "/api/v1/appointments",
        json={
            "business_id": business_id,
            "service_id": 1,
            "start_datetime": "2030-06-15T14:00:00+08:00",
            "general_service_details": {},
        },
        headers=auth_headers(cust_token),
    )
    assert first.status_code == 201

    second = client.post(
        "/api/v1/appointments",
        json={
            "business_id": business_id,
            "service_id": 1,
            "start_datetime": "2030-06-16T14:00:00+08:00",
            "general_service_details": {},
        },
        headers=auth_headers(cust_token),
    )
    assert second.status_code == 201
