"""
Business discovery (public, customer-facing gallery) and business
self-service profile endpoints (PART 2 step 2-3, PART 4.3, PART 5).
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.dependencies import get_current_business_account
from app.enums import BusinessApprovalStatus, BusinessCategory
from app.models.business import Business
from app.models.review import Review
from app.schemas.business import (
    BusinessCardOut,
    BusinessPublicDetailOut,
    BusinessSelfOut,
    BusinessUpdate,
    GoogleCalendarIdIn,
)
from app.schemas.common import Page
from app.schemas.review import ReviewOut

router = APIRouter(prefix="/businesses", tags=["businesses"])


@router.get("", response_model=Page[BusinessCardOut])
def discover_businesses(
    category: Optional[BusinessCategory] = None,
    search: Optional[str] = Query(None, description="Matches business name or city"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """
    Discovery Gallery (PART 4.3). Query Scoping (Backend Architecture #2):
    only Approved businesses are ever returned to the public, enforced here
    at the database level rather than trusted to the client.
    """
    query = db.query(Business).filter(Business.approval_status == BusinessApprovalStatus.APPROVED)
    if category is not None:
        query = query.filter(Business.category == category)
    if search:
        like = f"%{search}%"
        query = query.filter(or_(Business.business_name.ilike(like), Business.city.ilike(like)))

    total = query.count()
    items = (
        query.order_by(Business.average_rating.desc(), Business.business_name.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return Page[BusinessCardOut](
        items=[BusinessCardOut.model_validate(b) for b in items], total=total, page=page, page_size=page_size
    )


@router.get("/me", response_model=BusinessSelfOut)
def read_my_business(current_business: Business = Depends(get_current_business_account)):
    return BusinessSelfOut.model_validate(current_business)


@router.patch("/me", response_model=BusinessSelfOut)
def update_my_business(
    payload: BusinessUpdate,
    current_business: Business = Depends(get_current_business_account),
    db: Session = Depends(get_db),
):
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(current_business, field, value)
    db.commit()
    db.refresh(current_business)
    return BusinessSelfOut.model_validate(current_business)


@router.put("/me/google-calendar", response_model=BusinessSelfOut)
def set_business_google_calendar(
    payload: GoogleCalendarIdIn,
    current_business: Business = Depends(get_current_business_account),
    db: Session = Depends(get_db),
):
    current_business.google_calendar_id = payload.google_calendar_id
    db.commit()
    db.refresh(current_business)
    return BusinessSelfOut.model_validate(current_business)


@router.get("/{business_id}", response_model=BusinessPublicDetailOut)
def get_business_detail(business_id: int, db: Session = Depends(get_db)):
    """Business Details page (PART 4.3) - public, Approved businesses only."""
    business = (
        db.query(Business)
        .filter(Business.id == business_id, Business.approval_status == BusinessApprovalStatus.APPROVED)
        .first()
    )
    if business is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Business not found.")
    return BusinessPublicDetailOut.model_validate(business)


@router.get("/{business_id}/reviews", response_model=Page[ReviewOut])
def list_business_reviews(
    business_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Public - the real reviews behind a business's average_rating/rating_count (see app.services.reviews)."""
    business = (
        db.query(Business)
        .filter(Business.id == business_id, Business.approval_status == BusinessApprovalStatus.APPROVED)
        .first()
    )
    if business is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Business not found.")

    query = db.query(Review).options(joinedload(Review.user)).filter(Review.business_id == business_id)
    total = query.count()
    items = query.order_by(Review.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return Page[ReviewOut](
        items=[ReviewOut.from_model(r) for r in items], total=total, page=page, page_size=page_size
    )
