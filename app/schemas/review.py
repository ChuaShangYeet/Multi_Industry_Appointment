from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ReviewCreate(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: Optional[str] = Field(default=None, max_length=2000)


class ReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    appointment_id: int
    business_id: int
    rating: int
    comment: Optional[str]
    created_at: datetime
    # First name + last initial only (e.g. "Jane D.") - this is shown on a
    # public business page to anyone browsing, so the reviewer's full
    # identity (email, full last name) is never exposed here.
    reviewer_name: str

    @classmethod
    def from_model(cls, review) -> "ReviewOut":
        last_initial = f" {review.user.last_name[0]}." if review.user.last_name else ""
        return cls(
            id=review.id,
            appointment_id=review.appointment_id,
            business_id=review.business_id,
            rating=review.rating,
            comment=review.comment,
            created_at=review.created_at,
            reviewer_name=f"{review.user.first_name}{last_initial}",
        )
