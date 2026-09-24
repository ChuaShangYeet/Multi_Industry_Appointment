"""
THE AVAILABILITY ENGINE (PART 2.2 / Backend Architecture #3).

Pure query/validation logic, no HTTP concerns - the appointments router
catches AvailabilityConflictError and turns it into a 409 response.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.enums import ACTIVE_APPOINTMENT_STATUSES, AppointmentType, SpaceInventoryType
from app.models.appointment import Appointment
from app.models.details import HotelRoomItem
from app.models.resource import SpaceInventory, Staff


class AvailabilityConflictError(Exception):
    """Raised when a requested slot can't be granted right now."""


def calculate_end_datetime(start_datetime: datetime, duration_minutes: int) -> datetime:
    """end_datetime = start_datetime + Service.duration_minutes, per PART 2.2."""
    return start_datetime + timedelta(minutes=duration_minutes)


def _overlaps(start_datetime: datetime, end_datetime: datetime):
    """Two time blocks [a_start, a_end) and [b_start, b_end) overlap iff a_start < b_end AND a_end > b_start."""
    return (Appointment.start_datetime < end_datetime) & (Appointment.end_datetime > start_datetime)


def check_staff_availability(
    db: Session,
    *,
    business_id: int,
    staff_id: Optional[int],
    start_datetime: datetime,
    end_datetime: datetime,
    exclude_appointment_id: Optional[int] = None,
) -> None:
    """
    - Specific staff requested: conflict if that staff member already has an
      overlapping Pending/Confirmed appointment.
    - No specific staff requested: conflict if total overlapping
      Pending/Confirmed appointments for the business already meet or
      exceed the count of its `is_active` staff (nobody would be free).
    """
    filters = [
        Appointment.business_id == business_id,
        Appointment.status.in_(ACTIVE_APPOINTMENT_STATUSES),
        _overlaps(start_datetime, end_datetime),
    ]
    if exclude_appointment_id is not None:
        filters.append(Appointment.id != exclude_appointment_id)

    if staff_id is not None:
        conflict = db.execute(select(Appointment.id).where(*filters, Appointment.staff_id == staff_id)).first()
        if conflict is not None:
            raise AvailabilityConflictError("The requested staff member is not available at that time.")
        return

    total_active_staff = (
        db.scalar(
            select(func.count()).select_from(Staff).where(Staff.business_id == business_id, Staff.is_active.is_(True))
        )
        or 0
    )
    if total_active_staff == 0:
        raise AvailabilityConflictError("This business currently has no active staff to fulfil the appointment.")

    overlapping_count = db.scalar(select(func.count()).select_from(Appointment).where(*filters)) or 0
    if overlapping_count >= total_active_staff:
        raise AvailabilityConflictError("No staff are available at the requested time.")


def count_occupied_units(
    db: Session,
    *,
    space_inventory: SpaceInventory,
    start_datetime: datetime,
    end_datetime: datetime,
    exclude_appointment_id: Optional[int] = None,
) -> int:
    """
    How many units of this category are currently held by Pending/Confirmed
    appointments overlapping the requested window - a Pending appointment
    already holds its units (see ACTIVE_APPOINTMENT_STATUSES), so capacity
    is reserved from the moment a customer requests it, not only once a
    business accepts it; that's what stops two customers both landing on
    the same room "Pending" beyond total_quantity in the first place.

    A Hotel Room category can be booked several at once as part of a single
    stay (see HotelRoomItem - a stay might combine 2 Deluxe Rooms + 1
    Suite), so occupancy there is the SUM of each overlapping appointment's
    requested quantity for this room type, not a count of appointments.
    Every other category (Restaurant tables) still books exactly one unit
    per appointment, so counting appointment rows is exact for them.
    """
    if space_inventory.inventory_type == SpaceInventoryType.HOTEL_ROOM:
        filters = [
            HotelRoomItem.space_inventory_id == space_inventory.id,
            Appointment.status.in_(ACTIVE_APPOINTMENT_STATUSES),
            _overlaps(start_datetime, end_datetime),
        ]
        if exclude_appointment_id is not None:
            filters.append(Appointment.id != exclude_appointment_id)
        query = (
            select(func.coalesce(func.sum(HotelRoomItem.quantity), 0))
            .select_from(HotelRoomItem)
            .join(Appointment, HotelRoomItem.appointment_id == Appointment.id)
            .where(*filters)
        )
        return db.scalar(query) or 0

    filters = [
        Appointment.space_inventory_id == space_inventory.id,
        Appointment.status.in_(ACTIVE_APPOINTMENT_STATUSES),
        _overlaps(start_datetime, end_datetime),
    ]
    if exclude_appointment_id is not None:
        filters.append(Appointment.id != exclude_appointment_id)

    return db.scalar(select(func.count()).select_from(Appointment).where(*filters)) or 0


def available_units(
    db: Session, *, space_inventory: SpaceInventory, start_datetime: datetime, end_datetime: datetime
) -> int:
    """How many units of this category are still free for the requested window - never negative."""
    occupied = count_occupied_units(
        db, space_inventory=space_inventory, start_datetime=start_datetime, end_datetime=end_datetime
    )
    return max(0, space_inventory.total_quantity - occupied)


def calculate_utilization_rate(
    db: Session, *, space_inventory: SpaceInventory, start_datetime: datetime, end_datetime: datetime
) -> float:
    """
    Fraction of this resource's capacity already occupied for the requested
    window, in [0.0, 1.0] - the "demand vs supply" input to
    calculate_dynamic_price below. Built on count_occupied_units (the same
    occupancy count check_space_availability uses), not a separate query,
    so utilization and the hard capacity check can never disagree about
    what "occupied" means.
    """
    if space_inventory.total_quantity <= 0:
        return 0.0
    occupied = count_occupied_units(
        db, space_inventory=space_inventory, start_datetime=start_datetime, end_datetime=end_datetime
    )
    return min(1.0, occupied / space_inventory.total_quantity)


