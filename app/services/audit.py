"""Admin audit logging helper (PART 1.1 / PART 3) - every override goes through here."""
from typing import Optional

from sqlalchemy.orm import Session

from app.enums import AdminActionType, AdminTargetEntity
from app.models.admin import AdminAuditLog


def log_admin_action(
    db: Session,
    *,
    admin_id: int,
    action_type: AdminActionType,
    target_entity: AdminTargetEntity,
    target_id: int,
    notes: Optional[str] = None,
) -> AdminAuditLog:
    entry = AdminAuditLog(
        admin_id=admin_id,
        action_type=action_type,
        target_entity=target_entity,
        target_id=target_id,
        notes=notes,
    )
    db.add(entry)
    return entry
