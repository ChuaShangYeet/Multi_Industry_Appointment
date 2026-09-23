"""
Password hashing and JWT issuance/verification.

The rest of the app (routers, dependencies) never touches `jose` or
`passlib` directly - it goes through the functions here.
"""
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class Role(str, Enum):
    CUSTOMER = "customer"
    BUSINESS = "business"
    ADMIN = "admin"


def hash_password(plain_password: str) -> str:
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    return pwd_context.verify(plain_password, password_hash)


def create_access_token(*, subject_id: int, role: Role, extra_claims: Optional[dict[str, Any]] = None) -> str:
    """
    Issues a JWT whose payload identifies WHO (sub) and WHAT KIND of actor
    (role) is authenticated. Every protected endpoint's RBAC check is driven
    off the `role` claim - see app.dependencies.
    """
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload: dict[str, Any] = {
        "sub": str(subject_id),
        "role": role.value,
        "iat": now,
        "exp": expire,
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


class TokenPayload:
    def __init__(self, subject_id: int, role: Role, claims: dict[str, Any]):
        self.subject_id = subject_id
        self.role = role
        self.claims = claims


def decode_access_token(token: str) -> Optional[TokenPayload]:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        return None

    subject = payload.get("sub")
    role_value = payload.get("role")
    if subject is None or role_value not in {r.value for r in Role}:
        return None

    try:
        subject_id = int(subject)
    except (TypeError, ValueError):
        return None

    return TokenPayload(subject_id=subject_id, role=Role(role_value), claims=payload)
