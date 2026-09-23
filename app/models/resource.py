from typing import Any, Optional

from sqlalchemy import Boolean, Enum, Float, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.enums import SpaceInventoryType
from app.models.mixins import TimestampMixin


class Service(Base, TimestampMixin):
    """What is being booked (e.g. "Haircut", "Standard Table Booking")."""

    __tablename__ = "services"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[Optional[float]] = mapped_column(Float)

    # Soft-delete flag so a business can retire a service without breaking
    # the FK on historical appointments that reference it.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    business: Mapped["Business"] = relationship(back_populates="services")
    appointments: Mapped[list["Appointment"]] = relationship(back_populates="service")


class Staff(Base, TimestampMixin):
    """Human resources: salons, spas, professionals, car service."""

    __tablename__ = "staff"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    role_type: Mapped[Optional[str]] = mapped_column(String(120))

    # Deviation from spec: the spec referenced a `working_hours_id` FK to an
    # undefined "schedule" entity. Rather than leave a dangling reference,
    # this stores the same shape of JSON schedule Business.operating_hours
    # uses (nullable = falls back to the business's own operating hours).
    working_hours: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    business: Mapped["Business"] = relationship(back_populates="staff")
    appointments: Mapped[list["Appointment"]] = relationship(
        back_populates="staff", foreign_keys="Appointment.staff_id"
    )


class SpaceInventory(Base, TimestampMixin):
    """Physical resources: hotel rooms, restaurant tables."""

    __tablename__ = "space_inventory"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), nullable=False, index=True)
    inventory_type: Mapped[SpaceInventoryType] = mapped_column(
        Enum(SpaceInventoryType, native_enum=False, length=32)
    )
    category_name: Mapped[str] = mapped_column(String(255), nullable=False)
    total_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    capacity_per_unit: Mapped[Optional[int]] = mapped_column(Integer)
    # Per-unit price - the nightly rate for a Hotel Room category (a
    # "Suite" and a "Deluxe Room" charge differently; Service.price is one
    # flat rate shared by every room type, which is the wrong place for
    # this). Unused by Restaurant/Other inventory today.
    price: Mapped[Optional[float]] = mapped_column(Float)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    business: Mapped["Business"] = relationship(back_populates="space_inventory")
    appointments: Mapped[list["Appointment"]] = relationship(back_populates="space_inventory")
