"""
Reviews are the real source behind Business.average_rating/rating_count
(see app.services.reviews) - a customer can only review an appointment
they actually completed, and only once.
"""
from app.enums import AppointmentStatus
from app.models.appointment import Appointment
from tests.conftest import approve_business, auth_headers, future_iso, login_admin, make_admin, register_business, register_customer


def _setup_approved_salon(client, db_session):
    biz_token = register_business(client, "salon@example.com")
    make_admin(db_session)
    admin_token = login_admin(client)
    business_id = client.get("/api/v1/admin/businesses", headers=auth_headers(admin_token)).json()["items"][0]["id"]
    approve_business(client, admin_token, business_id)
    service_id = client.post(
        "/api/v1/businesses/me/services",
        json={"name": "Haircut", "duration_minutes": 30, "price": 25},
        headers=auth_headers(biz_token),
    ).json()["id"]
    client.post("/api/v1/businesses/me/staff", json={"name": "Sarah Lee"}, headers=auth_headers(biz_token))
    return biz_token, business_id, service_id


def _book(client, cust_token, business_id, service_id):
    resp = client.post(
        "/api/v1/appointments",
        json={
            "business_id": business_id,
            "service_id": service_id,
            "start_datetime": future_iso(),
            "general_service_details": {"service_specifics": {"note": "trim"}},
        },
        headers=auth_headers(cust_token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _force_completed(db_session, appointment_id: int) -> None:
    """Test-only shortcut: real Completion requires the scheduled end time to
    have passed (see app.services.state_machine.mark_completed), which a
    freshly booked future appointment never satisfies - that timing rule has
    nothing to do with what's under test here."""
    appt = db_session.query(Appointment).filter(Appointment.id == appointment_id).one()
    appt.status = AppointmentStatus.COMPLETED
    db_session.commit()


def test_cannot_review_before_completed(client, db_session):
    _, business_id, service_id = _setup_approved_salon(client, db_session)
    cust_token = register_customer(client)
    appt_id = _book(client, cust_token, business_id, service_id)

    resp = client.post(
        f"/api/v1/appointments/{appt_id}/review", json={"rating": 5}, headers=auth_headers(cust_token)
    )
    assert resp.status_code == 400


def test_can_review_completed_appointment_and_business_rating_updates(client, db_session):
    _, business_id, service_id = _setup_approved_salon(client, db_session)
    cust_token = register_customer(client)
    appt_id = _book(client, cust_token, business_id, service_id)
    _force_completed(db_session, appt_id)

    resp = client.post(
        f"/api/v1/appointments/{appt_id}/review",
        json={"rating": 5, "comment": "Loved it!"},
        headers=auth_headers(cust_token),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["rating"] == 5
    assert body["comment"] == "Loved it!"
    assert body["reviewer_name"] == "Jane D."

    business = client.get(f"/api/v1/businesses/{business_id}").json()
    assert business["average_rating"] == 5.0
    assert business["rating_count"] == 1

    # The appointment now carries the review, for the frontend to know it's already reviewed.
    appt = client.get(f"/api/v1/appointments/{appt_id}", headers=auth_headers(cust_token)).json()
    assert appt["review"]["rating"] == 5


def test_cannot_review_the_same_appointment_twice(client, db_session):
    _, business_id, service_id = _setup_approved_salon(client, db_session)
    cust_token = register_customer(client)
    appt_id = _book(client, cust_token, business_id, service_id)
    _force_completed(db_session, appt_id)

    first = client.post(f"/api/v1/appointments/{appt_id}/review", json={"rating": 4}, headers=auth_headers(cust_token))
    assert first.status_code == 201

    second = client.post(f"/api/v1/appointments/{appt_id}/review", json={"rating": 2}, headers=auth_headers(cust_token))
    assert second.status_code == 409


def test_cannot_review_someone_elses_appointment(client, db_session):
    _, business_id, service_id = _setup_approved_salon(client, db_session)
    owner_token = register_customer(client, email="owner@example.com")
    appt_id = _book(client, owner_token, business_id, service_id)
    _force_completed(db_session, appt_id)

    other_token = register_customer(client, email="other@example.com")
    resp = client.post(f"/api/v1/appointments/{appt_id}/review", json={"rating": 5}, headers=auth_headers(other_token))
    assert resp.status_code == 404


def test_rating_out_of_range_is_rejected(client, db_session):
    _, business_id, service_id = _setup_approved_salon(client, db_session)
    cust_token = register_customer(client)
    appt_id = _book(client, cust_token, business_id, service_id)
    _force_completed(db_session, appt_id)

    resp = client.post(f"/api/v1/appointments/{appt_id}/review", json={"rating": 6}, headers=auth_headers(cust_token))
    assert resp.status_code == 422


def test_average_rating_is_the_mean_of_all_reviews(client, db_session):
    _, business_id, service_id = _setup_approved_salon(client, db_session)

    jane_token = register_customer(client, email="jane2@example.com")
    jane_appt = _book(client, jane_token, business_id, service_id)
    _force_completed(db_session, jane_appt)
    client.post(f"/api/v1/appointments/{jane_appt}/review", json={"rating": 5}, headers=auth_headers(jane_token))

    john_token = register_customer(client, email="john2@example.com")
    john_appt = _book(client, john_token, business_id, service_id)
    _force_completed(db_session, john_appt)
    client.post(f"/api/v1/appointments/{john_appt}/review", json={"rating": 3}, headers=auth_headers(john_token))

    business = client.get(f"/api/v1/businesses/{business_id}").json()
    assert business["average_rating"] == 4.0
    assert business["rating_count"] == 2


def test_public_reviews_listing_masks_reviewer_identity(client, db_session):
    _, business_id, service_id = _setup_approved_salon(client, db_session)
    cust_token = register_customer(client)
    appt_id = _book(client, cust_token, business_id, service_id)
    _force_completed(db_session, appt_id)
    client.post(
        f"/api/v1/appointments/{appt_id}/review", json={"rating": 5, "comment": "Great!"}, headers=auth_headers(cust_token)
    )

    resp = client.get(f"/api/v1/businesses/{business_id}/reviews")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    review = body["items"][0]
    assert review["reviewer_name"] == "Jane D."
    assert review["rating"] == 5
    assert review["comment"] == "Great!"
    assert "email" not in review
