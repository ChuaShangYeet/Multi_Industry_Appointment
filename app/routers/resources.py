"""
Services, Staff and Space Inventory - PART 1.3.

Two audiences per resource type:
  - Public, read-only, scoped to an Approved business (PART 2 step 3: the
    booking flow only ever shows resources of an approved business).
  - The business itself managing its own resources (PART 5.1 "Settings").
    Gated by get_current_active_business since an unapproved business has no
    business to manage yet.

Deletion is always soft (is_active=False) - PART 3.3 "Content Moderation":
an admin can hide the exact same way a business can retire its own resource.
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_active_business
from app.enums import BusinessApprovalStatus
from app.models.business import Business
from app.models.resource import Service, SpaceInventory, Staff
from app.schemas.resource import (
    ServiceCreate,
    ServiceOut,
    ServiceUpdate,
    SpaceInventoryCreate,
    SpaceInventoryOut,
    SpaceInventoryUpdate,
    StaffCreate,
    StaffOut,
    StaffUpdate,
)
from app.schemas.validators import CURRENCY_CODES
from app.services.availability import available_units, calculate_resource_dynamic_price
from app.services.currency import convert_amount

router = APIRouter(prefix="/businesses", tags=["resources"])


def _get_approved_business_or_404(business_id: int, db: Session) -> Business:
    business = (
        db.query(Business)
        .filter(Business.id == business_id, Business.approval_status == BusinessApprovalStatus.APPROVED)
        .first()
    )
    if business is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Business not found.")
    return business


def _normalize_target_currency(target_currency: Optional[str]) -> Optional[str]:
    """None means "no conversion requested" - anything else must be a currency we recognize."""
    if target_currency is None:
        return None
    code = target_currency.strip().upper()
    if code not in CURRENCY_CODES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"'{target_currency}' is not a supported currency code.")
    return code


# ===========================================================================
# Services
#
# NOTE on route ordering: every "/me/..." literal route in this file must be
# registered BEFORE its sibling "/{business_id}/..." route, otherwise
# Starlette matches "me" as the business_id path parameter first and the
# int-typed public route 404s/422s instead of ever reaching the "me" route.
# ===========================================================================
@router.get("/me/services", response_model=list[ServiceOut])
def list_my_services(
    current_business: Business = Depends(get_current_active_business),
    db: Session = Depends(get_db),
):
    return db.query(Service).filter(Service.business_id == current_business.id).all()


@router.post("/me/services", response_model=ServiceOut, status_code=status.HTTP_201_CREATED)
def create_my_service(
    payload: ServiceCreate,
    current_business: Business = Depends(get_current_active_business),
    db: Session = Depends(get_db),
):
    service = Service(business_id=current_business.id, **payload.model_dump())
    db.add(service)
    db.commit()
    db.refresh(service)
    return service


@router.patch("/me/services/{service_id}", response_model=ServiceOut)
def update_my_service(
    service_id: int,
    payload: ServiceUpdate,
    current_business: Business = Depends(get_current_active_business),
    db: Session = Depends(get_db),
):
    service = db.query(Service).filter(Service.id == service_id, Service.business_id == current_business.id).first()
    if service is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Service not found.")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(service, field, value)
    db.commit()
    db.refresh(service)
    return service


@router.delete("/me/services/{service_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_my_service(
    service_id: int,
    current_business: Business = Depends(get_current_active_business),
    db: Session = Depends(get_db),
):
    """Soft delete: hides the service from discovery/booking without breaking historical appointment FKs."""
    service = db.query(Service).filter(Service.id == service_id, Service.business_id == current_business.id).first()
    if service is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Service not found.")
    service.is_active = False
    db.commit()


@router.get("/{business_id}/services", response_model=list[ServiceOut])
def list_public_services(business_id: int, target_currency: Optional[str] = None, db: Session = Depends(get_db)):
    """
    With target_currency, each service's price is also converted from the
    business's own currency and returned as converted_price - lets a
    customer browsing in a different currency see roughly what they'd pay.
    """
    business = _get_approved_business_or_404(business_id, db)
    target = _normalize_target_currency(target_currency)

    services = db.query(Service).filter(Service.business_id == business_id, Service.is_active.is_(True)).all()
    results = [ServiceOut.model_validate(s) for s in services]
    if target is not None:
        for service, out in zip(services, results):
            out.converted_price = convert_amount(service.price, base=business.currency, target=target)
    return results


# ===========================================================================
# Staff
# ===========================================================================
@router.get("/me/staff", response_model=list[StaffOut])
def list_my_staff(
    current_business: Business = Depends(get_current_active_business),
    db: Session = Depends(get_db),
):
    return db.query(Staff).filter(Staff.business_id == current_business.id).all()


@router.post("/me/staff", response_model=StaffOut, status_code=status.HTTP_201_CREATED)
def create_my_staff(
    payload: StaffCreate,
    current_business: Business = Depends(get_current_active_business),
    db: Session = Depends(get_db),
):
    staff = Staff(business_id=current_business.id, **payload.model_dump())
    db.add(staff)
    db.commit()
    db.refresh(staff)
    return staff


@router.patch("/me/staff/{staff_id}", response_model=StaffOut)
def update_my_staff(
    staff_id: int,
    payload: StaffUpdate,
    current_business: Business = Depends(get_current_active_business),
    db: Session = Depends(get_db),
):
    staff = db.query(Staff).filter(Staff.id == staff_id, Staff.business_id == current_business.id).first()
    if staff is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Staff member not found.")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(staff, field, value)
    db.commit()
    db.refresh(staff)
    return staff


@router.delete("/me/staff/{staff_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_my_staff(
    staff_id: int,
    current_business: Business = Depends(get_current_active_business),
    db: Session = Depends(get_db),
):
    staff = db.query(Staff).filter(Staff.id == staff_id, Staff.business_id == current_business.id).first()
    if staff is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Staff member not found.")
    staff.is_active = False
    db.commit()


@router.get("/{business_id}/staff", response_model=list[StaffOut])
def list_public_staff(business_id: int, db: Session = Depends(get_db)):
    _get_approved_business_or_404(business_id, db)
    return db.query(Staff).filter(Staff.business_id == business_id, Staff.is_active.is_(True)).all()


# ===========================================================================
# Space Inventory
# ===========================================================================
@router.get("/me/inventory", response_model=list[SpaceInventoryOut])
def list_my_inventory(
    current_business: Business = Depends(get_current_active_business),
    db: Session = Depends(get_db),
):
    return db.query(SpaceInventory).filter(SpaceInventory.business_id == current_business.id).all()


@router.post("/me/inventory", response_model=SpaceInventoryOut, status_code=status.HTTP_201_CREATED)
def create_my_inventory(
    payload: SpaceInventoryCreate,
    current_business: Business = Depends(get_current_active_business),
    db: Session = Depends(get_db),
):
    inventory = SpaceInventory(business_id=current_business.id, **payload.model_dump())
    db.add(inventory)
    db.commit()
    db.refresh(inventory)
    return inventory


@router.patch("/me/inventory/{inventory_id}", response_model=SpaceInventoryOut)
def update_my_inventory(
    inventory_id: int,
    payload: SpaceInventoryUpdate,
    current_business: Business = Depends(get_current_active_business),
    db: Session = Depends(get_db),
):
    inventory = (
        db.query(SpaceInventory)
        .filter(SpaceInventory.id == inventory_id, SpaceInventory.business_id == current_business.id)
        .first()
    )
    if inventory is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Inventory item not found.")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(inventory, field, value)
    db.commit()
    db.refresh(inventory)
    return inventory


@router.delete("/me/inventory/{inventory_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_my_inventory(
    inventory_id: int,
    current_business: Business = Depends(get_current_active_business),
    db: Session = Depends(get_db),
):
    inventory = (
        db.query(SpaceInventory)
        .filter(SpaceInventory.id == inventory_id, SpaceInventory.business_id == current_business.id)
        .first()
    )
    if inventory is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Inventory item not found.")
    inventory.is_active = False
    db.commit()


@router.get("/{business_id}/inventory", response_model=list[SpaceInventoryOut])
def list_public_inventory(
    business_id: int,
    start_datetime: Optional[datetime] = None,
    end_datetime: Optional[datetime] = None,
    target_currency: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    With start_datetime/end_datetime (both required together - a Hotel
    Details page uses this once the customer has picked check-in/check-out
    dates), each item's available_quantity is filled in so the frontend can
    filter out or label a room type that's already fully booked for that
    window, rather than only finding out via a 409 on submit.

    With target_currency, each item's price is also converted from the
    business's own currency and returned as converted_price.
    """
    business = _get_approved_business_or_404(business_id, db)
    target = _normalize_target_currency(target_currency)

    if (start_datetime is None) != (end_datetime is None):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "start_datetime and end_datetime must be given together.")
    if start_datetime is not None:
        if start_datetime.tzinfo is None or end_datetime.tzinfo is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "start_datetime and end_datetime must include a UTC offset."
            )
        if end_datetime <= start_datetime:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "end_datetime must be after start_datetime.")

    items = (
        db.query(SpaceInventory)
        .filter(SpaceInventory.business_id == business_id, SpaceInventory.is_active.is_(True))
        .all()
    )
    results = [SpaceInventoryOut.model_validate(item) for item in items]
    for item, out in zip(items, results):
        if start_datetime is not None:
            out.available_quantity = available_units(
                db, space_inventory=item, start_datetime=start_datetime, end_datetime=end_datetime
            )
            out.dynamic_price = calculate_resource_dynamic_price(
                db, space_inventory=item, start_datetime=start_datetime, end_datetime=end_datetime
            )
        if target is not None:
            # Convert whichever price the customer would actually pay - the
            # real-time dynamic price when one was computed, else the flat rate.
            effective_price = out.dynamic_price if out.dynamic_price is not None else item.price
            out.converted_price = convert_amount(effective_price, base=business.currency, target=target)
    return results
