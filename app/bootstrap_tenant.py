"""
One-off script that provisions the single Business a single-tenant
deployment serves (see app.config.Settings.SINGLE_TENANT_MODE) - creates it
directly as Approved, bypassing the marketplace review workflow, since
there is no marketplace to review it for. Run with:

    python -m app.bootstrap_tenant

Reads TENANT_BUSINESS_* from the environment (.env). Safe to re-run - it
no-ops if a business with that email already exists. Refuses to run when
SINGLE_TENANT_MODE is false, since that means this deployment is meant to
run the normal multi-tenant marketplace instead (use the public
POST /auth/business/register + admin approval flow there).
"""
import sys

import app.models  # noqa: F401 - ensure every table is registered on Base.metadata
from app.config import settings
from app.database import Base, SessionLocal, engine
from app.enums import BusinessApprovalStatus, BusinessCategory
from app.models.business import Business
from app.security import hash_password


def main() -> None:
    if not settings.SINGLE_TENANT_MODE:
        print("SINGLE_TENANT_MODE is false - set it to true in .env before running this script.")
        sys.exit(1)

    try:
        category = BusinessCategory(settings.TENANT_BUSINESS_CATEGORY)
    except ValueError:
        valid = ", ".join(c.value for c in BusinessCategory)
        print(f"TENANT_BUSINESS_CATEGORY '{settings.TENANT_BUSINESS_CATEGORY}' is not valid - must be one of: {valid}.")
        sys.exit(1)

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        existing = db.query(Business).filter(Business.email == settings.TENANT_BUSINESS_EMAIL).first()
        if existing:
            print(f"Business '{existing.email}' already exists (id={existing.id}). Nothing to do.")
            return

        business = Business(
            email=settings.TENANT_BUSINESS_EMAIL,
            password_hash=hash_password(settings.TENANT_BUSINESS_PASSWORD),
            business_name=settings.TENANT_BUSINESS_NAME,
            category=category,
            city=settings.TENANT_BUSINESS_CITY or None,
            timezone=settings.TENANT_BUSINESS_TIMEZONE,
            currency=settings.TENANT_BUSINESS_CURRENCY,
            # Approved immediately - single-tenant mode has no marketplace
            # review workflow to bypass around, this business IS the
            # deployment (see app.services.tenant.get_the_tenant_business).
            approval_status=BusinessApprovalStatus.APPROVED,
        )
        db.add(business)
        db.commit()
        print(f"Created and approved business '{business.email}' (id={business.id}).")
        print(f"Log in via POST {settings.API_V1_PREFIX}/auth/business/login to add services/staff/inventory.")
        print(f"Public convenience endpoints are live at {settings.API_V1_PREFIX}/business/{{profile,services,staff,inventory,slots}}.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
