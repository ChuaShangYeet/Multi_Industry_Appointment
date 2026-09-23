"""Unit tests for the availability engine (PART 2.2 / Backend Architecture #3)."""
from datetime import datetime, timedelta, timezone

import pytest

from app.enums import AppointmentStatus, AppointmentType, BusinessApprovalStatus, BusinessCategory, SpaceInventoryType
from app.models.appointment import Appointment
from app.models.business import Business
from app.models.resource import Service, SpaceInventory, Staff
from app.models.user import User
from app.security import hash_password
from app.services.availability import (
    AvailabilityConflictError,
    calculate_end_datetime,
    check_space_availability,
    check_staff_availability,
    resolve_appointment_type,
)


def _make_customer(db) -> User:
    user = User(email="jane@example.com", password_hash=hash_password("x"), first_name="Jane", last_name="Doe")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_business(db, category=BusinessCategory.SALON) -> Business:
    business = Business(
        email="biz@example.com",
        password_hash=hash_password("x"),
        business_name="Test Biz",
        category=category,
        approval_status=BusinessApprovalStatus.APPROVED,
    )
    db.add(business)
    db.commit()
    db.refresh(business)
    return business


def test_calculate_end_datetime():
    start = datetime(2030, 1, 1, 10, 0, tzinfo=timezone.utc)
    assert calculate_end_datetime(start, 45) == datetime(2030, 1, 1, 10, 45, tzinfo=timezone.utc)


def test_resolve_appointment_type_maps_every_category():
    assert resolve_appointment_type(BusinessCategory.RESTAURANT) == AppointmentType.RESTAURANT
    assert resolve_appointment_type(BusinessCategory.HOTEL) == AppointmentType.HOTEL
    assert resolve_appointment_type(BusinessCategory.CAR_SERVICE) == AppointmentType.CAR


def test_specific_staff_conflict_detected(db_session):
    user = _make_customer(db_session)
    business = _make_business(db_session)
    staff = Staff(business_id=business.id, name="Sarah")
    service = Service(business_id=business.id, name="Haircut", duration_minutes=30)
    db_session.add_all([staff, service])
    db_session.commit()

    start = datetime.now(timezone.utc) + timedelta(days=1)
    end = calculate_end_datetime(start, 30)
    existing = Appointment(
        user_id=user.id,
        business_id=business.id,
        service_id=service.id,
        staff_id=staff.id,
        appointment_type=AppointmentType.SALON,
        start_datetime=start,
        end_datetime=end,
        status=AppointmentStatus.CONFIRMED,
    )
    db_session.add(existing)
    db_session.commit()

    # Fully overlapping window with the same staff member -> conflict.
    with pytest.raises(AvailabilityConflictError):
        check_staff_availability(
            db_session,
            business_id=business.id,
            staff_id=staff.id,
            start_datetime=start,
            end_datetime=end,
        )

    # A non-overlapping window (starts exactly when the first ends) is fine.
    check_staff_availability(
        db_session,
        business_id=business.id,
        staff_id=staff.id,
        start_datetime=end,
        end_datetime=calculate_end_datetime(end, 30),
    )


def test_unassigned_staff_pool_exhausted(db_session):
    """With only 1 active staff member, a 2nd overlapping booking with no specific staff must be rejected."""
    user = _make_customer(db_session)
    business = _make_business(db_session)
    staff = Staff(business_id=business.id, name="Sarah", is_active=True)
    service = Service(business_id=business.id, name="Haircut", duration_minutes=30)
    db_session.add_all([staff, service])
    db_session.commit()

    start = datetime.now(timezone.utc) + timedelta(days=1)
    end = calculate_end_datetime(start, 30)

    # First booking with no specific staff succeeds and consumes the only slot.
    check_staff_availability(db_session, business_id=business.id, staff_id=None, start_datetime=start, end_datetime=end)
    db_session.add(
        Appointment(
            user_id=user.id,
            business_id=business.id,
            service_id=service.id,
            appointment_type=AppointmentType.SALON,
            start_datetime=start,
            end_datetime=end,
            status=AppointmentStatus.PENDING,
        )
    )
    db_session.commit()

    with pytest.raises(AvailabilityConflictError):
        check_staff_availability(
            db_session, business_id=business.id, staff_id=None, start_datetime=start, end_datetime=end
        )


def test_space_inventory_capacity_enforced(db_session):
    user = _make_customer(db_session)
    business = _make_business(db_session, category=BusinessCategory.RESTAURANT)
    service = Service(business_id=business.id, name="Table Booking", duration_minutes=90)
    table = SpaceInventory(
        business_id=business.id,
        inventory_type=SpaceInventoryType.RESTAURANT_TABLE,
        category_name="Window Table 4-Pax",
        total_quantity=2,
    )
    db_session.add_all([service, table])
    db_session.commit()

    start = datetime.now(timezone.utc) + timedelta(days=1)
    end = calculate_end_datetime(start, 90)

    for _ in range(2):
        check_space_availability(db_session, space_inventory=table, start_datetime=start, end_datetime=end)
        db_session.add(
            Appointment(
                user_id=user.id,
                business_id=business.id,
                service_id=service.id,
                space_inventory_id=table.id,
                appointment_type=AppointmentType.RESTAURANT,
                start_datetime=start,
                end_datetime=end,
                status=AppointmentStatus.CONFIRMED,
            )
        )
        db_session.commit()

    # The 3rd overlapping booking exceeds total_quantity=2.
    with pytest.raises(AvailabilityConflictError):
        check_space_availability(db_session, space_inventory=table, start_datetime=start, end_datetime=end)
