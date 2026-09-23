"""
THE BOOKING WORKFLOW, availability checks, and the appointment lifecycle
(PART 2, PART 4.4, PART 5.3-5.4).
"""
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.dependencies import get_current_active_business, get_current_customer, get_token_payload
from app.enums import (
    AppointmentStatus,
    AppointmentType,
    SPACE_BASED_CATEGORIES,
    STAFF_BASED_CATEGORIES,
)
from app.models.appointment import Appointment
from app.models.business import Business
from app.models.details import CarServiceDetails, GeneralServiceDetails, HotelDetails, HotelRoomItem, RestaurantDetails
from app.models.resource import Service, SpaceInventory, Staff
from app.models.user import User
from app.schemas.appointment import AppointmentCreate, AppointmentOut, AppointmentStatusUpdate
from app.security import Role
from app.services import google_calendar, state_machine
from app.services.availability import (
    AvailabilityConflictError,
    calculate_end_datetime,
    check_space_availability,
    check_staff_availability,
    resolve_appointment_type,
)
from app.services.currency import currency_for_phone_number
from app.services.state_machine import InvalidTransitionError

router = APIRouter(prefix="/appointments", tags=["appointments"])

_EAGER_LOAD = (
    joinedload(Appointment.business),
    joinedload(Appointment.service),
    joinedload(Appointment.staff),
    joinedload(Appointment.space_inventory),
    joinedload(Appointment.user),
    joinedload(Appointment.restaurant_details),
    joinedload(Appointment.hotel_details),
    joinedload(Appointment.car_service_details),
    joinedload(Appointment.general_service_details),
    joinedload(Appointment.room_items).joinedload(HotelRoomItem.space_inventory),
)


def _query_with_relations(db: Session):
    return db.query(Appointment).options(*_EAGER_LOAD)


