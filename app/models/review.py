from typing import Optional

from sqlalchemy import ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.mixins import TimestampMixin


class Review(Base, TimestampMixin):
    """
    A customer's rating/feedback on a Completed appointment.

    This is the real source behind Business.average_rating/rating_count -
    those two columns used to be hand-set seed data with no way for an
    actual customer to ever produce them (see app.seed_demo_data before this
    table existed). Now every write here recomputes them from the real rows
    (see app.services.reviews.recompute_business_rating) instead of leaving
    them to drift out of sync by hand.

    One review per appointment (appointment_id is unique) - a customer can
    only rate a visit/stay they actually completed, and only once, enforced
    both by the unique constraint here and by the appointments router only
    accepting a review for an appointment in AppointmentStatus.COMPLETED.
    """

    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    appointment_id: Mapped[int] = mapped_column(ForeignKey("appointments.id"), unique=True, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), nullable=False, index=True)

    rating: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-5, enforced by ReviewCreate
    comment: Mapped[Optional[str]] = mapped_column(Text)

    appointment: Mapped["Appointment"] = relationship(back_populates="review")
    user: Mapped["User"] = relationship()
    business: Mapped["Business"] = relationship()
