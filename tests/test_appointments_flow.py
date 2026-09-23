"""End-to-end API tests for the booking workflow and state machine (PART 2, PART 5)."""
from tests.conftest import (
    approve_business,
    auth_headers,
    future_iso,
    login_admin,
    make_admin,
    register_business,
    register_customer,
)


def _setup_approved_salon(client, db_session):
    """Registers+approves a Salon business with one service and one staff member. Returns (biz_token, admin_token)."""
    biz_token = register_business(client, "salon@example.com")
    make_admin(db_session)
    admin_token = login_admin(client)
    resp = client.get("/api/v1/admin/businesses", headers=auth_headers(admin_token))
    business_id = resp.json()["items"][0]["id"]
    approve_business(client, admin_token, business_id)

    client.post(
        "/api/v1/businesses/me/services",
        json={"name": "Haircut", "duration_minutes": 30, "price": 25},
        headers=auth_headers(biz_token),
    )
    client.post("/api/v1/businesses/me/staff", json={"name": "Sarah Lee"}, headers=auth_headers(biz_token))
    return biz_token, admin_token, business_id


def _book(client, cust_token, business_id=1, service_id=1, start=None):
    return client.post(
        "/api/v1/appointments",
        json={
            "business_id": business_id,
            "service_id": service_id,
            "start_datetime": start or future_iso(),
            "general_service_details": {"service_specifics": {"note": "trim"}},
        },
        headers=auth_headers(cust_token),
    )


def test_full_booking_accept_flow(client, db_session):
    biz_token, _, business_id = _setup_approved_salon(client, db_session)
    cust_token = register_customer(client)

    resp = _book(client, cust_token, business_id=business_id)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "Pending"
    assert body["appointment_type"] == "Salon"
    appt_id = body["id"]

    # Business sees it in the action-required queue.
    queue = client.get("/api/v1/appointments/business?status=Pending", headers=auth_headers(biz_token))
    assert len(queue.json()) == 1

    accept = client.patch(
        f"/api/v1/appointments/{appt_id}/status", json={"status": "Confirmed"}, headers=auth_headers(biz_token)
    )
    assert accept.status_code == 200
    assert accept.json()["status"] == "Confirmed"

    # Customer sees it Confirmed too.
    mine = client.get("/api/v1/appointments/me", headers=auth_headers(cust_token))
    assert mine.json()[0]["status"] == "Confirmed"


def test_double_booking_beyond_staff_capacity_returns_409(client, db_session):
    _, _, business_id = _setup_approved_salon(client, db_session)
    cust_token = register_customer(client)
    slot = future_iso()

    first = _book(client, cust_token, business_id=business_id, start=slot)
    assert first.status_code == 201

    second = _book(client, cust_token, business_id=business_id, start=slot)
    assert second.status_code == 409


def test_confirmed_appointment_is_locked_against_further_business_changes(client, db_session):
    biz_token, _, business_id = _setup_approved_salon(client, db_session)
    cust_token = register_customer(client)
    appt_id = _book(client, cust_token, business_id=business_id).json()["id"]

    client.patch(f"/api/v1/appointments/{appt_id}/status", json={"status": "Confirmed"}, headers=auth_headers(biz_token))

    relock = client.patch(
        f"/api/v1/appointments/{appt_id}/status", json={"status": "Cancelled"}, headers=auth_headers(biz_token)
    )
    assert relock.status_code == 409


def test_customer_cannot_cancel_a_confirmed_appointment(client, db_session):
    biz_token, _, business_id = _setup_approved_salon(client, db_session)
    cust_token = register_customer(client)
    appt_id = _book(client, cust_token, business_id=business_id).json()["id"]

    client.patch(f"/api/v1/appointments/{appt_id}/status", json={"status": "Confirmed"}, headers=auth_headers(biz_token))

    resp = client.delete(f"/api/v1/appointments/{appt_id}", headers=auth_headers(cust_token))
    assert resp.status_code == 409


def test_customer_can_cancel_own_pending_appointment(client, db_session):
    _, _, business_id = _setup_approved_salon(client, db_session)
    cust_token = register_customer(client)
    appt_id = _book(client, cust_token, business_id=business_id).json()["id"]

    resp = client.delete(f"/api/v1/appointments/{appt_id}", headers=auth_headers(cust_token))
    assert resp.status_code == 200
    assert resp.json()["status"] == "Cancelled"


def test_admin_force_cancel_bypasses_lock(client, db_session):
    biz_token, admin_token, business_id = _setup_approved_salon(client, db_session)
    cust_token = register_customer(client)
    appt_id = _book(client, cust_token, business_id=business_id).json()["id"]
    client.patch(f"/api/v1/appointments/{appt_id}/status", json={"status": "Confirmed"}, headers=auth_headers(biz_token))

    resp = client.post(
        f"/api/v1/admin/appointments/{appt_id}/force-cancel",
        json={"reason": "Fraudulent booking"},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "Cancelled"

    audit = client.get("/api/v1/admin/audit-log", headers=auth_headers(admin_token))
    assert audit.json()["total"] >= 1
    assert any(entry["action_type"] == "FORCE_CANCEL_APPT" for entry in audit.json()["items"])


def test_another_customer_cannot_view_someone_elses_appointment(client, db_session):
    _, _, business_id = _setup_approved_salon(client, db_session)
    cust_token = register_customer(client, "jane@example.com")
    appt_id = _book(client, cust_token, business_id=business_id).json()["id"]

    other_token = register_customer(client, "other@example.com")
    resp = client.get(f"/api/v1/appointments/{appt_id}", headers=auth_headers(other_token))
    assert resp.status_code == 403


def test_admin_dashboard_metrics_reflect_bookings(client, db_session):
    biz_token, admin_token, business_id = _setup_approved_salon(client, db_session)
    cust_token = register_customer(client)
    appt_id = _book(client, cust_token, business_id=business_id).json()["id"]
    client.patch(f"/api/v1/appointments/{appt_id}/status", json={"status": "Confirmed"}, headers=auth_headers(biz_token))

    resp = client.get("/api/v1/admin/dashboard", headers=auth_headers(admin_token))
    data = resp.json()
    assert data["total_customers"] == 1
    assert data["active_customers"] == 1
    assert data["total_businesses"] == 1
    assert data["active_businesses"] == 1
