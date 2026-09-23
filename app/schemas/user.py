from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator

from app.enums import AccountStatus
from app.schemas.validators import validate_phone_number, validate_timezone


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    first_name: str
    last_name: str
    phone_number: str | None
    account_status: AccountStatus
    timezone: str
    has_google_calendar_linked: bool = False
    created_at: datetime

    @classmethod
    def from_model(cls, user) -> "UserOut":
        data = cls.model_validate(user)
        data.has_google_calendar_linked = bool(user.google_calendar_token)
        return data


class UserUpdate(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    phone_number: str | None = None
    timezone: str | None = None

    @field_validator("phone_number", mode="before")
    @classmethod
    def _normalize_phone_number(cls, v):
        return validate_phone_number(v)

    @field_validator("timezone")
    @classmethod
    def _check_timezone(cls, v):
        return validate_timezone(v) if v is not None else v


class GoogleCalendarTokenIn(BaseModel):
    """
    The frontend completes the Google OAuth consent flow itself and hands us
    the resulting token to store - the backend never runs the OAuth redirect
    dance for the customer.
    """

    token: str
