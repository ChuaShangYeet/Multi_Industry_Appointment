"""
Google Calendar dual-sync orchestrator (PART 2.3 / Backend Architecture #5).

Design goal: the booking / accept / reject / cancel flow must NEVER fail
because Google is down or misconfigured - a sync failure is logged and
swallowed, never raised to the customer as a 500. When
GOOGLE_CALENDAR_ENABLED is false (the default - this repo ships without real
OAuth/service-account credentials so it runs out of the box), every public
function here is a no-op.

Two different credentials are used for the two sides of the dual-sync:
  - Customer side: the user's own OAuth token (`User.google_calendar_token`),
    writing into their "primary" calendar.
  - Business side: a platform service account (`GOOGLE_SERVICE_ACCOUNT_FILE`)
    writing into `Business.google_calendar_id`, which must be shared with
    that service account's email in Google Calendar's sharing settings.
    (The original spec only stores a calendar id for the business, with no
    separate business OAuth token - a shared service account is the
    standard way to make that work for a multi-tenant backend.)
"""
import logging
from typing import Callable, Optional, TypeVar

from app.config import settings
from app.enums import GOOGLE_CALENDAR_COLOR_ID
from app.models.appointment import Appointment

logger = logging.getLogger("app.google_calendar")

T = TypeVar("T")


class CalendarSyncResult:
    def __init__(self, customer_event_id: Optional[str] = None, business_event_id: Optional[str] = None):
        self.customer_event_id = customer_event_id
        self.business_event_id = business_event_id


def _safe_call(fn: Callable[[], T]) -> Optional[T]:
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - any Google/network failure degrades to a no-op
        logger.warning("Google Calendar sync call failed: %s", exc)
        return None


def _build_event_body(appointment: Appointment) -> dict:
    return {
        "summary": f"{appointment.service.name} - {appointment.business.business_name}",
        "description": f"Status: {appointment.status.value}",
        "start": {"dateTime": appointment.start_datetime.isoformat()},
        "end": {"dateTime": appointment.end_datetime.isoformat()},
        "colorId": GOOGLE_CALENDAR_COLOR_ID[appointment.status],
    }


def _user_calendar_client(oauth_token: str):
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    credentials = Credentials(
        token=oauth_token,
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
    )
    return build("calendar", "v3", credentials=credentials, cache_discovery=False)


def _business_calendar_client():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    credentials = service_account.Credentials.from_service_account_file(
        settings.GOOGLE_SERVICE_ACCOUNT_FILE,
        scopes=["https://www.googleapis.com/auth/calendar"],
    )
    return build("calendar", "v3", credentials=credentials, cache_discovery=False)


def sync_appointment_created(appointment: Appointment) -> CalendarSyncResult:
    """
    Inserts the event into both calendars. The caller is responsible for
    persisting the returned event ids onto
    Appointment.google_calendar_event_id / business_google_calendar_event_id.
    """
    result = CalendarSyncResult()
    if not settings.GOOGLE_CALENDAR_ENABLED:
        logger.info("Google Calendar sync disabled - skipped create sync for appointment #%s", appointment.id)
        return result

    body = _build_event_body(appointment)

    if appointment.user.google_calendar_token:
        result.customer_event_id = _safe_call(
            lambda: _user_calendar_client(appointment.user.google_calendar_token)
            .events()
            .insert(calendarId="primary", body=body)
            .execute()
            .get("id")
        )

    if appointment.business.google_calendar_id and settings.GOOGLE_SERVICE_ACCOUNT_FILE:
        result.business_event_id = _safe_call(
            lambda: _business_calendar_client()
            .events()
            .insert(calendarId=appointment.business.google_calendar_id, body=body)
            .execute()
            .get("id")
        )

    return result


def sync_appointment_updated(appointment: Appointment) -> None:
    """Re-pushes the event (new time and/or colorId) after any status change or reschedule."""
    if not settings.GOOGLE_CALENDAR_ENABLED:
        logger.info("Google Calendar sync disabled - skipped update sync for appointment #%s", appointment.id)
        return

    body = _build_event_body(appointment)

    if appointment.google_calendar_event_id and appointment.user.google_calendar_token:
        _safe_call(
            lambda: _user_calendar_client(appointment.user.google_calendar_token)
            .events()
            .update(calendarId="primary", eventId=appointment.google_calendar_event_id, body=body)
            .execute()
        )

    if (
        appointment.business_google_calendar_event_id
        and appointment.business.google_calendar_id
        and settings.GOOGLE_SERVICE_ACCOUNT_FILE
    ):
        _safe_call(
            lambda: _business_calendar_client()
            .events()
            .update(
                calendarId=appointment.business.google_calendar_id,
                eventId=appointment.business_google_calendar_event_id,
                body=body,
            )
            .execute()
        )


def sync_appointment_deleted(appointment: Appointment) -> None:
    """Used for a force-cancel/hard removal - the accept/reject flow prefers `sync_appointment_updated`
    (turning the event red) so the customer keeps a record of the cancellation on their calendar."""
    if not settings.GOOGLE_CALENDAR_ENABLED:
        return

    if appointment.google_calendar_event_id and appointment.user.google_calendar_token:
        _safe_call(
            lambda: _user_calendar_client(appointment.user.google_calendar_token)
            .events()
            .delete(calendarId="primary", eventId=appointment.google_calendar_event_id)
            .execute()
        )

    if (
        appointment.business_google_calendar_event_id
        and appointment.business.google_calendar_id
        and settings.GOOGLE_SERVICE_ACCOUNT_FILE
    ):
        _safe_call(
            lambda: _business_calendar_client()
            .events()
            .delete(
                calendarId=appointment.business.google_calendar_id,
                eventId=appointment.business_google_calendar_event_id,
            )
            .execute()
        )
