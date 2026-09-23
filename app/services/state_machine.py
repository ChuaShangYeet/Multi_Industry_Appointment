"""
APPOINTMENT LIFECYCLE STATE MACHINE (PART 2.4 / Backend Architecture #4).

All new appointments start Pending. The business transitions Pending ->
Confirmed/Cancelled. Once Confirmed or Cancelled via that normal flow, the
record is locked - a business can no longer change its status. The only
further moves are the business marking a Confirmed appointment Completed
once its time has passed, and an admin force-cancel override that bypasses
the lock entirely.
"""
from datetime import datetime, timezone
from typing import Optional

from app.enums import AppointmentStatus
from app.models.appointment import Appointment


class InvalidTransitionError(Exception):
    """Raised on any disallowed state transition - the router turns this into HTTP 409."""


def apply_business_decision(
    appointment: Appointment, *, new_status: AppointmentStatus, reason: Optional[str] = None
) -> None:
    """Business accepts (Confirmed) or rejects (Cancelled) a Pending appointment."""
    if appointment.status != AppointmentStatus.PENDING:
        raise InvalidTransitionError(
            f"Appointment is already {appointment.status.value} and can no longer be modified."
        )
    if new_status not in (AppointmentStatus.CONFIRMED, AppointmentStatus.CANCELLED):
        raise InvalidTransitionError("A business can only confirm or cancel a pending appointment.")

    appointment.status = new_status
    if new_status == AppointmentStatus.CANCELLED:
        appointment.cancellation_reason = reason or "Rejected by business"


def customer_cancel(appointment: Appointment) -> None:
    """A customer may cancel their own booking only while it's still awaiting business confirmation."""
    if appointment.status != AppointmentStatus.PENDING:
        raise InvalidTransitionError(
            "Only a Pending appointment can be cancelled here; a Confirmed booking must be cancelled "
            "through the business."
        )
    appointment.status = AppointmentStatus.CANCELLED
    appointment.cancellation_reason = "Cancelled by customer"


def mark_completed(appointment: Appointment) -> None:
    """Business marks a Confirmed appointment as Completed once its scheduled end time has passed."""
    if appointment.status != AppointmentStatus.CONFIRMED:
        raise InvalidTransitionError("Only a Confirmed appointment can be marked Completed.")

    now = datetime.now(timezone.utc)
    end = appointment.end_datetime
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    if now < end:
        raise InvalidTransitionError("Appointment cannot be marked Completed before its scheduled end time.")

    appointment.status = AppointmentStatus.COMPLETED


def force_cancel(appointment: Appointment, *, reason: str) -> None:
    """Admin override - bypasses the normal lock (PART 3.3 / Backend Architecture #6)."""
    if appointment.status == AppointmentStatus.CANCELLED:
        raise InvalidTransitionError("Appointment is already cancelled.")
    appointment.status = AppointmentStatus.CANCELLED
    appointment.cancellation_reason = reason
