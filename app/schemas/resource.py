from typing import Any, Optional

from pydantic import BaseModel, ConfigDict

from app.enums import SpaceInventoryType


# --- Service ---
class ServiceCreate(BaseModel):
    name: str
    duration_minutes: int
    price: Optional[float] = None


class ServiceUpdate(BaseModel):
    name: Optional[str] = None
    duration_minutes: Optional[int] = None
    price: Optional[float] = None
    is_active: Optional[bool] = None


class ServiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    business_id: int
    name: str
    duration_minutes: int
    price: Optional[float]
    is_active: bool
    # Only populated when the public listing endpoint is queried with
    # target_currency (see list_public_services) - `price` converted from
    # the business's own Business.currency, for a customer browsing in a
    # different currency. None whenever conversion wasn't requested or the
    # exchange rate couldn't be fetched - callers fall back to `price`.
    converted_price: Optional[float] = None


# --- Staff ---
class StaffCreate(BaseModel):
    name: str
    role_type: Optional[str] = None
    working_hours: Optional[dict[str, Any]] = None


class StaffUpdate(BaseModel):
    name: Optional[str] = None
    role_type: Optional[str] = None
    working_hours: Optional[dict[str, Any]] = None
    is_active: Optional[bool] = None


class StaffOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    business_id: int
    name: str
    role_type: Optional[str]
    working_hours: Optional[dict[str, Any]]
    is_active: bool


# --- Space Inventory ---
class SpaceInventoryCreate(BaseModel):
    inventory_type: SpaceInventoryType
    category_name: str
    total_quantity: int
    capacity_per_unit: Optional[int] = None
    price: Optional[float] = None


class SpaceInventoryUpdate(BaseModel):
    category_name: Optional[str] = None
    total_quantity: Optional[int] = None
    capacity_per_unit: Optional[int] = None
    price: Optional[float] = None
    is_active: Optional[bool] = None


class SpaceInventoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    business_id: int
    inventory_type: SpaceInventoryType
    category_name: str
    total_quantity: int
    capacity_per_unit: Optional[int]
    price: Optional[float]
    is_active: bool
    # Only populated when the public listing endpoint is queried with a
    # date range (see list_public_inventory) - units of this category
    # still free for that window, so the frontend can filter out or label
    # a sold-out room type before the customer even tries to book it.
    available_quantity: Optional[int] = None
    # Same idea as ServiceOut.converted_price, for a room type's nightly rate.
    converted_price: Optional[float] = None
