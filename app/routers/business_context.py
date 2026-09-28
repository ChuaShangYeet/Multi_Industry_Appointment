"""
Single-tenant convenience endpoints (Path 2 deployment - see
app.config.Settings.SINGLE_TENANT_MODE). Same public data as the
`/businesses/{business_id}/...` routes, auto-resolved to the one Business
this deployment serves via app.services.tenant, so a headless frontend
(e.g. a WordPress site) never needs to know or pass a business_id.

404s outright when SINGLE_TENANT_MODE is off - these routes don't apply to
a multi-tenant marketplace deployment of this same codebase, and resolving
"the" business would be meaningless (there could be any number of them).
"""
from datetime import date as date_type, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.enums import STAFF_BASED_CATEGORIES
from app.models.resource import Service
from app.routers.resources import list_inventory_for_business, list_services_for_business, list_staff_for_business
from app.schemas.business import BusinessPublicDetailOut
from app.schemas.resource import ServiceOut, SlotOut, SpaceInventoryOut, StaffOut
from app.services.availability import generate_staff_based_slots, resolve_appointment_type
from app.services.currency import normalize_target_currency
from app.services.tenant import get_the_tenant_business

router = APIRouter(prefix="/business", tags=["single-tenant"])


def _require_single_tenant_mode() -> None:
    if not settings.SINGLE_TENANT_MODE:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "This deployment is not running in single-tenant mode - use /businesses/{business_id}/... instead.",
        )


def _normalize_target_currency_or_422(target_currency: Optional[str]) -> Optional[str]:
    try:
        return normalize_target_currency(target_currency)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


@router.get("/profile", response_model=BusinessPublicDetailOut)
def get_tenant_profile(db: Session = Depends(get_db)):
    _require_single_tenant_mode()
    business = get_the_tenant_business(db)
    return BusinessPublicDetailOut.model_validate(business)


@router.get("/services", response_model=list[ServiceOut])
def get_tenant_services(target_currency: Optional[str] = None, db: Session = Depends(get_db)):
    _require_single_tenant_mode()
    business = get_the_tenant_business(db)
    target = _normalize_target_currency_or_422(target_currency)
    return list_services_for_business(db, business, target)


@router.get("/staff", response_model=list[StaffOut])
def get_tenant_staff(db: Session = Depends(get_db)):
    _require_single_tenant_mode()
    business = get_the_tenant_business(db)
    return list_staff_for_business(db, business)


@router.get("/inventory", response_model=list[SpaceInventoryOut])
def get_tenant_inventory(
    start_datetime: Optional[datetime] = None,
    end_datetime: Optional[datetime] = None,
    target_currency: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """See list_inventory_for_business - table/room capacity and (optionally) dynamic pricing for a date range."""
    _require_single_tenant_mode()
    business = get_the_tenant_business(db)
    target = _normalize_target_currency_or_422(target_currency)
    return list_inventory_for_business(db, business, start_datetime, end_datetime, target)


@router.get("/slots", response_model=list[SlotOut])
def get_tenant_slots(service_id: int, on_date: date_type, db: Session = Depends(get_db)):
    """
    Discrete bookable start times for one calendar day - staff-based
    business types (Salon/Spa/Car Service/Professional) only. Restaurant/
    Hotel capacity is a quantity over a date range, not a list of start
    times - use /business/inventory with start_datetime/end_datetime instead.
    """
    _require_single_tenant_mode()
    business = get_the_tenant_business(db)
    service = (
        db.query(Service)
        .filter(Service.id == service_id, Service.business_id == business.id, Service.is_active.is_(True))
        .first()
    )
    if service is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Service not found.")

    if resolve_appointment_type(business.category) not in STAFF_BASED_CATEGORIES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This business type doesn't have discrete slots - use /business/inventory with a date range instead.",
        )

    slots = generate_staff_based_slots(db, business=business, service=service, on_date=on_date)
    return [SlotOut(start_datetime=start, available=available) for start, available in slots]
