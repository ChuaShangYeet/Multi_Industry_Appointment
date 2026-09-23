import math
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.enums import AppointmentStatus, AppointmentType, TablePreference
from app.schemas.review import ReviewOut
from app.services.currency import convert_amount

# ---------------------------------------------------------------------------
# Industry-specific detail payloads (1-to-1 with Appointment - PART 1.5).
# Exactly one of these is required on create, chosen for the customer by the
# business's category (see app.services.availability / the appointments
# router) - the client doesn't send `appointment_type` itself, to avoid a
# request claiming a type that doesn't match the business being booked.
# ---------------------------------------------------------------------------


class RestaurantDetailsIn(BaseModel):
    no_of_pax: int = Field(gt=0)
    table_preference: Optional[TablePreference] = None
    special_requests: Optional[str] = None


class HotelDetailsIn(BaseModel):
    # room_type/no_of_rooms are accepted here only so this class can also
    # shape the read side (see AppointmentOut.from_model, which reuses it to
    # render the "Booking details" blob) - on create the router always
    # overwrites both with values derived from room_selections below, never
    # trusting whatever the client sent for them.
    room_type: Optional[str] = None
    no_of_rooms: int = Field(default=1, gt=0)
    no_of_guests: int = Field(default=1, gt=0)
    no_of_infants: int = Field(default=0, ge=0)
    expected_check_in_time: Optional[str] = None
    expected_check_out_time: Optional[str] = None
    smoking_preference: bool = False


class RoomSelectionIn(BaseModel):
    """One line of a hotel booking's room selection - a stay can combine several of these
    (different room types, or the same one at a higher quantity), not just one type."""

    space_inventory_id: int
    quantity: int = Field(gt=0)


class CarServiceDetailsIn(BaseModel):
    car_brand: Optional[str] = None
    car_model: Optional[str] = None
    plate_number: Optional[str] = None
    service_type: Optional[str] = None
    customer_remarks: Optional[str] = None


class GeneralServiceDetailsIn(BaseModel):
    staff_requested_id: Optional[int] = None
    service_specifics: Optional[dict[str, Any]] = None


class AppointmentCreate(BaseModel):
    business_id: int
    service_id: int
    staff_id: Optional[int] = None
    # Restaurant (and any other non-Hotel space-based type): exactly one
    # space/table, via space_inventory_id, as before. Hotel: one or more
    # room selections via room_selections instead - see the appointments
    # router, which rejects space_inventory_id for Hotel and requires
    # room_selections there.
    space_inventory_id: Optional[int] = None
    room_selections: Optional[list[RoomSelectionIn]] = None
    start_datetime: datetime
    # Check-out instant, for Hotel bookings only (a stay of N nights, not a
    # single fixed-duration slot - see the appointments router). Every other
    # business type still gets its end_datetime purely from
    # Service.duration_minutes and must not send this.
    end_datetime: Optional[datetime] = None

    restaurant_details: Optional[RestaurantDetailsIn] = None
    hotel_details: Optional[HotelDetailsIn] = None
    car_service_details: Optional[CarServiceDetailsIn] = None
    general_service_details: Optional[GeneralServiceDetailsIn] = None


class AppointmentStatusUpdate(BaseModel):
    """Business accepts/rejects a Pending appointment - PART 2 state machine."""

    status: Literal[AppointmentStatus.CONFIRMED, AppointmentStatus.CANCELLED]
    reason: Optional[str] = None


class ForceCancelRequest(BaseModel):
    """Admin override - PART 3.3 / PART 6."""

    reason: str


# ---------------------------------------------------------------------------
# Response shapes
# ---------------------------------------------------------------------------
class _BriefOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int


class BusinessBriefOut(_BriefOut):
    business_name: str
    category: str
    currency: str


class ServiceBriefOut(_BriefOut):
    name: str
    duration_minutes: int
    price: Optional[float]


class StaffBriefOut(_BriefOut):
    name: str


class SpaceInventoryBriefOut(_BriefOut):
    category_name: str
    price: Optional[float] = None
    # Only populated when the appointment is being shown to the customer who
    # booked it and their currency (from their own phone number) differs
    # from the business's - see from_model's target_currency.
    converted_price: Optional[float] = None


class UserBriefOut(_BriefOut):
    first_name: str
    last_name: str
    email: str
    phone_number: Optional[str]


class RoomItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    space_inventory: SpaceInventoryBriefOut
    quantity: int


