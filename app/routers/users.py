"""Customer self-service profile endpoints."""
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_customer
from app.models.user import User
from app.schemas.user import GoogleCalendarTokenIn, UserOut, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserOut)
def read_my_profile(current_user: User = Depends(get_current_customer)):
    return UserOut.from_model(current_user)


@router.patch("/me", response_model=UserOut)
def update_my_profile(
    payload: UserUpdate,
    current_user: User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(current_user, field, value)
    db.commit()
    db.refresh(current_user)
    return UserOut.from_model(current_user)


@router.put("/me/google-calendar", response_model=UserOut)
def link_google_calendar(
    payload: GoogleCalendarTokenIn,
    current_user: User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    """
    Stores the OAuth token the frontend obtained from Google's consent
    screen - the backend never runs that redirect flow itself.
    """
    current_user.google_calendar_token = payload.token
    db.commit()
    db.refresh(current_user)
    return UserOut.from_model(current_user)


@router.delete("/me/google-calendar", response_model=UserOut, status_code=status.HTTP_200_OK)
def unlink_google_calendar(
    current_user: User = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    current_user.google_calendar_token = None
    db.commit()
    db.refresh(current_user)
    return UserOut.from_model(current_user)
