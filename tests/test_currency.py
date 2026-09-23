"""
Currency conversion (app.services.currency) and the businesses that carry a
currency, plus the public services/inventory listings that convert into a
customer's target_currency on request.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.services.currency import convert_amount, currency_for_phone_number, get_exchange_rate
from tests.conftest import auth_headers, approve_business, login_admin, make_admin, register_business, register_customer
from tests.test_hotel_booking import _book_hotel, _setup_approved_hotel


def test_same_currency_is_a_no_op():
    assert get_exchange_rate("USD", "USD") == 1.0
    assert convert_amount(150, base="MYR", target="MYR") == 150


def test_currency_for_phone_number():
    assert currency_for_phone_number("+8613800138000") == "CNY"
    assert currency_for_phone_number("+60123456789") == "MYR"
    assert currency_for_phone_number(None) is None
    assert currency_for_phone_number("not-a-number") is None


def test_convert_amount_returns_none_when_amount_is_none():
    assert convert_amount(None, base="MYR", target="USD") is None


def test_get_exchange_rate_falls_back_to_none_on_network_failure():
    """The sandbox this runs in blocks arbitrary outbound hosts, which is exactly
    the failure mode a flaky/unreachable external API produces in production too -
    the function must degrade to None rather than raise."""
    assert get_exchange_rate("MYR", "USD") is None


@patch("app.services.currency.urllib.request.urlopen")
def test_get_exchange_rate_parses_and_caches(mock_urlopen):
    import json as _json

    class FakeResponse:
        def read(self):
            return _json.dumps({"amount": 1.0, "base": "MYR", "date": "2026-01-01", "rates": {"USD": 0.21}}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    mock_urlopen.return_value = FakeResponse()

    import app.services.currency as currency_module

    currency_module._RATE_CACHE.clear()
    rate1 = get_exchange_rate("MYR", "USD")
    rate2 = get_exchange_rate("MYR", "USD")
    assert rate1 == 0.21
    assert rate2 == 0.21
    mock_urlopen.assert_called_once()  # second call served from cache


def _setup_approved_business_with_service(client, db_session, currency: str = "MYR", price: float = 150):
    biz_token = register_business(client, "biz@example.com", category="Salon")
    make_admin(db_session)
    admin_token = login_admin(client)
    business_id = client.get("/api/v1/admin/businesses", headers=auth_headers(admin_token)).json()["items"][0]["id"]
    approve_business(client, admin_token, business_id)
    client.patch("/api/v1/businesses/me", json={"currency": currency}, headers=auth_headers(biz_token))
    service_id = client.post(
        "/api/v1/businesses/me/services",
        json={"name": "Haircut", "duration_minutes": 30, "price": price},
        headers=auth_headers(biz_token),
    ).json()["id"]
    return business_id, service_id


def test_business_registration_defaults_to_usd_and_validates_currency(client, db_session):
    resp = client.post(
        "/api/v1/auth/business/register",
        json={"email": "a@example.com", "password": "Password123!", "business_name": "A", "category": "Salon"},
    )
    token = resp.json()["access_token"]
    me = client.get("/api/v1/businesses/me", headers=auth_headers(token))
    assert me.json()["currency"] == "USD"

    bad = client.post(
        "/api/v1/auth/business/register",
        json={
            "email": "b@example.com", "password": "Password123!", "business_name": "B",
            "category": "Salon", "currency": "NOTREAL",
        },
    )
    assert bad.status_code == 422


def test_business_can_update_currency(client, db_session):
    business_id, _ = _setup_approved_business_with_service(client, db_session, currency="MYR")
    resp = client.get(f"/api/v1/businesses/{business_id}")
    assert resp.json()["currency"] == "MYR"


def test_public_services_target_currency_rejects_unknown_code(client, db_session):
    business_id, _ = _setup_approved_business_with_service(client, db_session)
    resp = client.get(f"/api/v1/businesses/{business_id}/services", params={"target_currency": "NOTREAL"})
    assert resp.status_code == 422


@patch("app.services.currency.get_exchange_rate", return_value=0.2)
def test_public_services_include_converted_price(mock_rate, client, db_session):
    business_id, service_id = _setup_approved_business_with_service(client, db_session, currency="MYR", price=150)

    resp = client.get(f"/api/v1/businesses/{business_id}/services", params={"target_currency": "USD"})
    assert resp.status_code == 200
    service = next(s for s in resp.json() if s["id"] == service_id)
    assert service["price"] == 150
    assert service["converted_price"] == 30.0  # 150 * 0.2

    # Without target_currency, no conversion is attempted at all.
    undated = client.get(f"/api/v1/businesses/{business_id}/services")
    assert undated.json()[0]["converted_price"] is None


@patch("app.services.currency.get_exchange_rate", return_value=None)
def test_public_services_degrade_to_null_converted_price_on_rate_failure(mock_rate, client, db_session):
    business_id, service_id = _setup_approved_business_with_service(client, db_session)
    resp = client.get(f"/api/v1/businesses/{business_id}/services", params={"target_currency": "USD"})
    service = next(s for s in resp.json() if s["id"] == service_id)
    assert service["price"] is not None
    assert service["converted_price"] is None


# ---------------------------------------------------------------------------
# Appointment views: a customer's currency (from their own phone number) is
# applied automatically, server-side - no query param needed, unlike the
# public/unauthenticated services & inventory listings above.
# ---------------------------------------------------------------------------
@patch("app.services.currency.get_exchange_rate", return_value=1.6)
def test_customer_appointment_views_show_business_currency_and_conversion(mock_rate, client, db_session):
    biz_token, _, business_id, service_id, space_id = _setup_approved_hotel(client, db_session, price=100)
    client.patch("/api/v1/businesses/me", json={"currency": "MYR"}, headers=auth_headers(biz_token))
    cust_token = register_customer(client, "wei@example.com", phone_number="+8613800138000")

    check_in = datetime.now(timezone.utc) + timedelta(days=5)
    check_out = check_in + timedelta(days=2)
    appt_id = _book_hotel(
        client, cust_token, business_id, service_id, space_id, check_in.isoformat(), check_out.isoformat()
    ).json()["id"]

    def _assert_converted(appt):
        assert appt["business"]["currency"] == "MYR"
        assert appt["space_inventory"]["price"] == 100
        assert appt["space_inventory"]["converted_price"] == 160.0  # 100 * 1.6
        assert appt["total_price"] == 200  # 100 * 2 nights
        assert appt["converted_total_price"] == 320.0  # 200 * 1.6

    mine = client.get("/api/v1/appointments/me", headers=auth_headers(cust_token)).json()
    _assert_converted(next(a for a in mine if a["id"] == appt_id))

    detail = client.get(f"/api/v1/appointments/{appt_id}", headers=auth_headers(cust_token)).json()
    _assert_converted(detail)


@patch("app.services.currency.get_exchange_rate", return_value=1.6)
def test_business_appointment_view_never_gets_converted_price(mock_rate, client, db_session):
    """A business sees its own bookings in its own currency - conversion is a customer-only concern."""
    biz_token, _, business_id, service_id, space_id = _setup_approved_hotel(client, db_session, price=100)
    client.patch("/api/v1/businesses/me", json={"currency": "MYR"}, headers=auth_headers(biz_token))
    cust_token = register_customer(client, "wei2@example.com", phone_number="+8613800138000")

    check_in = datetime.now(timezone.utc) + timedelta(days=5)
    check_out = check_in + timedelta(days=2)
    _book_hotel(client, cust_token, business_id, service_id, space_id, check_in.isoformat(), check_out.isoformat())

    resp = client.get("/api/v1/appointments/business", headers=auth_headers(biz_token))
    assert resp.json()[0]["converted_total_price"] is None
    assert resp.json()[0]["space_inventory"]["converted_price"] is None


def test_customer_with_matching_currency_gets_no_conversion(client, db_session):
    """A Malaysian customer booking a MYR business has nothing to convert."""
    biz_token, _, business_id, service_id, space_id = _setup_approved_hotel(client, db_session, price=100)
    client.patch("/api/v1/businesses/me", json={"currency": "MYR"}, headers=auth_headers(biz_token))
    cust_token = register_customer(client, "local@example.com", phone_number="+60123456789")

    check_in = datetime.now(timezone.utc) + timedelta(days=5)
    check_out = check_in + timedelta(days=1)
    _book_hotel(client, cust_token, business_id, service_id, space_id, check_in.isoformat(), check_out.isoformat())

    resp = client.get("/api/v1/appointments/me", headers=auth_headers(cust_token))
    # Same currency both sides - get_exchange_rate short-circuits to 1.0, so
    # converted_total_price still comes back equal to total_price (never null).
    assert resp.json()[0]["converted_total_price"] == resp.json()[0]["total_price"]
