from datetime import datetime
from typing import Optional

from sqlalchemy import Enum, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.db_types import UTCDateTime
from app.enums import AdminActionType, AdminRoleLevel, AdminTargetEntity
from app.models.mixins import TimestampMixin


class AdminUser(Base, TimestampMixin):
    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    first_name: Mapped[Optional[str]] = mapped_column(String(100))
    last_name: Mapped[Optional[str]] = mapped_column(String(100))
    role_level: Mapped[AdminRoleLevel] = mapped_column(
        Enum(AdminRoleLevel, native_enum=False, length=32), nullable=False, default=AdminRoleLevel.SUPPORT_STAFF
    )

    audit_logs: Mapped[list["AdminAuditLog"]] = relationship(back_populates="admin")


class AdminAuditLog(Base):
    """
    Append-only trail of every administrative override. Never updated or
    deleted - this is the record that answers "who changed this and when".
    """

    __tablename__ = "admin_audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    admin_id: Mapped[int] = mapped_column(ForeignKey("admin_users.id"), nullable=False, index=True)
    action_type: Mapped[AdminActionType] = mapped_column(Enum(AdminActionType, native_enum=False, length=64))
    target_entity: Mapped[AdminTargetEntity] = mapped_column(Enum(AdminTargetEntity, native_enum=False, length=32))
    target_id: Mapped[int] = mapped_column(Integer, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(String(1000))
    timestamp: Mapped[datetime] = mapped_column(UTCDateTime, server_default=func.now())

    admin: Mapped["AdminUser"] = relationship(back_populates="audit_logs")
