"""
Industry-specific, 1-to-1 extensions of Appointment. Each row exists only
alongside exactly one Appointment (unique FK), keeping the base Appointment
table free of industry-specific, mostly-null columns.
"""
from typing import Any, Optional

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.enums import TablePreference
from app.models.mixins import TimestampMixin


class RestaurantDetails(Base, TimestampMixin):
    __tablename__ = "restaurant_details"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    appointment_id: Mapped[int] = mapped_column(ForeignKey("appointments.id"), unique=True, nullable=False)
    no_of_pax: Mapped[int] = mapped_column(Integer, nullable=False)
    table_preference: Mapped[Optional[TablePreference]] = mapped_column(
        Enum(TablePreference, native_enum=False, length=20)
    )
    special_requests: Mapped[Optional[str]] = mapped_column(Text)

    appointment: Mapped["Appointment"] = relationship(back_populates="restaurant_details")


class HotelDetails(Base, TimestampMixin):
    __tablename__ = "hotel_details"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    appointment_id: Mapped[int] = mapped_column(ForeignKey("appointments.id"), unique=True, nullable=False)
    # room_type and no_of_rooms are server-derived from the appointment's
    # HotelRoomItem rows (a joined label and a summed count) rather than
    # trusted from the client - see the appointments router - so they stay
    # accurate summaries even though the room selection itself is now
    # 1-to-many, not 1-to-1.
    room_type: Mapped[Optional[str]] = mapped_column(String(255))
    no_of_rooms: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    no_of_guests: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    no_of_infants: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expected_check_in_time: Mapped[Optional[str]] = mapped_column(String(20))
    expected_check_out_time: Mapped[Optional[str]] = mapped_column(String(20))
    smoking_preference: Mapped[bool] = mapped_column(Boolean, default=False)

    appointment: Mapped["Appointment"] = relationship(back_populates="hotel_details")


class HotelRoomItem(Base, TimestampMixin):
    """
    One line of a hotel booking's room selection. Unlike every other table
    in this file, this is 1-to-MANY with Appointment: a stay can combine
    several room types at once (e.g. a party of 11 as 2 Deluxe Rooms + 1
    Suite), not just more of one type - see the appointments router's
    room_selections handling and app.services.availability, which sums
    quantity per space_inventory_id (across every active, overlapping
    appointment's room items) to know how many units of a room type are
    actually occupied.
    """

    __tablename__ = "hotel_room_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    appointment_id: Mapped[int] = mapped_column(ForeignKey("appointments.id"), nullable=False, index=True)
    space_inventory_id: Mapped[int] = mapped_column(ForeignKey("space_inventory.id"), nullable=False, index=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)

    appointment: Mapped["Appointment"] = relationship(back_populates="room_items")
    space_inventory: Mapped["SpaceInventory"] = relationship()


class CarServiceDetails(Base, TimestampMixin):
    __tablename__ = "car_service_details"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    appointment_id: Mapped[int] = mapped_column(ForeignKey("appointments.id"), unique=True, nullable=False)
    car_brand: Mapped[Optional[str]] = mapped_column(String(120))
    car_model: Mapped[Optional[str]] = mapped_column(String(120))
    plate_number: Mapped[Optional[str]] = mapped_column(String(30))
    service_type: Mapped[Optional[str]] = mapped_column(String(120))
    customer_remarks: Mapped[Optional[str]] = mapped_column(Text)

    appointment: Mapped["Appointment"] = relationship(back_populates="car_service_details")


class GeneralServiceDetails(Base, TimestampMixin):
    """Spa, hair salon, professional services (e.g. tax consultation)."""

    __tablename__ = "general_service_details"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    appointment_id: Mapped[int] = mapped_column(ForeignKey("appointments.id"), unique=True, nullable=False)
    staff_requested_id: Mapped[Optional[int]] = mapped_column(ForeignKey("staff.id"), nullable=True)
    service_specifics: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)

    appointment: Mapped["Appointment"] = relationship(back_populates="general_service_details")
