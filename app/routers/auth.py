"""
Authentication endpoints for all three actor types (PART 2.2). Each actor
type has its own register/login pair since they check different login
gates and live in different tables - there is no single unified "users"
table an off-the-shelf auth library would assume.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.enums import AccountStatus
from app.models.admin import AdminUser
from app.models.business import Business
from app.models.user import User
from app.schemas.auth import BusinessRegisterRequest, CustomerRegisterRequest, LoginRequest, TokenResponse
from app.security import Role, create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Customer
# ---------------------------------------------------------------------------
@router.post("/customer/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register_customer(payload: CustomerRegisterRequest, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists.")

    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        first_name=payload.first_name,
        last_name=payload.last_name,
        phone_number=payload.phone_number,
        account_status=AccountStatus.ACTIVE,
        timezone=payload.timezone,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token(subject_id=user.id, role=Role.CUSTOMER)
    return TokenResponse(access_token=token, role=Role.CUSTOMER.value)


@router.post("/customer/login", response_model=TokenResponse)
def login_customer(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password.")

    # Login gate (PART 2.2): Suspended/Banned accounts are blocked outright.
    if user.account_status != AccountStatus.ACTIVE:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Account is {user.account_status.value}.")

    token = create_access_token(subject_id=user.id, role=Role.CUSTOMER)
    return TokenResponse(access_token=token, role=Role.CUSTOMER.value)


# ---------------------------------------------------------------------------
# Business
# ---------------------------------------------------------------------------
@router.post("/business/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register_business(payload: BusinessRegisterRequest, db: Session = Depends(get_db)):
    """
    Self-registration always starts as Pending (PART 1.2 / PART 3.2) - an
    admin must approve it before the business can use core features. A
    token is still issued so the business can log in and check its status.
    """
    if db.query(Business).filter(Business.email == payload.email).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists.")

    business = Business(
        email=payload.email,
        password_hash=hash_password(payload.password),
        business_name=payload.business_name,
        category=payload.category,
        description=payload.description,
        address=payload.address,
        city=payload.city,
        phone_number=payload.phone_number,
        timezone=payload.timezone,
        currency=payload.currency,
    )
    db.add(business)
    db.commit()
    db.refresh(business)

    token = create_access_token(subject_id=business.id, role=Role.BUSINESS)
    return TokenResponse(access_token=token, role=Role.BUSINESS.value)


@router.post("/business/login", response_model=TokenResponse)
def login_business(payload: LoginRequest, db: Session = Depends(get_db)):
    business = db.query(Business).filter(Business.email == payload.email).first()
    if business is None or not verify_password(payload.password, business.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password.")

    # Note: login itself succeeds regardless of approval_status so a Pending
    # business can see its own status; core features are gated separately by
    # get_current_active_business (Approved only) on the routes that need it.
    token = create_access_token(subject_id=business.id, role=Role.BUSINESS)
    return TokenResponse(access_token=token, role=Role.BUSINESS.value)


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------
@router.post("/admin/login", response_model=TokenResponse)
def login_admin(payload: LoginRequest, db: Session = Depends(get_db)):
    admin = db.query(AdminUser).filter(AdminUser.email == payload.email).first()
    if admin is None or not verify_password(payload.password, admin.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password.")

    token = create_access_token(subject_id=admin.id, role=Role.ADMIN, extra_claims={"role_level": admin.role_level.value})
    return TokenResponse(access_token=token, role=Role.ADMIN.value)
