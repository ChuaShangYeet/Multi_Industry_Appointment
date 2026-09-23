"""
Hotel bookings span a customer-chosen number of nights (check-in to
check-out), not one fixed-duration slot like every other business type -
see the appointments router's end_datetime handling and
AppointmentOut.nights/total_price.
"""
from datetime import datetime, timedelta, timezone

from tests.conftest import auth_headers, approve_business, login_admin, make_admin, register_business, register_customer


def _setup_approved_hotel(client, db_session, total_rooms: int = 1, price: int = 100, capacity_per_unit: int | None = None):
    biz_token = register_business(client, "hotel@example.com", category="Hotel")
    make_admin(db_session)
    admin_token = login_admin(client)
    resp = client.get("/api/v1/admin/businesses", headers=auth_headers(admin_token))
    business_id = resp.json()["items"][0]["id"]
    approve_business(client, admin_token, business_id)

    # Deliberately no price here - a hotel's nightly rate belongs to the
    # room type (SpaceInventory.price below), not this generic booking
    # Service every room type shares.
    service_resp = client.post(
        "/api/v1/businesses/me/services",
        json={"name": "Room Booking", "duration_minutes": 1440},
        headers=auth_headers(biz_token),
    )
    service_id = service_resp.json()["id"]

    inventory_payload = {
        "inventory_type": "Hotel Room",
        "category_name": "Deluxe Room",
        "total_quantity": total_rooms,
        "price": price,
    }
    if capacity_per_unit is not None:
        inventory_payload["capacity_per_unit"] = capacity_per_unit
    inventory_resp = client.post(
        "/api/v1/businesses/me/inventory", json=inventory_payload, headers=auth_headers(biz_token)
    )
    space_id = inventory_resp.json()["id"]

    return biz_token, admin_token, business_id, service_id, space_id


def _book_hotel(client, cust_token, business_id, service_id, space_id, start, end, no_of_rooms=1, no_of_guests=2):
    return _book_hotel_rooms(
        client, cust_token, business_id, service_id,
        [{"space_inventory_id": space_id, "quantity": no_of_rooms}],
        start, end, no_of_guests=no_of_guests,
    )


def _book_hotel_rooms(client, cust_token, business_id, service_id, room_selections, start, end, no_of_guests=2):
    """Like _book_hotel, but takes a list of {space_inventory_id, quantity} - lets tests combine
    several different room types in one booking."""
    return client.post(
        "/api/v1/appointments",
        json={
            "business_id": business_id,
            "service_id": service_id,
            "room_selections": room_selections,
            "start_datetime": start,
            "end_datetime": end,
            "hotel_details": {"no_of_guests": no_of_guests},
        },
        headers=auth_headers(cust_token),
    )


def test_multi_night_hotel_stay_computes_nights_and_total_price(client, db_session):
    _, _, business_id, service_id, space_id = _setup_approved_hotel(client, db_session)
    cust_token = register_customer(client)

    check_in = datetime.now(timezone.utc) + timedelta(days=5, hours=15)
    check_out = check_in + timedelta(days=3)

    resp = _book_hotel(client, cust_token, business_id, service_id, space_id, check_in.isoformat(), check_out.isoformat())
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["appointment_type"] == "Hotel"
    assert body["nights"] == 3
    assert body["total_price"] == 300
    assert body["end_datetime"] is not None


