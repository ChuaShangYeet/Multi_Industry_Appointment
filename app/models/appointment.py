from datetime import datetime
from typing import Optional

from sqlalchemy import Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.db_types import UTCDateTime
from app.enums import AppointmentStatus, AppointmentType
from app.models.mixins import TimestampMixin


class Appointment(Base, TimestampMixin):
    """
    The core/base entity - the hub tying together User, Business, Service and
    the specific resource (Staff or Space_Inventory). Industry-specific
    fields live in a separate 1-to-1 "details" table (see
    app.models.details) instead of being bolted on here, so this table never
    grows null-heavy columns as new industries are added.
    """

    __tablename__ = "appointments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), nullable=False, index=True)
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"), nullable=False, index=True)
    staff_id: Mapped[Optional[int]] = mapped_column(ForeignKey("staff.id"), nullable=True, index=True)
    space_inventory_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("space_inventory.id"), nullable=True, index=True
    )

    appointment_type: Mapped[AppointmentType] = mapped_column(Enum(AppointmentType, native_enum=False, length=20))
    start_datetime: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, index=True)
    end_datetime: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, index=True)
    status: Mapped[AppointmentStatus] = mapped_column(
        Enum(AppointmentStatus, native_enum=False, length=20),
        nullable=False,
        default=AppointmentStatus.PENDING,
        index=True,
    )

    google_calendar_event_id: Mapped[Optional[str]] = mapped_column(String(255))
    # Mirror event id on the *business's* calendar - the spec's dual-sync
    # mechanism writes to both the customer's and the business's calendar,
    # and each write can return a different event id.
    business_google_calendar_event_id: Mapped[Optional[str]] = mapped_column(String(255))

    cancellation_reason: Mapped[Optional[str]] = mapped_column(String(500))

    user: Mapped["User"] = relationship(back_populates="appointments")
    business: Mapped["Business"] = relationship(back_populates="appointments")
    service: Mapped["Service"] = relationship(back_populates="appointments")
    staff: Mapped[Optional["Staff"]] = relationship(back_populates="appointments", foreign_keys=[staff_id])
    space_inventory: Mapped[Optional["SpaceInventory"]] = relationship(back_populates="appointments")

    restaurant_details: Mapped[Optional["RestaurantDetails"]] = relationship(
        back_populates="appointment", uselist=False, cascade="all, delete-orphan"
    )
    hotel_details: Mapped[Optional["HotelDetails"]] = relationship(
        back_populates="appointment", uselist=False, cascade="all, delete-orphan"
    )
    car_service_details: Mapped[Optional["CarServiceDetails"]] = relationship(
        back_populates="appointment", uselist=False, cascade="all, delete-orphan"
    )
    general_service_details: Mapped[Optional["GeneralServiceDetails"]] = relationship(
        back_populates="appointment", uselist=False, cascade="all, delete-orphan"
    )
    # Hotel only, and 1-to-MANY unlike the *_details relationships above - a
    # stay can combine several room types (see app.models.details.HotelRoomItem).
    room_items: Mapped[list["HotelRoomItem"]] = relationship(back_populates="appointment", cascade="all, delete-orphan")

    # At most one - a customer may only review an appointment once it's
    # Completed (see the appointments router), and only once ever (see
    # Review.appointment_id's unique constraint).
    review: Mapped[Optional["Review"]] = relationship(back_populates="appointment", uselist=False, cascade="all, delete-orphan")

    @property
    def is_locked(self) -> bool:
        """Confirmed/Cancelled/Completed appointments can no longer transition via the normal business flow."""
        return self.status != AppointmentStatus.PENDING
