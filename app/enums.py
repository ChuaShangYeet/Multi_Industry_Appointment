"""
All Enum types used across the schema, in one place so status values used in
comparisons/business logic (e.g. "Confirmed", "Approved") never drift from
what's stored in the DB columns.
"""
import enum


class AdminRoleLevel(str, enum.Enum):
    SUPER_ADMIN = "SuperAdmin"
    SUPPORT_STAFF = "SupportStaff"
    CONTENT_MODERATOR = "ContentModerator"


class AdminActionType(str, enum.Enum):
    UPDATE_USER = "UPDATE_USER"
    RESET_USER_PASSWORD = "RESET_USER_PASSWORD"
    SUSPEND_USER = "SUSPEND_USER"
    BAN_USER = "BAN_USER"
    ANONYMIZE_USER = "ANONYMIZE_USER"
    APPROVE_BUSINESS = "APPROVE_BUSINESS"
    REJECT_BUSINESS = "REJECT_BUSINESS"
    SUSPEND_BUSINESS = "SUSPEND_BUSINESS"
    UPDATE_BUSINESS = "UPDATE_BUSINESS"
    RESET_BUSINESS_PASSWORD = "RESET_BUSINESS_PASSWORD"
    FORCE_CANCEL_APPT = "FORCE_CANCEL_APPT"
    ADJUST_INVENTORY = "ADJUST_INVENTORY"
    MODERATE_CONTENT = "MODERATE_CONTENT"


class AdminTargetEntity(str, enum.Enum):
    USER = "User"
    BUSINESS = "Business"
    APPOINTMENT = "Appointment"
    STAFF = "Staff"
    SERVICE = "Service"
    SPACE_INVENTORY = "Space_Inventory"


class AccountStatus(str, enum.Enum):
    ACTIVE = "Active"
    SUSPENDED = "Suspended"
    BANNED = "Banned"


class BusinessApprovalStatus(str, enum.Enum):
    PENDING = "Pending"
    APPROVED = "Approved"
    REJECTED = "Rejected"
    SUSPENDED = "Suspended"


class BusinessCategory(str, enum.Enum):
    RESTAURANT = "Restaurant"
    HOTEL = "Hotel"
    SPA = "Spa"
    CAR_SERVICE = "Car Service"
    PROFESSIONAL = "Professional"
    SALON = "Salon"


class AppointmentType(str, enum.Enum):
    RESTAURANT = "Restaurant"
    HOTEL = "Hotel"
    SALON = "Salon"
    SPA = "Spa"
    CAR = "Car"
    PROFESSIONAL = "Professional"


class AppointmentStatus(str, enum.Enum):
    PENDING = "Pending"
    CONFIRMED = "Confirmed"
    CANCELLED = "Cancelled"
    COMPLETED = "Completed"


class TablePreference(str, enum.Enum):
    INDOOR = "Indoor"
    OUTDOOR = "Outdoor"
    WINDOW = "Window"


class SpaceInventoryType(str, enum.Enum):
    HOTEL_ROOM = "Hotel Room"
    RESTAURANT_TABLE = "Restaurant Table"
    OTHER = "Other"


# Business categories whose appointments are matched against Staff
# availability rather than Space_Inventory availability.
STAFF_BASED_CATEGORIES = {
    AppointmentType.SALON,
    AppointmentType.SPA,
    AppointmentType.CAR,
    AppointmentType.PROFESSIONAL,
}

# Business categories matched against Space_Inventory (rooms/tables) instead.
SPACE_BASED_CATEGORIES = {
    AppointmentType.RESTAURANT,
    AppointmentType.HOTEL,
}

# Appointment states that still hold a claim on a resource (staff slot or
# inventory unit). Used everywhere "overlapping active appointments" is
# counted for availability checks.
ACTIVE_APPOINTMENT_STATUSES = {AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED}

# Google Calendar colorId mapping per PART 5 of the spec.
GOOGLE_CALENDAR_COLOR_ID = {
    AppointmentStatus.PENDING: "5",  # Yellow
    AppointmentStatus.CONFIRMED: "2",  # Green
    AppointmentStatus.CANCELLED: "11",  # Red
    AppointmentStatus.COMPLETED: "2",  # Keep green once completed
}