def test_multi_night_price_scales_with_rooms(client, db_session):
    _, _, business_id, service_id, space_id = _setup_approved_hotel(client, db_session, total_rooms=5)
    cust_token = register_customer(client)

    check_in = datetime.now(timezone.utc) + timedelta(days=5)
    check_out = check_in + timedelta(days=2)

    resp = _book_hotel(
        client, cust_token, business_id, service_id, space_id, check_in.isoformat(), check_out.isoformat(), no_of_rooms=3
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["nights"] == 2
    assert body["total_price"] == 100 * 2 * 3


def test_price_belongs_to_room_type_not_the_shared_service(client, db_session):
    """Two room types under the same Service must be able to charge different nightly rates."""
    biz_token, _, business_id, service_id, deluxe_id = _setup_approved_hotel(client, db_session, price=100)
    suite_resp = client.post(
        "/api/v1/businesses/me/inventory",
        json={"inventory_type": "Hotel Room", "category_name": "Suite", "total_quantity": 1, "price": 350},
        headers=auth_headers(biz_token),
    )
    suite_id = suite_resp.json()["id"]
    cust_token = register_customer(client)

    check_in = datetime.now(timezone.utc) + timedelta(days=5)
    check_out = check_in + timedelta(days=1)

    deluxe_booking = _book_hotel(client, cust_token, business_id, service_id, deluxe_id, check_in.isoformat(), check_out.isoformat())
    suite_booking = _book_hotel(client, cust_token, business_id, service_id, suite_id, check_in.isoformat(), check_out.isoformat())

    assert deluxe_booking.json()["total_price"] == 100
    assert suite_booking.json()["total_price"] == 350


def test_public_inventory_reports_available_quantity_for_date_range(client, db_session):
    _, _, business_id, service_id, space_id = _setup_approved_hotel(client, db_session, total_rooms=2)
    cust_token = register_customer(client)

    check_in = datetime.now(timezone.utc) + timedelta(days=5)
    check_out = check_in + timedelta(days=2)
    _book_hotel(client, cust_token, business_id, service_id, space_id, check_in.isoformat(), check_out.isoformat())

    # Overlapping window - 1 of the 2 rooms is now taken.
    overlapping = client.get(
        f"/api/v1/businesses/{business_id}/inventory",
        params={"start_datetime": check_in.isoformat(), "end_datetime": check_out.isoformat()},
    )
    assert overlapping.status_code == 200
    assert overlapping.json()[0]["available_quantity"] == 1

    # Non-overlapping window - both rooms are free.
    later_start = check_out + timedelta(days=1)
    later_end = later_start + timedelta(days=1)
    non_overlapping = client.get(
        f"/api/v1/businesses/{business_id}/inventory",
        params={"start_datetime": later_start.isoformat(), "end_datetime": later_end.isoformat()},
    )
    assert non_overlapping.json()[0]["available_quantity"] == 2

    # No date range given - available_quantity is just absent (null).
    undated = client.get(f"/api/v1/businesses/{business_id}/inventory")
    assert undated.json()[0]["available_quantity"] is None


def test_public_inventory_requires_both_dates_together(client, db_session):
    _, _, business_id, _, _ = _setup_approved_hotel(client, db_session)
    start = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()

    resp = client.get(f"/api/v1/businesses/{business_id}/inventory", params={"start_datetime": start})
    assert resp.status_code == 422


def test_hotel_booking_without_end_datetime_is_rejected(client, db_session):
    _, _, business_id, service_id, space_id = _setup_approved_hotel(client, db_session)
    cust_token = register_customer(client)
    start = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()

    resp = client.post(
        "/api/v1/appointments",
        json={
            "business_id": business_id,
            "service_id": service_id,
            "room_selections": [{"space_inventory_id": space_id, "quantity": 1}],
            "start_datetime": start,
            "hotel_details": {"no_of_guests": 1},
        },
        headers=auth_headers(cust_token),
    )
    assert resp.status_code == 422


def test_hotel_checkout_before_checkin_is_rejected(client, db_session):
    _, _, business_id, service_id, space_id = _setup_approved_hotel(client, db_session)
    cust_token = register_customer(client)

    check_in = datetime.now(timezone.utc) + timedelta(days=5)
    check_out = check_in - timedelta(hours=1)

    resp = _book_hotel(client, cust_token, business_id, service_id, space_id, check_in.isoformat(), check_out.isoformat())
    assert resp.status_code == 400


def test_end_datetime_rejected_for_non_hotel_business(client, db_session):
    biz_token = register_business(client, "salon@example.com", category="Salon")
    make_admin(db_session)
    admin_token = login_admin(client)
    business_id = client.get("/api/v1/admin/businesses", headers=auth_headers(admin_token)).json()["items"][0]["id"]
    approve_business(client, admin_token, business_id)
    service_id = client.post(
        "/api/v1/businesses/me/services",
        json={"name": "Haircut", "duration_minutes": 30, "price": 25},
        headers=auth_headers(biz_token),
    ).json()["id"]
    cust_token = register_customer(client)

    start = datetime.now(timezone.utc) + timedelta(days=1)
    resp = client.post(
        "/api/v1/appointments",
        json={
            "business_id": business_id,
            "service_id": service_id,
            "start_datetime": start.isoformat(),
            "end_datetime": (start + timedelta(hours=1)).isoformat(),
            "general_service_details": {"service_specifics": {"note": "trim"}},
        },
        headers=auth_headers(cust_token),
    )
    assert resp.status_code == 400


def test_overlapping_multi_night_stays_respect_room_capacity(client, db_session):
    _, _, business_id, service_id, space_id = _setup_approved_hotel(client, db_session, total_rooms=1)
    cust_token = register_customer(client)

    check_in = datetime.now(timezone.utc) + timedelta(days=5)
    first = _book_hotel(
        client, cust_token, business_id, service_id, space_id,
        check_in.isoformat(), (check_in + timedelta(days=4)).isoformat(),
    )
    assert first.status_code == 201

    # Overlaps nights 2-3 of the first stay - only 1 room total, so this must fail.
    overlapping = _book_hotel(
        client, cust_token, business_id, service_id, space_id,
        (check_in + timedelta(days=2)).isoformat(), (check_in + timedelta(days=3)).isoformat(),
    )
    assert overlapping.status_code == 409

    # Starts exactly when the first stay ends - no overlap, must succeed.
    back_to_back = _book_hotel(
        client, cust_token, business_id, service_id, space_id,
        (check_in + timedelta(days=4)).isoformat(), (check_in + timedelta(days=5)).isoformat(),
    )
    assert back_to_back.status_code == 201


def test_one_room_too_small_for_the_party_is_rejected(client, db_session):
    """A single room sleeping 2 can't be booked for 11 guests - no room type is ever filtered out for
    this on its own; the combined capacity of however many rooms are booked is what has to hold."""
    _, _, business_id, service_id, space_id = _setup_approved_hotel(client, db_session, total_rooms=5, capacity_per_unit=2)
    cust_token = register_customer(client)
    check_in = datetime.now(timezone.utc) + timedelta(days=5)
    check_out = check_in + timedelta(days=1)

    resp = _book_hotel(
        client, cust_token, business_id, service_id, space_id,
        check_in.isoformat(), check_out.isoformat(), no_of_rooms=1, no_of_guests=11,
    )
    assert resp.status_code == 400
    assert "11 guests" in resp.json()["detail"]


def test_enough_rooms_of_the_same_type_cover_a_large_party(client, db_session):
    """3 rooms sleeping 4 each (12 total) is enough for 11 guests, even though no single room is."""
    _, _, business_id, service_id, space_id = _setup_approved_hotel(client, db_session, total_rooms=5, capacity_per_unit=4)
    cust_token = register_customer(client)
    check_in = datetime.now(timezone.utc) + timedelta(days=5)
    check_out = check_in + timedelta(days=1)

    resp = _book_hotel(
        client, cust_token, business_id, service_id, space_id,
        check_in.isoformat(), check_out.isoformat(), no_of_rooms=3, no_of_guests=11,
    )
    assert resp.status_code == 201, resp.text


def test_combining_different_room_types_in_one_booking(client, db_session):
    """A party of 11 can be split across 2 Deluxe Rooms (cap 2 each) + 1 Suite (cap 4) - see
    HotelRoomItem, which lets a single stay hold more than one room type at once."""
    biz_token, _, business_id, service_id, deluxe_id = _setup_approved_hotel(
        client, db_session, total_rooms=5, price=100, capacity_per_unit=2
    )
    suite_resp = client.post(
        "/api/v1/businesses/me/inventory",
        json={"inventory_type": "Hotel Room", "category_name": "Suite", "total_quantity": 2, "price": 350, "capacity_per_unit": 4},
        headers=auth_headers(biz_token),
    )
    suite_id = suite_resp.json()["id"]
    cust_token = register_customer(client)

    check_in = datetime.now(timezone.utc) + timedelta(days=5)
    check_out = check_in + timedelta(days=2)

    resp = _book_hotel_rooms(
        client, cust_token, business_id, service_id,
        [
            {"space_inventory_id": deluxe_id, "quantity": 2},
            {"space_inventory_id": suite_id, "quantity": 1},
        ],
        # 2 Deluxe (cap 2 each) + 1 Suite (cap 4) = 8 total, enough for 8 guests.
        check_in.isoformat(), check_out.isoformat(), no_of_guests=8,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["nights"] == 2
    # (100 * 2 rooms + 350 * 1 room) * 2 nights
    assert body["total_price"] == (100 * 2 + 350 * 1) * 2
    room_items = {item["space_inventory"]["id"]: item["quantity"] for item in body["room_items"]}
    assert room_items == {deluxe_id: 2, suite_id: 1}
    details = body["details"]
    assert details["no_of_rooms"] == 3
    assert "Deluxe Room" in details["room_type"] and "Suite" in details["room_type"]


def test_combined_room_types_still_enforce_capacity(client, db_session):
    """2 Deluxe Rooms (cap 2 each = 4 total) is not enough for 11 guests, even combined with nothing else."""
    biz_token, _, business_id, service_id, deluxe_id = _setup_approved_hotel(
        client, db_session, total_rooms=5, price=100, capacity_per_unit=2
    )
    cust_token = register_customer(client)
    check_in = datetime.now(timezone.utc) + timedelta(days=5)
    check_out = check_in + timedelta(days=1)

    resp = _book_hotel_rooms(
        client, cust_token, business_id, service_id,
        [{"space_inventory_id": deluxe_id, "quantity": 2}],
        check_in.isoformat(), check_out.isoformat(), no_of_guests=11,
    )
    assert resp.status_code == 400
    assert "11 guests" in resp.json()["detail"]


def test_duplicate_room_type_in_selections_is_rejected(client, db_session):
    _, _, business_id, service_id, space_id = _setup_approved_hotel(client, db_session, total_rooms=5)
    cust_token = register_customer(client)
    check_in = datetime.now(timezone.utc) + timedelta(days=5)
    check_out = check_in + timedelta(days=1)

    resp = _book_hotel_rooms(
        client, cust_token, business_id, service_id,
        [
            {"space_inventory_id": space_id, "quantity": 1},
            {"space_inventory_id": space_id, "quantity": 2},
        ],
        check_in.isoformat(), check_out.isoformat(),
    )
    assert resp.status_code == 400


def test_capacity_check_skipped_when_room_type_has_no_declared_capacity(client, db_session):
    """capacity_per_unit is optional - a business that never set one imposes no guest-count limit."""
    _, _, business_id, service_id, space_id = _setup_approved_hotel(client, db_session, total_rooms=5)
    cust_token = register_customer(client)
    check_in = datetime.now(timezone.utc) + timedelta(days=5)
    check_out = check_in + timedelta(days=1)

    resp = _book_hotel(
        client, cust_token, business_id, service_id, space_id,
        check_in.isoformat(), check_out.isoformat(), no_of_rooms=1, no_of_guests=50,
    )
    assert resp.status_code == 201, resp.text
