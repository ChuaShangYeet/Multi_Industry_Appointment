from typing import Any, Optional

from sqlalchemy import Enum, Float, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.enums import BusinessApprovalStatus, BusinessCategory
from app.models.mixins import TimestampMixin


class Business(Base, TimestampMixin):
    """
    The Provider entity (restaurant, hotel, spa, car service, professional).

    Deviation from the original spec: added `email` / `password_hash` so a
    business can actually authenticate against the API (PART 2's login gate
    for "Business is Pending/Suspended -> 403" only makes sense if the
    business itself can log in). Also added a handful of read-only-ish
    fields (`description`, `address`, `city`, `cover_image_url`,
    `average_rating`, `rating_count`) - the customer-facing discovery
    gallery in PART 4 explicitly needs a picture, rating and location per
    business tile, and the original entity had nowhere to put them. Also
    added `timezone` (an IANA zone name, e.g. "Asia/Kuala_Lumpur") - the
    spec's `operating_hours` are plain wall-clock times ("09:00") with no
    timezone of their own, which is meaningless without one, and a booking
    is fundamentally a slot on the business's own clock (you book "2pm at
    the salon", not "2pm in the customer's timezone"). This is what anchors
    every appointment's start_datetime/end_datetime to a real instant, so
    the availability engine's overlap checks stay correct no matter what
    timezone the customer booking it happens to be in.
    """

    __tablename__ = "businesses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    business_name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[BusinessCategory] = mapped_column(Enum(BusinessCategory, native_enum=False, length=32))
    approval_status: Mapped[BusinessApprovalStatus] = mapped_column(
        Enum(BusinessApprovalStatus, native_enum=False, length=20),
        nullable=False,
        default=BusinessApprovalStatus.PENDING,
    )
    onboarding_notes: Mapped[Optional[str]] = mapped_column(Text)

    google_calendar_id: Mapped[Optional[str]] = mapped_column(String(255))

    # One entry per day of the week (see app.schemas.validators.DAYS_OF_WEEK),
    # each either null (closed) or {"open": "09:00", "close": "18:00"} - the
    # wall-clock times are in this business's own timezone (below).
    operating_hours: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)

    # IANA timezone name (validated via app.schemas.validators.validate_timezone).
    # Every appointment booked with this business is anchored to a wall-clock
    # time in this zone before being converted to the UTC instant that's
    # actually stored - see the appointments router.
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC", server_default="UTC")

    # ISO 4217 code (validated via app.schemas.validators.validate_currency)
    # this business's own Service.price/SpaceInventory.price are denominated
    # in - the customer-facing price display converts from this to the
    # customer's own currency (see app.services.currency).
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD", server_default="USD")

    # --- Discovery/UX fields (see class docstring) ---
    description: Mapped[Optional[str]] = mapped_column(Text)
    address: Mapped[Optional[str]] = mapped_column(String(500))
    city: Mapped[Optional[str]] = mapped_column(String(120))
    # E.164, e.g. "+60312345678" - validated via app.schemas.validators.validate_phone_number.
    # Shown to customers on the Business Details page so they have a direct
    # number to call, distinct from the business's login email.
    phone_number: Mapped[Optional[str]] = mapped_column(String(32))
    cover_image_url: Mapped[Optional[str]] = mapped_column(String(1000))
    # Denormalized cache, recomputed from the real app.models.review.Review
    # rows every time one is written (see
    # app.services.reviews.recompute_business_rating) - kept on Business
    # itself so the discovery gallery can sort/filter without joining every
    # business's reviews on every request. Never written to directly.
    average_rating: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    rating_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    services: Mapped[list["Service"]] = relationship(back_populates="business", cascade="all, delete-orphan")
    staff: Mapped[list["Staff"]] = relationship(back_populates="business", cascade="all, delete-orphan")
    space_inventory: Mapped[list["SpaceInventory"]] = relationship(
        back_populates="business", cascade="all, delete-orphan"
    )
    appointments: Mapped[list["Appointment"]] = relationship(back_populates="business")

    @property
    def is_approved(self) -> bool:
        return self.approval_status == BusinessApprovalStatus.APPROVED
