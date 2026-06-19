from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

VALID_STATUSES = frozenset({"pending", "approved", "rejected"})


class PermissionRequest(Base):
    """사용자의 기능 권한 신청. admin이 승인/거부한다.

    승인 시 user_feature_permissions 에 해당 feature 가 부여된다.
    username 은 admin 목록 조회 시 사용자 식별을 위해 비정규화 저장한다.
    """

    __tablename__ = "permission_requests"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    username: Mapped[str] = mapped_column(String(50), nullable=False)
    feature: Mapped[str] = mapped_column(String(50), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[str | None] = mapped_column(String(50))