# ---------------------------------------------------------------------------
# Create (PART 2.1 booking workflow, steps 4-7)
# ---------------------------------------------------------------------------
@router.post("", response_model=AppointmentOut, status_code=status.HTTP_201_CREATED)
def create_appointment(
    payload: AppointmentCreate,
    current_user: User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    # Step 3: only an Approved business's resources can ever be booked.
    business = db.get(Business, payload.business_id)
    if business is None or not business.is_approved:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Business not found.")

    service = (
        db.query(Service)
        .filter(Service.id == payload.service_id, Service.business_id == business.id, Service.is_active.is_(True))
        .first()
    )
    if service is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Service not found for this business.")

    appointment_type = resolve_appointment_type(business.category)

    # Every appointment is anchored to a real instant in time, not a naive
    # "wall clock" reading - a naive datetime is ambiguous the moment the
    # customer and business are in different timezones (which of their
    # clocks does "2:00 PM" mean?). Rather than silently guessing UTC (the
    # previous behavior here, which could silently mis-book a slot by whole
    # hours), require the client to send a timezone-aware datetime. The
    # frontend computes this correctly from the business's own
    # Business.timezone before ever sending the request - see
    # frontend/src/pages/customer/BookingPage.tsx.
    if payload.start_datetime.tzinfo is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "start_datetime must include a UTC offset (e.g. '2030-06-15T14:00:00+08:00') - "
            "a timezone-naive datetime is ambiguous and cannot be safely booked.",
        )
    start_datetime = payload.start_datetime
    if start_datetime <= datetime.now(timezone.utc):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Appointments must be booked for a future date and time.")

    # Hotel stays span a customer-chosen number of nights (check-in to
    # check-out), not one fixed-duration slot - every other business type
    # keeps booking a single slot sized by Service.duration_minutes.
    if appointment_type == AppointmentType.HOTEL:
        if payload.end_datetime is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "end_datetime (check-out) is required for hotel bookings."
            )
        if payload.end_datetime.tzinfo is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "end_datetime must include a UTC offset, for the same reason as start_datetime.",
            )
        end_datetime = payload.end_datetime
        if end_datetime <= start_datetime:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Check-out must be after check-in.")
    else:
        if payload.end_datetime is not None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "end_datetime is only accepted for hotel bookings."
            )
        end_datetime = calculate_end_datetime(start_datetime, service.duration_minutes)

    staff: Optional[Staff] = None
    space_inventory: Optional[SpaceInventory] = None
    # Hotel only - one or more (SpaceInventory, quantity) pairs making up the
    # stay (see app.models.details.HotelRoomItem); every other space-based
    # type still books exactly one `space_inventory` above.
    room_selections: list[tuple[SpaceInventory, int]] = []

    # --- Resource selection + availability check, dispatched by industry ---
    if appointment_type in STAFF_BASED_CATEGORIES:
        if payload.space_inventory_id is not None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "This business type is not booked against inventory.")
        if payload.staff_id is not None:
            staff = (
                db.query(Staff)
                .filter(Staff.id == payload.staff_id, Staff.business_id == business.id, Staff.is_active.is_(True))
                .first()
            )
            if staff is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Requested staff member not found.")
        try:
            check_staff_availability(
                db,
                business_id=business.id,
                staff_id=payload.staff_id,
                start_datetime=start_datetime,
                end_datetime=end_datetime,
            )
        except AvailabilityConflictError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    elif appointment_type == AppointmentType.HOTEL:
        # A stay can combine several room types at once (e.g. a party of 11
        # as 2 Deluxe Rooms + 1 Suite) - room_selections carries the whole
        # list, not just one space_inventory_id + a room count.
        if payload.staff_id is not None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "This business type is not booked against staff.")
        if payload.space_inventory_id is not None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "Hotel bookings use room_selections, not space_inventory_id."
            )
        if not payload.room_selections:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "room_selections is required for hotel bookings.")

        seen_space_inventory_ids: set[int] = set()
        for selection in payload.room_selections:
            if selection.space_inventory_id in seen_space_inventory_ids:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    "Each room type may only appear once in room_selections - combine quantities instead.",
                )
            seen_space_inventory_ids.add(selection.space_inventory_id)

            item = (
                db.query(SpaceInventory)
                .filter(
                    SpaceInventory.id == selection.space_inventory_id,
                    SpaceInventory.business_id == business.id,
                    SpaceInventory.is_active.is_(True),
                )
                .first()
            )
            if item is None:
                raise HTTPException(
                    status.HTTP_404_NOT_FOUND, f"Requested inventory category {selection.space_inventory_id} not found."
                )
            try:
                check_space_availability(
                    db,
                    space_inventory=item,
                    start_datetime=start_datetime,
                    end_datetime=end_datetime,
                    quantity=selection.quantity,
                )
            except AvailabilityConflictError as exc:
                raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
            room_selections.append((item, selection.quantity))

    elif appointment_type in SPACE_BASED_CATEGORIES:
        if payload.staff_id is not None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "This business type is not booked against staff.")
        if payload.space_inventory_id is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "space_inventory_id is required for this business type.")
        space_inventory = (
            db.query(SpaceInventory)
            .filter(
                SpaceInventory.id == payload.space_inventory_id,
                SpaceInventory.business_id == business.id,
                SpaceInventory.is_active.is_(True),
            )
            .first()
        )
        if space_inventory is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Requested inventory category not found.")
        try:
            check_space_availability(
                db, space_inventory=space_inventory, start_datetime=start_datetime, end_datetime=end_datetime
            )
        except AvailabilityConflictError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    # --- Industry-specific details: exactly one, matching appointment_type ---
    detail_payloads = {
        AppointmentType.RESTAURANT: payload.restaurant_details,
        AppointmentType.HOTEL: payload.hotel_details,
        AppointmentType.CAR: payload.car_service_details,
        AppointmentType.SALON: payload.general_service_details,
        AppointmentType.SPA: payload.general_service_details,
        AppointmentType.PROFESSIONAL: payload.general_service_details,
    }
    required_detail = detail_payloads[appointment_type]
    if required_detail is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Missing required booking details for a {appointment_type.value} appointment.",
        )
    if appointment_type == AppointmentType.HOTEL:
        # A single room's capacity no longer has to fit every guest on its
        # own - a party of 11 can take 3 rooms that sleep 4 each, possibly
        # of different types. What has to hold is the COMBINED capacity
        # across every room selection. If any selected type never declared
        # a capacity, its true capacity is unknown, so the whole check is
        # skipped rather than under-counting it as 0.
        capacities = [item.capacity_per_unit for item, _ in room_selections]
        if all(c is not None for c in capacities):
            total_capacity = sum(item.capacity_per_unit * qty for item, qty in room_selections)
            if total_capacity < required_detail.no_of_guests:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    f"These rooms sleep {total_capacity} in total, which isn't enough for "
                    f"{required_detail.no_of_guests} guests - add more rooms.",
                )
    if appointment_type in (AppointmentType.SALON, AppointmentType.SPA, AppointmentType.PROFESSIONAL):
        if required_detail.staff_requested_id is not None:
            requested_staff = (
                db.query(Staff)
                .filter(
                    Staff.id == required_detail.staff_requested_id,
                    Staff.business_id == business.id,
                    Staff.is_active.is_(True),
                )
                .first()
            )
            if requested_staff is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Requested staff member not found.")

    appointment = Appointment(
        user_id=current_user.id,
        business_id=business.id,
        service_id=service.id,
        staff_id=staff.id if staff else None,
        # Hotel: the first room selection, just so this column (used by every
        # other type as THE booked space) isn't left null - the full
        # breakdown lives in room_items, added below.
        space_inventory_id=(
            room_selections[0][0].id if room_selections else (space_inventory.id if space_inventory else None)
        ),
        appointment_type=appointment_type,
        start_datetime=start_datetime,
        end_datetime=end_datetime,
        status=AppointmentStatus.PENDING,
    )
    db.add(appointment)
    db.flush()  # assigns appointment.id for the 1-to-1 detail row

    if appointment_type == AppointmentType.RESTAURANT:
        db.add(RestaurantDetails(appointment_id=appointment.id, **payload.restaurant_details.model_dump()))
    elif appointment_type == AppointmentType.HOTEL:
        # room_type/no_of_rooms are derived here from room_selections, never
        # trusted from the client (see HotelDetailsIn) - a party combining 2
        # Deluxe Rooms + 1 Suite gets room_type "Deluxe Room, Suite" and
        # no_of_rooms 3.
        hotel_fields = payload.hotel_details.model_dump()
        hotel_fields["room_type"] = ", ".join(item.category_name for item, _ in room_selections)
        hotel_fields["no_of_rooms"] = sum(qty for _, qty in room_selections)
        db.add(HotelDetails(appointment_id=appointment.id, **hotel_fields))
        for item, qty in room_selections:
            db.add(HotelRoomItem(appointment_id=appointment.id, space_inventory_id=item.id, quantity=qty))
    elif appointment_type == AppointmentType.CAR:
        db.add(CarServiceDetails(appointment_id=appointment.id, **payload.car_service_details.model_dump()))
    else:
        db.add(GeneralServiceDetails(appointment_id=appointment.id, **payload.general_service_details.model_dump()))

    db.commit()
    db.refresh(appointment)

    # Step 7: sync to Google Calendar (dual-sync; safe no-op if disabled/unset).
    sync_result = google_calendar.sync_appointment_created(appointment)
    if sync_result.customer_event_id or sync_result.business_event_id:
        appointment.google_calendar_event_id = sync_result.customer_event_id
        appointment.business_google_calendar_event_id = sync_result.business_event_id
        db.commit()

    appointment = _query_with_relations(db).filter(Appointment.id == appointment.id).one()
    return AppointmentOut.from_model(
        appointment, target_currency=currency_for_phone_number(current_user.phone_number)
    )


