from typing import Optional

from sqlalchemy import Boolean, Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.enums import AccountStatus
from app.models.mixins import TimestampMixin


class User(Base, TimestampMixin):
    """The Customer entity - the person browsing and booking appointments."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone_number: Mapped[Optional[str]] = mapped_column(String(30))
    account_status: Mapped[AccountStatus] = mapped_column(
        Enum(AccountStatus, native_enum=False, length=20), nullable=False, default=AccountStatus.ACTIVE
    )

    # IANA timezone name (e.g. "Asia/Kuala_Lumpur") the customer wants their
    # own appointment times displayed in - purely a display preference, it
    # has no effect on availability/conflict checking (which always happens
    # against the business's own timezone-anchored UTC instant - see
    # Business.timezone). Defaults to "UTC" until the customer sets one.
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC", server_default="UTC")

    # OAuth token used to write bookings into the customer's own calendar.
    # Stored as an opaque string (in practice a JSON blob of
    # access/refresh/expiry) - the app never inspects its contents directly,
    # only forwards it to app.services.google_calendar.
    google_calendar_token: Mapped[Optional[str]] = mapped_column(String(2048))

    # GDPR hard-delete support: we never physically remove a row that has
    # appointment history attached to it (that would corrupt financial /
    # historical records other tables reference). Instead we scrub PII and
    # flag the row, per PART 3.1 of the spec ("Hard Delete (GDPR
    # anonymization)").
    is_anonymized: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    appointments: Mapped[list["Appointment"]] = relationship(back_populates="user")

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def is_active(self) -> bool:
        return self.account_status == AccountStatus.ACTIVE
