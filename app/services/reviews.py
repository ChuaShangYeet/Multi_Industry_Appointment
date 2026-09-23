"""Keeps Business.average_rating/rating_count in sync with the real Review rows."""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.business import Business
from app.models.review import Review


def recompute_business_rating(db: Session, business_id: int) -> None:
    """
    Recomputes Business.average_rating/rating_count from every Review row
    for this business - called after each review is written so the
    denormalized cache on Business never drifts from its real source of
    truth. Does not commit; the caller does that alongside its own write.
    """
    avg_rating, count = db.execute(
        select(func.avg(Review.rating), func.count(Review.id)).where(Review.business_id == business_id)
    ).one()
    business = db.get(Business, business_id)
    business.average_rating = round(avg_rating, 2) if avg_rating is not None else 0.0
    business.rating_count = count or 0
