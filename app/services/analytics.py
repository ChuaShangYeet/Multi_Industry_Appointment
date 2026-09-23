"""
Admin dashboard metrics (PART 6.2 / Backend Architecture #6).

"Active" is computed on the fly, not cached, so it's always accurate as of
the current request.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.enums import ACTIVE_APPOINTMENT_STATUSES, AppointmentStatus
from app.models.appointment import Appointment
from app.models.business import Business
from app.models.user import User


def activity_window(now: Optional[datetime] = None) -> Tuple[datetime, datetime]:
    now = now or datetime.now(timezone.utc)
    return now - timedelta(days=30), now + timedelta(days=30)


def total_customers(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(User)) or 0


def total_businesses(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(Business)) or 0


def active_customers(db: Session, *, now: Optional[datetime] = None) -> int:
    """Distinct customers with >=1 Pending/Confirmed appointment starting within the +/-1 month window."""
    window_start, window_end = activity_window(now)
    return (
        db.scalar(
            select(func.count(func.distinct(Appointment.user_id))).where(
                Appointment.status.in_(ACTIVE_APPOINTMENT_STATUSES),
                Appointment.start_datetime >= window_start,
                Appointment.start_datetime <= window_end,
            )
        )
        or 0
    )


def active_businesses(db: Session, *, now: Optional[datetime] = None) -> int:
    """Distinct businesses with >=1 Confirmed (accepted) appointment starting within the +/-1 month window."""
    window_start, window_end = activity_window(now)
    return (
        db.scalar(
            select(func.count(func.distinct(Appointment.business_id))).where(
                Appointment.status == AppointmentStatus.CONFIRMED,
                Appointment.start_datetime >= window_start,
                Appointment.start_datetime <= window_end,
            )
        )
        or 0
    )
