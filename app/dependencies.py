"""
FastAPI dependencies: DB session (re-exported from app.database for
convenience) and the RBAC/auth gateway described in PART 2.2 of the spec.

Every protected route depends on one of the `get_current_*` functions below,
which decode the JWT, load the corresponding row, and enforce the relevant
"login gate" (Active / Approved) before the route body ever runs.
"""
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.database import get_db  # noqa: F401  (re-exported)
from app.enums import AccountStatus, AdminRoleLevel, BusinessApprovalStatus
from app.models.admin import AdminUser
from app.models.business import Business
from app.models.user import User
from app.security import Role, TokenPayload, decode_access_token

bearer_scheme = HTTPBearer(auto_error=False)


def _decode_or_401(credentials: Optional[HTTPAuthorizationCredentials]) -> TokenPayload:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    payload = decode_access_token(credentials.credentials)
    if payload is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    return payload


def get_token_payload(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> TokenPayload:
    return _decode_or_401(credentials)


# --------------------------------------------------------------------------
# Customer
# --------------------------------------------------------------------------
def get_current_customer(
    payload: TokenPayload = Depends(get_token_payload),
    db: Session = Depends(get_db),
) -> User:
    if payload.role != Role.CUSTOMER:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Customer account required")
    user = db.get(User, payload.subject_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account not found")
    # Enforced again here (not just at login) so a user suspended mid-session
    # is immediately locked out of core features, per the spec's login gate.
    if user.account_status != AccountStatus.ACTIVE:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Account is {user.account_status.value}")
    return user


# --------------------------------------------------------------------------
# Business
# --------------------------------------------------------------------------
def get_current_business_account(
    payload: TokenPayload = Depends(get_token_payload),
    db: Session = Depends(get_db),
) -> Business:
    """Any authenticated business, regardless of approval status - used for
    endpoints a Pending business still needs (e.g. checking its own status)."""
    if payload.role != Role.BUSINESS:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Business account required")
    business = db.get(Business, payload.subject_id)
    if business is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account not found")
    return business


def get_current_active_business(business: Business = Depends(get_current_business_account)) -> Business:
    """Approved businesses only - gates core features (managing services,
    staff, inventory, and appointment actions), per PART 2.2 of the spec."""
    if business.approval_status != BusinessApprovalStatus.APPROVED:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Business is {business.approval_status.value}")
    return business


# --------------------------------------------------------------------------
# Admin
# --------------------------------------------------------------------------
def get_current_admin(
    payload: TokenPayload = Depends(get_token_payload),
    db: Session = Depends(get_db),
) -> AdminUser:
    if payload.role != Role.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin account required")
    admin = db.get(AdminUser, payload.subject_id)
    if admin is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account not found")
    return admin


def require_admin_role(*allowed_levels: AdminRoleLevel):
    """
    Dependency factory for finer-grained admin RBAC. SuperAdmin is always
    implicitly allowed (it's the top of the hierarchy); pass the other
    role(s) permitted for a given endpoint, e.g.:

        Depends(require_admin_role(AdminRoleLevel.SUPPORT_STAFF))
    """

    def _dependency(admin: AdminUser = Depends(get_current_admin)) -> AdminUser:
        if admin.role_level == AdminRoleLevel.SUPER_ADMIN:
            return admin
        if admin.role_level in allowed_levels:
            return admin
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient admin privileges for this action")

    return _dependency