# THE DYNAMIC PRICING ENGINE.
#
# Multipliers stack multiplicatively (not added) - e.g. a >80%-utilized
# Friday inside the 24h last-minute window is 1.20 x 1.15 x 1.10, not
# 1 + 0.20 + 0.15 + 0.10. This is the conventional way surge multipliers
# compose (airlines/Klook-style yield pricing) and avoids the discount and
# surge rules fighting each other in a flat sum.
_SURGE_HIGH_UTILIZATION = 0.80
_SURGE_HIGH_MULTIPLIER = 1.20
_DISCOUNT_LOW_UTILIZATION = 0.30
_DISCOUNT_LOW_MULTIPLIER = 0.90
_LAST_MINUTE_WINDOW = timedelta(hours=24)
_LAST_MINUTE_UTILIZATION_FLOOR = 0.50
_LAST_MINUTE_MULTIPLIER = 1.15
_WEEKEND_MULTIPLIER = 1.10
_WEEKEND_DAYS = {4, 5}  # datetime.weekday(): Monday=0 ... Friday=4, Saturday=5


def calculate_dynamic_price(
    base_price: float, utilization_rate: float, booking_date: datetime, request_time: datetime
) -> float:
    """
    Real-time price for one resource, given how full it already is and how
    soon the requested date is - base_price times whichever of these
    multipliers apply:

    - Capacity surge: utilization > 80% -> x1.20. utilization < 30% -> x0.90.
      (Between 30-80%, no capacity-driven adjustment.)
    - Last-minute premium: booking_date is within the next 24h of
      request_time AND utilization > 50% -> an additional x1.15. Only
      applies to a booking that is still in the future relative to
      request_time - a past booking_date (backfilled/historical data) never
      triggers "urgency".
    - Weekend/peak surge: booking_date falls on a Friday or Saturday ->
      an additional x1.10.

    booking_date/request_time must both be timezone-aware (this codebase
    never stores/accepts naive datetimes - see the appointments router).
    """
    if booking_date.tzinfo is None or request_time.tzinfo is None:
        raise ValueError("booking_date and request_time must both be timezone-aware.")

    multiplier = 1.0

    if utilization_rate > _SURGE_HIGH_UTILIZATION:
        multiplier *= _SURGE_HIGH_MULTIPLIER
    elif utilization_rate < _DISCOUNT_LOW_UTILIZATION:
        multiplier *= _DISCOUNT_LOW_MULTIPLIER

    time_until_booking = booking_date - request_time
    if timedelta(0) <= time_until_booking <= _LAST_MINUTE_WINDOW and utilization_rate > _LAST_MINUTE_UTILIZATION_FLOOR:
        multiplier *= _LAST_MINUTE_MULTIPLIER

    if booking_date.weekday() in _WEEKEND_DAYS:
        multiplier *= _WEEKEND_MULTIPLIER

    return round(base_price * multiplier, 2)


def calculate_resource_dynamic_price(
    db: Session,
    *,
    space_inventory: SpaceInventory,
    start_datetime: datetime,
    end_datetime: datetime,
    request_time: Optional[datetime] = None,
) -> Optional[float]:
    """
    Convenience wrapper tying the two functions above to one resource -
    what the resources router actually calls. None whenever there is
    nothing to compute a dynamic price from: the business never opted this
    resource into dynamic pricing, or it has no base price set.
    """
    if not space_inventory.is_dynamic_pricing_enabled or space_inventory.price is None:
        return None
    utilization_rate = calculate_utilization_rate(
        db, space_inventory=space_inventory, start_datetime=start_datetime, end_datetime=end_datetime
    )
    return calculate_dynamic_price(
        space_inventory.price, utilization_rate, start_datetime, request_time or datetime.now(timezone.utc)
    )


def check_space_availability(
    db: Session,
    *,
    space_inventory: SpaceInventory,
    start_datetime: datetime,
    end_datetime: datetime,
    quantity: int = 1,
    exclude_appointment_id: Optional[int] = None,
) -> None:
    """Only permits the booking if occupied + quantity <= total_quantity."""
    occupied = count_occupied_units(
        db,
        space_inventory=space_inventory,
        start_datetime=start_datetime,
        end_datetime=end_datetime,
        exclude_appointment_id=exclude_appointment_id,
    )
    if occupied + quantity > space_inventory.total_quantity:
        available = max(0, space_inventory.total_quantity - occupied)
        raise AvailabilityConflictError(
            f"Only {available} '{space_inventory.category_name}' unit(s) available at the requested time "
            f"(requested {quantity})."
        )


_CATEGORY_TO_APPOINTMENT_TYPE = {
    "Restaurant": AppointmentType.RESTAURANT,
    "Hotel": AppointmentType.HOTEL,
    "Spa": AppointmentType.SPA,
    "Car Service": AppointmentType.CAR,
    "Professional": AppointmentType.PROFESSIONAL,
    "Salon": AppointmentType.SALON,
}


def resolve_appointment_type(business_category) -> AppointmentType:
    """
    Maps Business.category -> Appointment.appointment_type. Derived
    server-side from the business being booked rather than trusted from the
    client request, so a booking can't claim a type that doesn't match its
    business.
    """
    key = business_category.value if hasattr(business_category, "value") else business_category
    return _CATEGORY_TO_APPOINTMENT_TYPE[key]
