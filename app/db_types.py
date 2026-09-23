"""
Custom SQLAlchemy column types.

SQLite (used for local dev - see app/database.py) has no native tz-aware
datetime type. SQLAlchemy's own `DateTime(timezone=True)` on SQLite silently
stores whatever naive wall-clock fields the aware datetime has, *without*
converting to UTC first - so "2030-06-15 14:00 +08:00" and
"2030-06-15 06:00 Z" (the exact same instant) get stored as two different,
incomparable values. That silently breaks the availability engine's overlap
checks: two bookings for the same real moment, expressed with different UTC
offsets, would not be detected as a conflict. PostgreSQL's own TIMESTAMPTZ
normalizes to UTC internally and doesn't have this problem, but relying on
that per-database behavior is fragile - `UTCDateTime` makes the "always
normalized to UTC" guarantee explicit and backend-agnostic, so appointment
times are always compared correctly regardless of which database is behind
the app or what UTC offset a client happened to send.
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator):
    """A tz-aware DateTime that is always normalized to UTC on the way in and out."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: Optional[datetime], dialect) -> Optional[datetime]:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError(
                "UTCDateTime received a naive datetime - every stored timestamp must be "
                "timezone-aware so it can be normalized to UTC."
            )
        return value.astimezone(timezone.utc)

    def process_result_value(self, value: Optional[datetime], dialect) -> Optional[datetime]:
        if value is None:
            return None
        # SQLite hands back a naive datetime (see module docstring); Postgres
        # hands back one already tagged UTC. Either way, the value's fields
        # are already the correct UTC wall-clock reading at this point
        # because process_bind_param normalized it before storage - this
        # just (re)attaches the tzinfo so callers always get an aware value.
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
