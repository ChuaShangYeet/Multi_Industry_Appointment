"""
Shared Pydantic field validators used across multiple schemas.

Phone numbers are stored as free text on the model (no format constraint at
the DB level - see app.models.user.User.phone_number), but every schema
that accepts one from a client runs it through validate_phone_number first,
so only genuinely valid, country-code-prefixed numbers ever reach the
database - normalized to a single consistent format (E.164, e.g.
"+60123456789") regardless of how the user typed it.
"""
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import phonenumbers

PASSWORD_MIN_LENGTH = 8
_UPPERCASE_RE = re.compile(r"[A-Z]")
_LOWERCASE_RE = re.compile(r"[a-z]")
_DIGIT_RE = re.compile(r"[0-9]")
_SYMBOL_RE = re.compile(r"[^A-Za-z0-9]")  # anything that isn't a letter or digit counts as a symbol

DAYS_OF_WEEK = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")

# ISO 4217 codes this platform can price a business in and convert to for a
# customer - not exhaustive, but covers every country the phone country
# picker (frontend/src/countries.ts) offers, plus a few more majors.
CURRENCY_CODES = {
    "USD", "EUR", "GBP", "MYR", "SGD", "IDR", "THB", "PHP", "VND", "HKD",
    "CNY", "JPY", "KRW", "INR", "AUD", "NZD", "AED", "SAR", "CHF", "SEK",
    "BRL", "MXN", "ZAR", "NGN", "CAD",
}


def validate_password_strength(value: str) -> str:
    """
    Enforces a minimum password strength: at least 8 characters, with at
    least one uppercase letter, one lowercase letter, one digit, and one
    symbol. Applied to every password a client sets (registration, admin
    password resets) - never to a login password, since that only needs to
    match whatever hash is already stored, including for accounts created
    before this rule existed.
    """
    if len(value) < PASSWORD_MIN_LENGTH:
        raise ValueError(f"Password must be at least {PASSWORD_MIN_LENGTH} characters long.")
    if not _UPPERCASE_RE.search(value):
        raise ValueError("Password must contain at least one uppercase letter.")
    if not _LOWERCASE_RE.search(value):
        raise ValueError("Password must contain at least one lowercase letter.")
    if not _DIGIT_RE.search(value):
        raise ValueError("Password must contain at least one number.")
    if not _SYMBOL_RE.search(value):
        raise ValueError("Password must contain at least one symbol (e.g. ! @ # $ % ^ & *).")
    return value


def validate_phone_number(value: str | None) -> str | None:
    """
    Validates an international phone number and normalizes it to E.164.

    The caller picks their own country by typing its "+<country code>"
    prefix (e.g. +1 for the US, +60 for Malaysia, +44 for the UK) - this
    never assumes a default country of its own, it just checks that what
    results is a real, dialable number for whichever country was chosen.
    """
    if value is None:
        return None

    value = value.strip()
    if not value:
        return None

    if not value.startswith("+"):
        raise ValueError(
            "Phone number must start with a country code, e.g. +60123456789 (Malaysia) "
            "or +14155552671 (US)."
        )

    try:
        parsed = phonenumbers.parse(value, None)
    except phonenumbers.NumberParseException as exc:
        raise ValueError(f"'{value}' is not a valid phone number ({exc}).") from exc

    if not phonenumbers.is_valid_number(parsed):
        raise ValueError(f"'{value}' is not a valid, dialable phone number for that country code.")

    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def validate_operating_hours(value: dict | None) -> dict | None:
    """
    Validates a business's (or staff member's) weekly schedule: exactly one
    entry per day of the week (`DAYS_OF_WEEK`), each either `null` (closed
    that day) or `{"open": "HH:MM", "close": "HH:MM"}` in 24-hour wall-clock
    time, in the timezone the business itself records separately - with
    `open` strictly before `close`.
    """
    if value is None:
        return None

    missing = [d for d in DAYS_OF_WEEK if d not in value]
    unexpected = [d for d in value if d not in DAYS_OF_WEEK]
    if missing or unexpected:
        problems = []
        if missing:
            problems.append(f"missing {missing}")
        if unexpected:
            problems.append(f"unexpected {unexpected}")
        raise ValueError(
            f"operating_hours must have exactly one entry per day of the week ({', '.join(problems)})."
        )

    normalized = {}
    for day in DAYS_OF_WEEK:
        hours = value[day]
        if hours is None:
            normalized[day] = None
            continue

        if not isinstance(hours, dict) or set(hours) != {"open", "close"}:
            raise ValueError(
                f"operating_hours['{day}'] must be null (closed) or an object with 'open' and 'close' times."
            )

        open_time, close_time = hours["open"], hours["close"]
        if not (isinstance(open_time, str) and _TIME_RE.match(open_time)):
            raise ValueError(f"operating_hours['{day}']['open'] must be a 24-hour 'HH:MM' time, got {open_time!r}.")
        if not (isinstance(close_time, str) and _TIME_RE.match(close_time)):
            raise ValueError(f"operating_hours['{day}']['close'] must be a 24-hour 'HH:MM' time, got {close_time!r}.")
        if open_time >= close_time:
            raise ValueError(f"operating_hours['{day}']: 'open' ({open_time}) must be before 'close' ({close_time}).")

        normalized[day] = {"open": open_time, "close": close_time}

    return normalized


def validate_currency(value: str) -> str:
    """Validates an ISO 4217 currency code against CURRENCY_CODES, normalized to uppercase."""
    code = value.strip().upper()
    if code not in CURRENCY_CODES:
        raise ValueError(f"'{value}' is not a supported currency code. Supported: {', '.join(sorted(CURRENCY_CODES))}.")
    return code


def validate_timezone(value: str) -> str:
    """
    Validates an IANA timezone name (e.g. "Asia/Kuala_Lumpur", "America/New_York",
    "UTC") using Python's own tz database, so only real zones are ever stored.
    """
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(
            f"'{value}' is not a recognized IANA timezone name (e.g. 'Asia/Kuala_Lumpur', 'UTC')."
        ) from exc
    return value