class AppointmentOut(BaseModel):
    id: int
    business: BusinessBriefOut
    service: ServiceBriefOut
    staff: Optional[StaffBriefOut]
    # The first/primary room selection (Hotel) or the single table (every
    # other space-based type) - kept for simple "one room" display. Hotel
    # bookings that combine several room types carry the full breakdown in
    # room_items instead; this is just room_items[0] then.
    space_inventory: Optional[SpaceInventoryBriefOut]
    # Hotel only - every room selection making up the stay, each with its
    # own quantity. Empty for every other appointment type.
    room_items: list[RoomItemOut] = []
    appointment_type: AppointmentType
    start_datetime: datetime
    end_datetime: datetime
    # For Hotel: nights stayed, and the sum across room_items of (that room
    # type's price x nights x its quantity). For every other type: nights is
    # None and total_price is just Service.price, unchanged - see
    # from_model below.
    nights: Optional[int] = None
    total_price: Optional[float] = None
    # Only populated for the customer who booked it, converted from the
    # business's currency to theirs (see from_model's target_currency) - the
    # business/admin view of the same appointment never gets this, since a
    # business wants to see its own bookings in its own currency.
    converted_total_price: Optional[float] = None
    # The currency converted_total_price/space_inventory.converted_price are
    # actually in - the client can't format them correctly without this.
    customer_currency: Optional[str] = None
    status: AppointmentStatus
    google_calendar_event_id: Optional[str]
    cancellation_reason: Optional[str]
    created_at: datetime
    updated_at: datetime
    details: Optional[dict[str, Any]] = None
    user: Optional[UserBriefOut] = None  # populated for the business/admin views
    # Set once the customer has left a review for this appointment - lets
    # the frontend show "Leave a review" only when status is Completed AND
    # this is still null, rather than after every appointment.
    review: Optional[ReviewOut] = None

    @classmethod
    def from_model(cls, appt, *, include_user: bool = False, target_currency: Optional[str] = None) -> "AppointmentOut":
        details = None
        if appt.restaurant_details:
            details = RestaurantDetailsIn.model_validate(appt.restaurant_details, from_attributes=True).model_dump()
        elif appt.hotel_details:
            details = HotelDetailsIn.model_validate(appt.hotel_details, from_attributes=True).model_dump()
        elif appt.car_service_details:
            details = CarServiceDetailsIn.model_validate(appt.car_service_details, from_attributes=True).model_dump()
        elif appt.general_service_details:
            details = GeneralServiceDetailsIn.model_validate(
                appt.general_service_details, from_attributes=True
            ).model_dump()

        nights = None
        total_price = appt.service.price
        room_items_out: list[RoomItemOut] = []
        primary_space_inventory = appt.space_inventory  # non-Hotel: the single booked table/space, as before

        if appt.appointment_type == AppointmentType.HOTEL:
            nights = max(1, math.ceil((appt.end_datetime - appt.start_datetime).total_seconds() / 86400))
            # The nightly rate belongs to each room type booked (a Suite and
            # a Deluxe Room don't cost the same), not to the generic "Room
            # Booking" Service every room type shares - see
            # SpaceInventory.price. total_price sums nights x quantity x
            # rate across every room selection; if any selection's room
            # type has no price set, the whole total is unknown (None)
            # rather than silently partial.
            running_total = 0.0
            price_known = len(appt.room_items) > 0
            for item in appt.room_items:
                room_items_out.append(
                    RoomItemOut(
                        space_inventory=SpaceInventoryBriefOut.model_validate(item.space_inventory), quantity=item.quantity
                    )
                )
                if item.space_inventory.price is None:
                    price_known = False
                else:
                    running_total += item.space_inventory.price * nights * item.quantity
            total_price = running_total if price_known else None
            primary_space_inventory = appt.room_items[0].space_inventory if appt.room_items else None

        space_inventory_out = (
            SpaceInventoryBriefOut.model_validate(primary_space_inventory) if primary_space_inventory else None
        )
        converted_total_price = None
        if target_currency is not None:
            converted_total_price = convert_amount(total_price, base=appt.business.currency, target=target_currency)
            if space_inventory_out is not None:
                space_inventory_out.converted_price = convert_amount(
                    space_inventory_out.price, base=appt.business.currency, target=target_currency
                )
            for room_item_out in room_items_out:
                room_item_out.space_inventory.converted_price = convert_amount(
                    room_item_out.space_inventory.price, base=appt.business.currency, target=target_currency
                )

        return cls(
            id=appt.id,
            business=BusinessBriefOut.model_validate(appt.business),
            service=ServiceBriefOut.model_validate(appt.service),
            staff=StaffBriefOut.model_validate(appt.staff) if appt.staff else None,
            space_inventory=space_inventory_out,
            room_items=room_items_out,
            customer_currency=target_currency,
            appointment_type=appt.appointment_type,
            start_datetime=appt.start_datetime,
            end_datetime=appt.end_datetime,
            nights=nights,
            total_price=total_price,
            converted_total_price=converted_total_price,
            status=appt.status,
            google_calendar_event_id=appt.google_calendar_event_id,
            cancellation_reason=appt.cancellation_reason,
            created_at=appt.created_at,
            updated_at=appt.updated_at,
            details=details,
            user=UserBriefOut.model_validate(appt.user) if include_user and appt.user else None,
            review=ReviewOut.from_model(appt.review) if appt.review else None,
        )