# ---------------------------------------------------------------------------
# Read - customer's own appointments (PART 4.4)
# ---------------------------------------------------------------------------
@router.get("/me", response_model=list[AppointmentOut])
def list_my_appointments(
    appointment_status: Optional[AppointmentStatus] = Query(None, alias="status"),
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    current_user: User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    query = _query_with_relations(db).filter(Appointment.user_id == current_user.id)
    if appointment_status is not None:
        query = query.filter(Appointment.status == appointment_status)
    if date_from is not None:
        query = query.filter(Appointment.start_datetime >= date_from)
    if date_to is not None:
        query = query.filter(Appointment.start_datetime <= date_to)
    appointments = query.order_by(Appointment.start_datetime.desc()).all()
    target_currency = currency_for_phone_number(current_user.phone_number)
    return [AppointmentOut.from_model(a, target_currency=target_currency) for a in appointments]


# ---------------------------------------------------------------------------
# Read - business's appointments (PART 5.2/5.3: "Action Required" and
# "Today's Appointments" widgets are just this endpoint with status/date
# filters composed by the frontend).
# ---------------------------------------------------------------------------
@router.get("/business", response_model=list[AppointmentOut])
def list_business_appointments(
    appointment_status: Optional[AppointmentStatus] = Query(None, alias="status"),
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    current_business: Business = Depends(get_current_active_business),
    db: Session = Depends(get_db),
):
    query = _query_with_relations(db).filter(Appointment.business_id == current_business.id)
    if appointment_status is not None:
        query = query.filter(Appointment.status == appointment_status)
    if date_from is not None:
        query = query.filter(Appointment.start_datetime >= date_from)
    if date_to is not None:
        query = query.filter(Appointment.start_datetime <= date_to)
    appointments = query.order_by(Appointment.start_datetime.asc()).all()
    return [AppointmentOut.from_model(a, include_user=True) for a in appointments]


# ---------------------------------------------------------------------------
# Read - single appointment detail, for whichever actor owns it (or admin)
# ---------------------------------------------------------------------------
@router.get("/{appointment_id}", response_model=AppointmentOut)
def get_appointment(
    appointment_id: int,
    payload=Depends(get_token_payload),
    db: Session = Depends(get_db),
):
    appointment = _query_with_relations(db).filter(Appointment.id == appointment_id).first()
    if appointment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Appointment not found.")

    allowed = (
        (payload.role == Role.CUSTOMER and appointment.user_id == payload.subject_id)
        or (payload.role == Role.BUSINESS and appointment.business_id == payload.subject_id)
        or (payload.role == Role.ADMIN)
    )
    if not allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not have access to this appointment.")

    target_currency = currency_for_phone_number(appointment.user.phone_number) if payload.role == Role.CUSTOMER else None
    return AppointmentOut.from_model(appointment, include_user=True, target_currency=target_currency)


# ---------------------------------------------------------------------------
# Business accepts/rejects a Pending appointment (PART 5.4, state machine)
# ---------------------------------------------------------------------------
@router.patch("/{appointment_id}/status", response_model=AppointmentOut)
def update_appointment_status(
    appointment_id: int,
    payload: AppointmentStatusUpdate,
    current_business: Business = Depends(get_current_active_business),
    db: Session = Depends(get_db),
):
    appointment = _query_with_relations(db).filter(Appointment.id == appointment_id).first()
    if appointment is None or appointment.business_id != current_business.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Appointment not found.")

    try:
        state_machine.apply_business_decision(appointment, new_status=payload.status, reason=payload.reason)
    except InvalidTransitionError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    db.commit()
    db.refresh(appointment)
    google_calendar.sync_appointment_updated(appointment)
    return AppointmentOut.from_model(appointment, include_user=True)


@router.post("/{appointment_id}/complete", response_model=AppointmentOut)
def complete_appointment(
    appointment_id: int,
    current_business: Business = Depends(get_current_active_business),
    db: Session = Depends(get_db),
):
    appointment = _query_with_relations(db).filter(Appointment.id == appointment_id).first()
    if appointment is None or appointment.business_id != current_business.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Appointment not found.")

    try:
        state_machine.mark_completed(appointment)
    except InvalidTransitionError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    db.commit()
    db.refresh(appointment)
    google_calendar.sync_appointment_updated(appointment)
    return AppointmentOut.from_model(appointment, include_user=True)


# ---------------------------------------------------------------------------
# Customer cancels their own still-Pending appointment
# ---------------------------------------------------------------------------
@router.delete("/{appointment_id}", response_model=AppointmentOut)
def cancel_my_appointment(
    appointment_id: int,
    current_user: User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    appointment = _query_with_relations(db).filter(Appointment.id == appointment_id).first()
    if appointment is None or appointment.user_id != current_user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Appointment not found.")

    try:
        state_machine.customer_cancel(appointment)
    except InvalidTransitionError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    db.commit()
    db.refresh(appointment)
    google_calendar.sync_appointment_updated(appointment)
    return AppointmentOut.from_model(appointment)
