"""
Single-tenant deployment support (Path 2: one dedicated backend instance
per client - see app.config.Settings.SINGLE_TENANT_MODE). Everything a
multi-tenant route reaches via a `business_id` path/query param, the
single-tenant convenience routes (app.routers.business_context) reach via
this module instead.
"""
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.business import Business


def get_the_tenant_business(db: Session) -> Business:
    """
    The one Business row this deployment exists for. Single-tenant mode
    means exactly one Business is ever created per instance/database (see
    app.bootstrap_tenant, and business self-registration being disabled in
    this mode - app.routers.auth), so "the business" needs no id/slug
    lookup, just the only row in the table. Deterministic (oldest first) in
    case that invariant is ever violated by direct DB access.

    503, not 404: an empty result here means this instance hasn't been
    provisioned yet, which is a deployment/operator problem, not something
    a client request did wrong.
    """
    business = db.query(Business).order_by(Business.id.asc()).first()
    if business is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "This instance has not been provisioned yet - run `python -m app.bootstrap_tenant`.",
        )
    return business
