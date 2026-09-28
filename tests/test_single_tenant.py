"""
Single-tenant deployment mode (Path 2: one dedicated backend instance per
client, fronted by e.g. a WordPress site - see
app.config.Settings.SINGLE_TENANT_MODE). Defaults to False so the rest of
the suite keeps exercising the normal multi-tenant marketplace unchanged;
every test here flips it on for just that one test via monkeypatch.
"""
from datetime import date, timedelta

from app.config import settings
from app.enums import BusinessApprovalStatus, BusinessCategory
from app.models.business import Business
from app.models.resource import Service, SpaceInventory, Staff
from app.security import hash_password
from tests.conftest import auth_headers, register_customer


def _make_tenant_business(db, category=BusinessCategory.SALON, **overrides) -> Business:
    """Mirrors what `python -m app.bootstrap_tenant` does - a single Approved
    Business row, created directly rather than via (disabled) self-registration."""
    business = Business(
        email=overrides.pop("email", "owner@example.com"),
        password_hash=hash_password("x"),
        business_name=overrides.pop("business_name", "My Business"),
        category=category,
        approval_status=BusinessApprovalStatus.APPROVED,
        timezone=overrides.pop("timezone", "Asia/Kuala_Lumpur"),
        currency=overrides.pop("currency", "MYR"),
        **overrides,
    )
    db.add(business)
    db.commit()
    db.refresh(business)
    return business


def test_single_tenant_endpoints_404_when_mode_is_off(client):
    resp = client.get("/api/v1/business/profile")
    assert resp.status_code == 404


def test_discovery_disabled_in_single_tenant_mode(client, monkeypatch):
    monkeypatch.setattr(settings, "SINGLE_TENANT_MODE", True)
    resp = client.get("/api/v1/businesses")
    assert resp.status_code == 404


def test_business_self_registration_disabled_in_single_tenant_mode(client, monkeypatch):
    monkeypatch.setattr(settings, "SINGLE_TENANT_MODE", True)
    resp = client.post(
        "/api/v1/auth/business/register",
        json={
            "email": "second@example.com",
            "password": "Password123!",
            "business_name": "Second Business",
            "category": "Salon",
            "city": "KL",
        },
    )
    assert resp.status_code == 404


def test_tenant_profile_resolves_without_a_business_id(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "SINGLE_TENANT_MODE", True)
    business = _make_tenant_business(db_session)

    resp = client.get("/api/v1/business/profile")
    assert resp.status_code == 200
    assert resp.json()["id"] == business.id
    assert resp.json()["business_name"] == "My Business"


def test_tenant_endpoints_503_when_not_provisioned(client, monkeypatch):
    monkeypatch.setattr(settings, "SINGLE_TENANT_MODE", True)
    resp = client.get("/api/v1/business/profile")
    assert resp.status_code == 503


def test_tenant_services_resolves_without_a_business_id(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "SINGLE_TENANT_MODE", True)
    business = _make_tenant_business(db_session)
    db_session.add(Service(business_id=business.id, name="Haircut", duration_minutes=30, price=25))
    db_session.commit()

    resp = client.get("/api/v1/business/services")
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["name"] == "Haircut"


def test_tenant_staff_resolves_without_a_business_id(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "SINGLE_TENANT_MODE", True)
    business = _make_tenant_business(db_session)
    db_session.add(Staff(business_id=business.id, name="Sarah Lee"))
    db_session.commit()

    resp = client.get("/api/v1/business/staff")
    assert resp.status_code == 200
    assert resp.json()[0]["name"] == "Sarah Lee"


def test_tenant_inventory_resolves_without_a_business_id(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "SINGLE_TENANT_MODE", True)
    business = _make_tenant_business(db_session, category=BusinessCategory.HOTEL, currency="SGD")
    db_session.add(
        SpaceInventory(
            business_id=business.id, inventory_type="Hotel Room", category_name="Deluxe Room",
            total_quantity=5, price=100,
        )
    )
    db_session.commit()

    resp = client.get("/api/v1/business/inventory")
    assert resp.status_code == 200
    assert resp.json()[0]["category_name"] == "Deluxe Room"


def test_tenant_slots_for_a_staff_based_business(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "SINGLE_TENANT_MODE", True)
    business = _make_tenant_business(db_session, category=BusinessCategory.SALON)
    business.operating_hours = {
        "monday": {"open": "09:00", "close": "18:00"}, "tuesday": {"open": "09:00", "close": "18:00"},
        "wednesday": {"open": "09:00", "close": "18:00"}, "thursday": {"open": "09:00", "close": "18:00"},
        "friday": {"open": "09:00", "close": "18:00"}, "saturday": None, "sunday": None,
    }
    service = Service(business_id=business.id, name="Haircut", duration_minutes=60, price=25)
    db_session.add(service)
    db_session.commit()
    db_session.refresh(service)

    # Find the next Monday so we always land on an open day.
    on_date = date.today() + timedelta(days=1)
    while on_date.weekday() != 0:
        on_date += timedelta(days=1)

    resp = client.get("/api/v1/business/slots", params={"service_id": service.id, "on_date": on_date.isoformat()})
    assert resp.status_code == 200
    slots = resp.json()
    assert len(slots) == 9  # 09:00-18:00 in 60-minute increments
    assert all(s["available"] is False for s in slots)  # no staff at all -> none bookable


def test_tenant_slots_rejected_for_a_space_based_business(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "SINGLE_TENANT_MODE", True)
    business = _make_tenant_business(db_session, category=BusinessCategory.RESTAURANT)
    service = Service(business_id=business.id, name="Table Booking", duration_minutes=90)
    db_session.add(service)
    db_session.commit()
    db_session.refresh(service)

    resp = client.get(
        "/api/v1/business/slots", params={"service_id": service.id, "on_date": date.today().isoformat()}
    )
    assert resp.status_code == 400


def test_end_to_end_booking_flow_still_works_in_single_tenant_mode(client, db_session, monkeypatch):
    """The convenience endpoints are additive - POST /appointments (still requiring business_id,
    which the WP frontend gets once from GET /business/profile) keeps working unchanged."""
    monkeypatch.setattr(settings, "SINGLE_TENANT_MODE", True)
    business = _make_tenant_business(db_session, category=BusinessCategory.SALON)
    staff = Staff(business_id=business.id, name="Sarah Lee")
    service = Service(business_id=business.id, name="Haircut", duration_minutes=30, price=25)
    db_session.add_all([staff, service])
    db_session.commit()
    db_session.refresh(service)

    business_id = client.get("/api/v1/business/profile").json()["id"]
    cust_token = register_customer(client)

    from tests.conftest import future_iso

    resp = client.post(
        "/api/v1/appointments",
        json={
            "business_id": business_id,
            "service_id": service.id,
            "start_datetime": future_iso(),
            "general_service_details": {"service_specifics": {"note": "trim"}},
        },
        headers=auth_headers(cust_token),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["business"]["currency"] == "MYR"
