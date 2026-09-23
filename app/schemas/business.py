from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator

from app.enums import BusinessApprovalStatus, BusinessCategory
from app.schemas.validators import validate_currency, validate_operating_hours, validate_phone_number, validate_timezone


class BusinessCardOut(BaseModel):
    """Discovery gallery tile: picture, name, rating, location - PART 4.3."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    business_name: str
    category: BusinessCategory
    city: str | None
    cover_image_url: str | None
    average_rating: float
    rating_count: int


class BusinessPublicDetailOut(BaseModel):
    """Business Details page: hours, address, services (services come from a separate endpoint) - PART 4.3."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    business_name: str
    category: BusinessCategory
    description: str | None
    address: str | None
    city: str | None
    cover_image_url: str | None
    phone_number: str | None
    operating_hours: dict[str, Any] | None
    timezone: str
    currency: str
    average_rating: float
    rating_count: int


class BusinessSelfOut(BaseModel):
    """A business's view of its own account, including approval/onboarding state."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    business_name: str
    category: BusinessCategory
    approval_status: BusinessApprovalStatus
    onboarding_notes: str | None
    description: str | None
    address: str | None
    city: str | None
    cover_image_url: str | None
    phone_number: str | None
    operating_hours: dict[str, Any] | None
    timezone: str
    currency: str
    google_calendar_id: str | None
    average_rating: float
    rating_count: int
    created_at: datetime


class BusinessAdminOut(BusinessSelfOut):
    """Same as BusinessSelfOut - admins see everything a business itself sees, plus audit context is fetched separately."""


class BusinessUpdate(BaseModel):
    """Fields a business may edit about itself."""

    business_name: Optional[str] = None
    category: Optional[BusinessCategory] = None
    description: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    cover_image_url: Optional[str] = None
    phone_number: Optional[str] = None
    operating_hours: Optional[dict[str, Any]] = None
    timezone: Optional[str] = None
    currency: Optional[str] = None

    @field_validator("phone_number", mode="before")
    @classmethod
    def _normalize_phone_number(cls, v):
        return validate_phone_number(v)

    @field_validator("operating_hours")
    @classmethod
    def _check_operating_hours(cls, v):
        return validate_operating_hours(v)

    @field_validator("timezone")
    @classmethod
    def _check_timezone(cls, v):
        return validate_timezone(v) if v is not None else v

    @field_validator("currency")
    @classmethod
    def _check_currency(cls, v):
        return validate_currency(v) if v is not None else v


class GoogleCalendarIdIn(BaseModel):
    google_calendar_id: str


class BusinessAdminUpdate(BaseModel):
    """Admin-only governance fields - PART 3.2."""

    approval_status: Optional[BusinessApprovalStatus] = None
    onboarding_notes: Optional[str] = None
    business_name: Optional[str] = None
    category: Optional[BusinessCategory] = None
    operating_hours: Optional[dict[str, Any]] = None
    timezone: Optional[str] = None
    google_calendar_id: Optional[str] = None

    @field_validator("operating_hours")
    @classmethod
    def _check_operating_hours(cls, v):
        return validate_operating_hours(v)

    @field_validator("timezone")
    @classmethod
    def _check_timezone(cls, v):
        return validate_timezone(v) if v is not None else v
