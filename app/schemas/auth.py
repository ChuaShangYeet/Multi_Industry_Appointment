from pydantic import BaseModel, EmailStr, field_validator

from app.enums import BusinessCategory
from app.schemas.validators import validate_currency, validate_password_strength, validate_phone_number, validate_timezone


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str


class CustomerRegisterRequest(BaseModel):
    email: EmailStr
    password: str
    first_name: str
    last_name: str
    phone_number: str | None = None
    # IANA zone, e.g. "Asia/Kuala_Lumpur" - the frontend auto-detects this via
    # the browser and lets the customer override it; purely a display
    # preference (see app.models.user.User.timezone).
    timezone: str = "UTC"

    @field_validator("password")
    @classmethod
    def _check_password_strength(cls, v):
        return validate_password_strength(v)

    @field_validator("phone_number", mode="before")
    @classmethod
    def _normalize_phone_number(cls, v):
        return validate_phone_number(v)

    @field_validator("timezone")
    @classmethod
    def _check_timezone(cls, v):
        return validate_timezone(v)


class LoginRequest(BaseModel):
    """Login only checks a password against its stored hash - never re-validates its strength,
    so accounts created before this rule existed can still log in."""

    email: EmailStr
    password: str


class BusinessRegisterRequest(BaseModel):
    email: EmailStr
    password: str
    business_name: str
    category: BusinessCategory
    description: str | None = None
    address: str | None = None
    city: str | None = None
    phone_number: str | None = None
    # IANA zone the business actually operates in - anchors every appointment
    # booked with it to a real instant (see app.models.business.Business.timezone).
    # The frontend auto-detects this via the browser and lets the business
    # override it, since a business's true operating timezone may differ from
    # wherever the person filling in the registration form happens to be.
    timezone: str = "UTC"
    # ISO 4217 code the business's own prices are in (see
    # app.models.business.Business.currency) - what customers browsing in a
    # different currency see converted from.
    currency: str = "USD"

    @field_validator("password")
    @classmethod
    def _check_password_strength(cls, v):
        return validate_password_strength(v)

    @field_validator("phone_number", mode="before")
    @classmethod
    def _normalize_phone_number(cls, v):
        return validate_phone_number(v)

    @field_validator("timezone")
    @classmethod
    def _check_timezone(cls, v):
        return validate_timezone(v)

    @field_validator("currency")
    @classmethod
    def _check_currency(cls, v):
        return validate_currency(v)
