"""
Import every model module here so that:
  1. `Base.metadata.create_all()` (used by tests and first-run dev setup)
     knows about all tables.
  2. Alembic's autogenerate can see the full schema.
  3. Relationship string references (e.g. Mapped["Business"]) resolve.
"""
from app.models.admin import AdminAuditLog, AdminUser  # noqa: F401
from app.models.appointment import Appointment  # noqa: F401
from app.models.business import Business  # noqa: F401
from app.models.details import (  # noqa: F401
    CarServiceDetails,
    GeneralServiceDetails,
    HotelDetails,
    HotelRoomItem,
    RestaurantDetails,
)
from app.models.resource import Service, SpaceInventory, Staff  # noqa: F401
from app.models.review import Review  # noqa: F401
from app.models.user import User  # noqa: F401

__all__ = [
    "AdminUser",
    "AdminAuditLog",
    "User",
    "Business",
    "Service",
    "Staff",
    "SpaceInventory",
    "Appointment",
    "RestaurantDetails",
    "HotelDetails",
    "HotelRoomItem",
    "CarServiceDetails",
    "GeneralServiceDetails",
    "Review",
]
