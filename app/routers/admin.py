"""
Admin CRUD & governance (PART 3, PART 6). Every state-changing action here
writes an Admin_Audit_Log row - see app.services.audit.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.dependencies import get_current_admin, require_admin_role
from app.enums import (
    AccountStatus,
    AdminActionType,
    AdminRoleLevel,
    AdminTargetEntity,
    AppointmentStatus,
    BusinessApprovalStatus,
    BusinessCategory,
)
from app.models.admin import AdminAuditLog, AdminUser
from app.models.appointment import Appointment
from app.models.business import Business
from app.models.resource import Service, SpaceInventory, Staff
from app.models.user import User
from app.schemas.admin import (
    AuditLogOut,
    BusinessAdminDetailOut,
    BusinessAdminPasswordReset,
    BusinessListItemOut,
    CustomerAdminDetailOut,
    CustomerAdminUpdate,
    CustomerListItemOut,
    DashboardMetrics,
    InventoryAdjustRequest,
    ModerateContentRequest,
)
from app.schemas.appointment import AppointmentOut, ForceCancelRequest
from app.schemas.business import BusinessAdminOut, BusinessAdminUpdate
from app.schemas.common import Page
from app.schemas.user import UserOut
from app.security import hash_password
from app.services import analytics, google_calendar, state_machine
from app.services.audit import log_admin_action
from app.services.state_machine import InvalidTransitionError

router = APIRouter(prefix="/admin", tags=["admin"])

_MANAGE_ROLES = require_admin_role(AdminRoleLevel.SUPPORT_STAFF)
_MODERATE_ROLES = require_admin_role(AdminRoleLevel.SUPPORT_STAFF, AdminRoleLevel.CONTENT_MODERATOR)


@router.get("/me", response_model=dict)
def read_my_admin_profile(current_admin: AdminUser = Depends(get_current_admin)):
    return {
        "id": current_admin.id,
        "email": current_admin.email,
        "role_level": current_admin.role_level.value,
    }


# ---------------------------------------------------------------------------
# Dashboard (PART 6.2)
# ---------------------------------------------------------------------------
@router.get("/dashboard", response_model=DashboardMetrics)
def dashboard_metrics(
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
):
    window_start, window_end = analytics.activity_window()
    return DashboardMetrics(
        total_customers=analytics.total_customers(db),
        active_customers=analytics.active_customers(db),
        total_businesses=analytics.total_businesses(db),
        active_businesses=analytics.active_businesses(db),
        window_start=window_start,
        window_end=window_end,
    )


# ---------------------------------------------------------------------------
# Customers (PART 3.1, PART 6.3)
# ---------------------------------------------------------------------------
@router.get("/customers", response_model=Page[CustomerListItemOut])
def list_customers(
    search: Optional[str] = Query(None, description="Matches name or email"),
    account_status: Optional[AccountStatus] = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
):
    query = db.query(User)
    if search:
        like = f"%{search}%"
        query = query.filter(
            or_(User.email.ilike(like), User.first_name.ilike(like), User.last_name.ilike(like))
        )
    if account_status is not None:
        query = query.filter(User.account_status == account_status)

    total = query.count()
    items = query.order_by(User.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return Page[CustomerListItemOut](items=items, total=total, page=page, page_size=page_size)


@router.get("/customers/{user_id}", response_model=CustomerAdminDetailOut)
def get_customer_detail(user_id: int, db: Session = Depends(get_db), _admin: AdminUser = Depends(get_current_admin)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Customer not found.")
    appointments = (
        db.query(Appointment)
        .options(
            joinedload(Appointment.business),
            joinedload(Appointment.service),
            joinedload(Appointment.staff),
            joinedload(Appointment.space_inventory),
            joinedload(Appointment.restaurant_details),
            joinedload(Appointment.hotel_details),
            joinedload(Appointment.car_service_details),
            joinedload(Appointment.general_service_details),
        )
        .filter(Appointment.user_id == user_id)
        .order_by(Appointment.start_datetime.desc())
        .all()
    )
    return CustomerAdminDetailOut(
        user=UserOut.from_model(user),
        appointments=[AppointmentOut.from_model(a) for a in appointments],
    )


@router.patch("/customers/{user_id}", response_model=UserOut)
def update_customer(
    user_id: int,
    payload: CustomerAdminUpdate,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(_MANAGE_ROLES),
):
    """PART 3.1 Update: password resets, email updates, clearing corrupted OAuth tokens, status changes."""
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Customer not found.")

    changes = payload.model_dump(exclude_unset=True, exclude={"new_password", "clear_google_calendar_token"})
    for field, value in changes.items():
        setattr(user, field, value)

    if payload.new_password:
        user.password_hash = hash_password(payload.new_password)
        log_admin_action(
            db,
            admin_id=admin.id,
            action_type=AdminActionType.RESET_USER_PASSWORD,
            target_entity=AdminTargetEntity.USER,
            target_id=user.id,
        )

    if payload.clear_google_calendar_token:
        user.google_calendar_token = None

    if payload.account_status is not None:
        action = (
            AdminActionType.BAN_USER
            if payload.account_status == AccountStatus.BANNED
            else AdminActionType.SUSPEND_USER
            if payload.account_status == AccountStatus.SUSPENDED
            else AdminActionType.UPDATE_USER
        )
        log_admin_action(db, admin_id=admin.id, action_type=action, target_entity=AdminTargetEntity.USER, target_id=user.id)
    elif changes:
        log_admin_action(
            db, admin_id=admin.id, action_type=AdminActionType.UPDATE_USER, target_entity=AdminTargetEntity.USER, target_id=user.id
        )

    db.commit()
    db.refresh(user)
    return UserOut.from_model(user)


@router.delete("/customers/{user_id}", response_model=UserOut)
def anonymize_customer(
    user_id: int,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(_MANAGE_ROLES),
):
    """
    PART 3.1 Delete: GDPR hard-delete = anonymize, never a physical row
    delete (appointment history referencing this user must survive).
    """
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Customer not found.")

    user.first_name = "Deleted"
    user.last_name = "User"
    user.email = f"deleted-user-{user.id}@anonymized.invalid"
    user.phone_number = None
    user.google_calendar_token = None
    user.password_hash = hash_password(hash_password(str(user.id)))  # unusable, unguessable
    user.account_status = AccountStatus.BANNED
    user.is_anonymized = True

    log_admin_action(
        db, admin_id=admin.id, action_type=AdminActionType.ANONYMIZE_USER, target_entity=AdminTargetEntity.USER, target_id=user.id
    )
    db.commit()
    db.refresh(user)
    return UserOut.from_model(user)


# ---------------------------------------------------------------------------
# Businesses (PART 3.2, PART 6.4)
# ---------------------------------------------------------------------------
@router.get("/businesses", response_model=Page[BusinessListItemOut])
def list_businesses(
    search: Optional[str] = None,
    category: Optional[BusinessCategory] = None,
    approval_status: Optional[BusinessApprovalStatus] = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
):
    query = db.query(Business)
    if search:
        query = query.filter(Business.business_name.ilike(f"%{search}%"))
    if category is not None:
        query = query.filter(Business.category == category)
    if approval_status is not None:
        query = query.filter(Business.approval_status == approval_status)

    total = query.count()
    items = query.order_by(Business.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return Page[BusinessListItemOut](items=items, total=total, page=page, page_size=page_size)


@router.get("/businesses/{business_id}", response_model=BusinessAdminDetailOut)
def get_business_detail(business_id: int, db: Session = Depends(get_db), _admin: AdminUser = Depends(get_current_admin)):
    business = db.get(Business, business_id)
    if business is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Business not found.")

    _, window_end = analytics.activity_window()
    upcoming_confirmed = (
        db.query(Appointment)
        .filter(
            Appointment.business_id == business_id,
            Appointment.status == AppointmentStatus.CONFIRMED,
            Appointment.start_datetime <= window_end,
        )
        .count()
    )
    return BusinessAdminDetailOut(
        business=BusinessAdminOut.model_validate(business),
        total_services=db.query(Service).filter(Service.business_id == business_id).count(),
        total_staff=db.query(Staff).filter(Staff.business_id == business_id).count(),
        total_inventory_items=db.query(SpaceInventory).filter(SpaceInventory.business_id == business_id).count(),
        total_appointments=db.query(Appointment).filter(Appointment.business_id == business_id).count(),
        upcoming_confirmed_appointments=upcoming_confirmed,
    )


@router.patch("/businesses/{business_id}", response_model=BusinessAdminOut)
def update_business(
    business_id: int,
    payload: BusinessAdminUpdate,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(_MANAGE_ROLES),
):
    """PART 3.2: approve/reject Pending self-registrations, fix hours, re-categorize, suspend, etc."""
    business = db.get(Business, business_id)
    if business is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Business not found.")

    changes = payload.model_dump(exclude_unset=True)
    new_status = changes.pop("approval_status", None)
    for field, value in changes.items():
        setattr(business, field, value)

    if new_status is not None and new_status != business.approval_status:
        business.approval_status = new_status
        action = {
            BusinessApprovalStatus.APPROVED: AdminActionType.APPROVE_BUSINESS,
            BusinessApprovalStatus.REJECTED: AdminActionType.REJECT_BUSINESS,
            BusinessApprovalStatus.SUSPENDED: AdminActionType.SUSPEND_BUSINESS,
            BusinessApprovalStatus.PENDING: AdminActionType.UPDATE_BUSINESS,
        }[new_status]
        log_admin_action(
            db, admin_id=admin.id, action_type=action, target_entity=AdminTargetEntity.BUSINESS, target_id=business.id
        )
    elif changes:
        log_admin_action(
            db,
            admin_id=admin.id,
            action_type=AdminActionType.UPDATE_BUSINESS,
            target_entity=AdminTargetEntity.BUSINESS,
            target_id=business.id,
        )

    db.commit()
    db.refresh(business)
    return BusinessAdminOut.model_validate(business)


@router.post("/businesses/{business_id}/reset-password", response_model=BusinessAdminOut)
def reset_business_password(
    business_id: int,
    payload: BusinessAdminPasswordReset,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(_MANAGE_ROLES),
):
    business = db.get(Business, business_id)
    if business is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Business not found.")
    business.password_hash = hash_password(payload.new_password)
    log_admin_action(
        db,
        admin_id=admin.id,
        action_type=AdminActionType.RESET_BUSINESS_PASSWORD,
        target_entity=AdminTargetEntity.BUSINESS,
        target_id=business.id,
    )
    db.commit()
    db.refresh(business)
    return BusinessAdminOut.model_validate(business)


# ---------------------------------------------------------------------------
# Workflow interventions / overrides (PART 3.3)
# ---------------------------------------------------------------------------
@router.post("/appointments/{appointment_id}/force-cancel", response_model=AppointmentOut)
def force_cancel_appointment(
    appointment_id: int,
    payload: ForceCancelRequest,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(_MANAGE_ROLES),
):
    appointment = (
        db.query(Appointment)
        .options(
            joinedload(Appointment.business),
            joinedload(Appointment.service),
            joinedload(Appointment.staff),
            joinedload(Appointment.space_inventory),
            joinedload(Appointment.user),
            joinedload(Appointment.restaurant_details),
            joinedload(Appointment.hotel_details),
            joinedload(Appointment.car_service_details),
            joinedload(Appointment.general_service_details),
        )
        .filter(Appointment.id == appointment_id)
        .first()
    )
    if appointment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Appointment not found.")

    try:
        state_machine.force_cancel(appointment, reason=payload.reason)
    except InvalidTransitionError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    log_admin_action(
        db,
        admin_id=admin.id,
        action_type=AdminActionType.FORCE_CANCEL_APPT,
        target_entity=AdminTargetEntity.APPOINTMENT,
        target_id=appointment.id,
        notes=payload.reason,
    )
    db.commit()
    db.refresh(appointment)
    # Triggers the background Google Calendar sync deletion, per Backend Architecture #6.
    google_calendar.sync_appointment_deleted(appointment)
    google_calendar.sync_appointment_updated(appointment)
    return AppointmentOut.from_model(appointment, include_user=True)


@router.patch("/inventory/{inventory_id}", response_model=dict)
def adjust_inventory(
    inventory_id: int,
    payload: InventoryAdjustRequest,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(_MANAGE_ROLES),
):
    inventory = db.get(SpaceInventory, inventory_id)
    if inventory is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Inventory item not found.")
    inventory.total_quantity = payload.total_quantity
    log_admin_action(
        db,
        admin_id=admin.id,
        action_type=AdminActionType.ADJUST_INVENTORY,
        target_entity=AdminTargetEntity.SPACE_INVENTORY,
        target_id=inventory.id,
        notes=payload.reason,
    )
    db.commit()
    db.refresh(inventory)
    return {"id": inventory.id, "total_quantity": inventory.total_quantity}


@router.patch("/services/{service_id}/moderate", response_model=dict)
def moderate_service(
    service_id: int,
    payload: ModerateContentRequest,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(_MODERATE_ROLES),
):
    service = db.get(Service, service_id)
    if service is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Service not found.")
    service.is_active = payload.is_active
    log_admin_action(
        db,
        admin_id=admin.id,
        action_type=AdminActionType.MODERATE_CONTENT,
        target_entity=AdminTargetEntity.SERVICE,
        target_id=service.id,
        notes=payload.reason,
    )
    db.commit()
    return {"id": service.id, "is_active": service.is_active}


@router.patch("/staff/{staff_id}/moderate", response_model=dict)
def moderate_staff(
    staff_id: int,
    payload: ModerateContentRequest,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(_MODERATE_ROLES),
):
    staff = db.get(Staff, staff_id)
    if staff is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Staff member not found.")
    staff.is_active = payload.is_active
    log_admin_action(
        db,
        admin_id=admin.id,
        action_type=AdminActionType.MODERATE_CONTENT,
        target_entity=AdminTargetEntity.STAFF,
        target_id=staff.id,
        notes=payload.reason,
    )
    db.commit()
    return {"id": staff.id, "is_active": staff.is_active}


# ---------------------------------------------------------------------------
# Audit log (PART 1.1)
# ---------------------------------------------------------------------------
@router.get("/audit-log", response_model=Page[AuditLogOut])
def list_audit_log(
    admin_id: Optional[int] = None,
    target_entity: Optional[AdminTargetEntity] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
):
    query = db.query(AdminAuditLog)
    if admin_id is not None:
        query = query.filter(AdminAuditLog.admin_id == admin_id)
    if target_entity is not None:
        query = query.filter(AdminAuditLog.target_entity == target_entity)

    total = query.count()
    items = query.order_by(AdminAuditLog.timestamp.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return Page[AuditLogOut](items=items, total=total, page=page, page_size=page_size)
