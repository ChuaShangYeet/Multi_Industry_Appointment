from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator

from app.enums import AccountStatus, AdminActionType, AdminRoleLevel, AdminTargetEntity
from app.schemas.appointment import AppointmentOut
from app.schemas.business import BusinessAdminOut
from app.schemas.user import UserOut
from app.schemas.validators import validate_password_strength, validate_phone_number


class AdminLoginRequest(BaseModel):
    email: EmailStr
    password: str


class AdminCreate(BaseModel):
    """Used only by the bootstrap script / a SuperAdmin creating another admin."""

    email: EmailStr
    password: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    role_level: AdminRoleLevel = AdminRoleLevel.SUPPORT_STAFF

    @field_validator("password")
    @classmethod
    def _check_password_strength(cls, v):
        return validate_password_strength(v)


class AdminOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    first_name: Optional[str]
    last_name: Optional[str]
    role_level: AdminRoleLevel


class DashboardMetrics(BaseModel):
    total_customers: int
    active_customers: int
    total_businesses: int
    active_businesses: int
    window_start: datetime
    window_end: datetime


class CustomerListItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    first_name: str
    last_name: str
    account_status: AccountStatus
    created_at: datetime


class CustomerAdminUpdate(BaseModel):
    """PART 3.1: password resets, email updates, clearing OAuth tokens, status changes."""

    email: Optional[EmailStr] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone_number: Optional[str] = None
    account_status: Optional[AccountStatus] = None
    new_password: Optional[str] = None
    clear_google_calendar_token: bool = False

    @field_validator("phone_number", mode="before")
    @classmethod
    def _normalize_phone_number(cls, v):
        return validate_phone_number(v)

    @field_validator("new_password")
    @classmethod
    def _check_password_strength(cls, v):
        return validate_password_strength(v) if v is not None else v


class BusinessListItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    business_name: str
    category: str
    approval_status: str
    created_at: datetime


class BusinessAdminPasswordReset(BaseModel):
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _check_password_strength(cls, v):
        return validate_password_strength(v)


class InventoryAdjustRequest(BaseModel):
    total_quantity: int
    reason: str


class CustomerAdminDetailOut(BaseModel):
    """PART 3.1 Read: unified profile with historical/upcoming appointments."""

    user: UserOut
    appointments: list[AppointmentOut]


class BusinessAdminDetailOut(BaseModel):
    """PART 3.2 Read: full profile plus a quick performance snapshot."""

    business: BusinessAdminOut
    total_services: int
    total_staff: int
    total_inventory_items: int
    total_appointments: int
    upcoming_confirmed_appointments: int


class ModerateContentRequest(BaseModel):
    """PART 3.3 Content Moderation: hide/unhide a staff member or service."""

    is_active: bool
    reason: Optional[str] = None


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    admin_id: int
    action_type: AdminActionType
    target_entity: AdminTargetEntity
    target_id: int
    notes: Optional[str]
    timestamp: datetime
