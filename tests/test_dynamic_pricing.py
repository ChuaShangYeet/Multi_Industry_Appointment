"""
THE DYNAMIC PRICING ENGINE (app.services.availability.calculate_dynamic_price
and friends). Split into pure unit tests for the pricing math itself, and
integration tests for the public inventory listing that actually surfaces it.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.enums import AppointmentStatus, AppointmentType, BusinessApprovalStatus, BusinessCategory, SpaceInventoryType
from app.models.appointment import Appointment
from app.models.business import Business
from app.models.details import HotelRoomItem
from app.models.resource import Service, SpaceInventory
from app.models.user import User
from app.security import hash_password
from app.services.availability import (
    calculate_dynamic_price,
    calculate_resource_dynamic_price,
    calculate_utilization_rate,
)
from tests.conftest import approve_business, auth_headers, login_admin, make_admin, register_business, register_customer

# A Wednesday, comfortably outside the 24h last-minute window from REQUEST_TIME.
BOOKING_DATE = datetime(2030, 1, 2, 10, 0, tzinfo=timezone.utc)
REQUEST_TIME = datetime(2030, 1, 1, 8, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# calculate_dynamic_price - pure function, no DB
# ---------------------------------------------------------------------------
def test_no_adjustment_at_neutral_utilization_on_a_weekday():
    # 50% utilization is inside the neutral (30-80%) band, and a Wednesday
    # isn't a weekend - price passes through unchanged.
    assert calculate_dynamic_price(100.0, 0.5, BOOKING_DATE, REQUEST_TIME) == 100.0


def test_high_utilization_applies_surge():
    assert calculate_dynamic_price(100.0, 0.81, BOOKING_DATE, REQUEST_TIME) == 120.0


def test_low_utilization_applies_discount():
    assert calculate_dynamic_price(100.0, 0.29, BOOKING_DATE, REQUEST_TIME) == 90.0


def test_last_minute_premium_requires_both_within_24h_and_high_utilization():
    soon = REQUEST_TIME + timedelta(hours=12)
    # High utilization alone, but not last-minute -> no urgency premium.
    far_out = REQUEST_TIME + timedelta(days=5)
    assert calculate_dynamic_price(100.0, 0.6, far_out, REQUEST_TIME) == 100.0
    # Last-minute alone, but utilization not > 50% -> no urgency premium.
    assert calculate_dynamic_price(100.0, 0.4, soon, REQUEST_TIME) == 100.0
    # Both conditions met -> urgency premium applies.
    assert calculate_dynamic_price(100.0, 0.6, soon, REQUEST_TIME) == 115.0


def test_last_minute_premium_does_not_apply_to_a_past_booking_date():
    past = REQUEST_TIME - timedelta(hours=1)
    assert calculate_dynamic_price(100.0, 0.9, past, REQUEST_TIME) == 120.0  # surge still applies, urgency doesn't


def test_weekend_surge_applies_on_friday_and_saturday():
    friday = datetime(2030, 1, 4, 10, 0, tzinfo=timezone.utc)
    saturday = datetime(2030, 1, 5, 10, 0, tzinfo=timezone.utc)
    sunday = datetime(2030, 1, 6, 10, 0, tzinfo=timezone.utc)
    assert calculate_dynamic_price(100.0, 0.5, friday, REQUEST_TIME) == 110.0
    assert calculate_dynamic_price(100.0, 0.5, saturday, REQUEST_TIME) == 110.0
    assert calculate_dynamic_price(100.0, 0.5, sunday, REQUEST_TIME) == 100.0


def test_multipliers_stack_multiplicatively():
    # High utilization (x1.20) + last-minute (x1.15) + Friday (x1.10):
    # a Thursday-evening request for a Friday-morning slot, 14h out.
    request_time = datetime(2030, 1, 3, 20, 0, tzinfo=timezone.utc)  # Thursday
    friday_soon = datetime(2030, 1, 4, 10, 0, tzinfo=timezone.utc)  # Friday, 14h later
    price = calculate_dynamic_price(100.0, 0.9, friday_soon, request_time)
    assert price == round(100.0 * 1.20 * 1.15 * 1.10, 2)


def test_naive_datetimes_are_rejected():
    with pytest.raises(ValueError):
        calculate_dynamic_price(100.0, 0.5, datetime(2030, 1, 2, 10, 0), REQUEST_TIME)


# ---------------------------------------------------------------------------
# calculate_utilization_rate / calculate_resource_dynamic_price - hit the DB
# ---------------------------------------------------------------------------
def _make_hotel_with_room(db, total_quantity=5, price=100.0, dynamic=True):
    business = Business(
        email="hotel@example.com",
        password_hash=hash_password("x"),
        business_name="Test Hotel",
        category=BusinessCategory.HOTEL,
        approval_status=BusinessApprovalStatus.APPROVED,
    )
    service = None
    db.add(business)
    db.commit()
    db.refresh(business)
    service = Service(business_id=business.id, name="Room Booking", duration_minutes=1440)
    room = SpaceInventory(
        business_id=business.id,
        inventory_type=SpaceInventoryType.HOTEL_ROOM,
        category_name="Deluxe Room",
        total_quantity=total_quantity,
        price=price,
        is_dynamic_pricing_enabled=dynamic,
    )
    db.add_all([service, room])
    db.commit()
    db.refresh(service)
    db.refresh(room)
    return business, service, room


def _make_customer(db) -> User:
    user = User(email="jane@example.com", password_hash=hash_password("x"), first_name="Jane", last_name="Doe")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_utilization_rate_reflects_occupied_over_total(db_session):
    _, service, room = _make_hotel_with_room(db_session, total_quantity=4)
    user = _make_customer(db_session)
    start = BOOKING_DATE
    end = start + timedelta(days=1)

    for _ in range(3):
        appt = Appointment(
            user_id=user.id, business_id=room.business_id, service_id=service.id, space_inventory_id=room.id,
            appointment_type=AppointmentType.HOTEL, start_datetime=start, end_datetime=end,
            status=AppointmentStatus.CONFIRMED,
        )
        db_session.add(appt)
        db_session.flush()
        db_session.add(HotelRoomItem(appointment_id=appt.id, space_inventory_id=room.id, quantity=1))
    db_session.commit()

    assert calculate_utilization_rate(db_session, space_inventory=room, start_datetime=start, end_datetime=end) == 0.75


def test_utilization_rate_is_zero_for_a_zero_capacity_resource(db_session):
    _, _, room = _make_hotel_with_room(db_session, total_quantity=0)
    start, end = BOOKING_DATE, BOOKING_DATE + timedelta(days=1)
    assert calculate_utilization_rate(db_session, space_inventory=room, start_datetime=start, end_datetime=end) == 0.0


def test_resource_dynamic_price_is_none_when_disabled(db_session):
    _, _, room = _make_hotel_with_room(db_session, dynamic=False)
    start, end = BOOKING_DATE, BOOKING_DATE + timedelta(days=1)
    assert calculate_resource_dynamic_price(db_session, space_inventory=room, start_datetime=start, end_datetime=end) is None


def test_resource_dynamic_price_is_none_without_a_base_price(db_session):
    _, _, room = _make_hotel_with_room(db_session, price=None, dynamic=True)
    start, end = BOOKING_DATE, BOOKING_DATE + timedelta(days=1)
    assert calculate_resource_dynamic_price(db_session, space_inventory=room, start_datetime=start, end_datetime=end) is None


def test_resource_dynamic_price_reflects_high_utilization(db_session):
    _, service, room = _make_hotel_with_room(db_session, total_quantity=5, price=100.0, dynamic=True)
    user = _make_customer(db_session)
    start, end = BOOKING_DATE, BOOKING_DATE + timedelta(days=1)

    for _ in range(5):  # 5/5 = 100% utilization
        appt = Appointment(
            user_id=user.id, business_id=room.business_id, service_id=service.id, space_inventory_id=room.id,
            appointment_type=AppointmentType.HOTEL, start_datetime=start, end_datetime=end,
            status=AppointmentStatus.CONFIRMED,
        )
        db_session.add(appt)
        db_session.flush()
        db_session.add(HotelRoomItem(appointment_id=appt.id, space_inventory_id=room.id, quantity=1))
    db_session.commit()

    price = calculate_resource_dynamic_price(
        db_session, space_inventory=room, start_datetime=start, end_datetime=end, request_time=REQUEST_TIME
    )
    assert price == 120.0  # 100% utilization -> surge only (BOOKING_DATE is a Wednesday, well outside 24h)


# ---------------------------------------------------------------------------
# Wired into GET /businesses/{id}/inventory
# ---------------------------------------------------------------------------
def _setup_dynamic_hotel(client, db_session, total_rooms=5, price=100, dynamic=True):
    biz_token = register_business(client, "hotel@example.com", category="Hotel")
    make_admin(db_session)
    admin_token = login_admin(client)
    business_id = client.get("/api/v1/admin/businesses", headers=auth_headers(admin_token)).json()["items"][0]["id"]
    approve_business(client, admin_token, business_id)
    client.post(
        "/api/v1/businesses/me/services",
        json={"name": "Room Booking", "duration_minutes": 1440},
        headers=auth_headers(biz_token),
    )
    space_resp = client.post(
        "/api/v1/businesses/me/inventory",
        json={
            "inventory_type": "Hotel Room",
            "category_name": "Deluxe Room",
            "total_quantity": total_rooms,
            "price": price,
            "is_dynamic_pricing_enabled": dynamic,
        },
        headers=auth_headers(biz_token),
    )
    assert space_resp.status_code == 201, space_resp.text
    return biz_token, business_id, space_resp.json()["id"]


def test_public_inventory_omits_dynamic_price_without_a_date_range(client, db_session):
    _, business_id, _ = _setup_dynamic_hotel(client, db_session)
    resp = client.get(f"/api/v1/businesses/{business_id}/inventory")
    assert resp.status_code == 200
    assert resp.json()[0]["dynamic_price"] is None


def test_public_inventory_omits_dynamic_price_when_not_enabled(client, db_session):
    _, business_id, _ = _setup_dynamic_hotel(client, db_session, dynamic=False)
    start = datetime.now(timezone.utc) + timedelta(days=5)
    resp = client.get(
        f"/api/v1/businesses/{business_id}/inventory",
        params={"start_datetime": start.isoformat(), "end_datetime": (start + timedelta(days=1)).isoformat()},
    )
    assert resp.status_code == 200
    assert resp.json()[0]["dynamic_price"] is None
    assert resp.json()[0]["is_dynamic_pricing_enabled"] is False


def test_public_inventory_surfaces_dynamic_price_for_a_date_range(client, db_session):
    biz_token, business_id, space_id = _setup_dynamic_hotel(client, db_session, total_rooms=2, price=100)
    cust_token = register_customer(client)
    start = datetime.now(timezone.utc) + timedelta(days=5)
    end = start + timedelta(days=1)

    # Fill both rooms -> 100% utilization -> surge.
    for _ in range(2):
        resp = client.post(
            "/api/v1/appointments",
            json={
                "business_id": business_id,
                "service_id": client.get("/api/v1/businesses/me/services", headers=auth_headers(biz_token)).json()[0]["id"],
                "room_selections": [{"space_inventory_id": space_id, "quantity": 1}],
                "start_datetime": start.isoformat(),
                "end_datetime": end.isoformat(),
                "hotel_details": {"no_of_guests": 1},
            },
            headers=auth_headers(cust_token),
        )
        assert resp.status_code == 201, resp.text

    resp = client.get(
        f"/api/v1/businesses/{business_id}/inventory",
        params={"start_datetime": start.isoformat(), "end_datetime": end.isoformat()},
    )
    assert resp.status_code == 200
    item = resp.json()[0]
    assert item["available_quantity"] == 0
    assert item["dynamic_price"] == 120.0  # 100% utilization -> surge, no other rule active on an arbitrary weekday+5d out


def test_converted_price_reflects_dynamic_price_not_the_flat_rate(client, db_session, monkeypatch):
    from app.routers import resources as resources_router

    monkeypatch.setattr(resources_router, "convert_amount", lambda amount, base, target: amount * 2 if amount else None)

    biz_token, business_id, space_id = _setup_dynamic_hotel(client, db_session, total_rooms=1, price=100)
    cust_token = register_customer(client)
    start = datetime.now(timezone.utc) + timedelta(days=5)
    end = start + timedelta(days=1)

    service_id = client.get("/api/v1/businesses/me/services", headers=auth_headers(biz_token)).json()[0]["id"]
    booking = client.post(
        "/api/v1/appointments",
        json={
            "business_id": business_id,
            "service_id": service_id,
            "room_selections": [{"space_inventory_id": space_id, "quantity": 1}],
            "start_datetime": start.isoformat(),
            "end_datetime": end.isoformat(),
            "hotel_details": {"no_of_guests": 1},
        },
        headers=auth_headers(cust_token),
    )
    assert booking.status_code == 201, booking.text

    resp = client.get(
        f"/api/v1/businesses/{business_id}/inventory",
        params={"start_datetime": start.isoformat(), "end_datetime": end.isoformat(), "target_currency": "USD"},
    )
    item = resp.json()[0]
    assert item["dynamic_price"] == 120.0  # 100% utilization surge
    assert item["converted_price"] == 240.0  # converted from dynamic_price (x2 via the monkeypatched convert_amount), not the flat 100
