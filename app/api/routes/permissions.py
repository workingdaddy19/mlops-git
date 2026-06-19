"""기능 권한 신청/승인 API.

- 사용자(router): 권한 신청 + 본인 신청 내역 조회
- 관리자(admin_router): 신청 목록 조회 + 승인/거부 (승인 시 권한 자동 부여)
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, require_admin
from app.models.permission_request import PermissionRequest, VALID_STATUSES
from app.models.user_permission import VALID_FEATURES
from app.repositories.permission_request_repo import PermissionRequestRepository
from app.repositories.user_permission_repo import UserPermissionRepository
from app.schemas.auth import UserRead
from app.schemas.permission import PermissionRequestCreate, PermissionRequestRead

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/permissions", tags=["permissions"])
admin_router = APIRouter(prefix="/admin/permission-requests", tags=["admin-permissions"])


# ═══════════════════════════════════════════
# 사용자 — 권한 신청
# ═══════════════════════════════════════════

@router.post("/requests", response_model=PermissionRequestRead, status_code=201)
def create_request(
    body: PermissionRequestCreate,
    current_user: UserRead = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """기능 권한 신청 (대기 상태로 등록)."""
    if body.feature not in VALID_FEATURES:
        raise HTTPException(status_code=400, detail=f"유효하지 않은 기능: {body.feature}")

    if current_user.role == "admin":
        raise HTTPException(status_code=400, detail="관리자는 모든 기능이 이미 허용되어 신청이 필요 없습니다.")

    # 이미 보유한 권한인지 확인
    perm_repo = UserPermissionRepository(db)
    if body.feature in perm_repo.get_by_user(current_user.id):
        raise HTTPException(status_code=409, detail="이미 보유한 권한입니다.")

    req_repo = PermissionRequestRepository(db)
    if req_repo.has_pending(current_user.id, body.feature):
        raise HTTPException(status_code=409, detail="이미 대기 중인 신청이 있습니다.")

    req = req_repo.create(PermissionRequest(
        user_id=current_user.id,
        username=current_user.username,
        feature=body.feature,
        reason=body.reason,
        status="pending",
    ))
    logger.info("permission request created: user=%s feature=%s", current_user.username, body.feature)
    return PermissionRequestRead.model_validate(req)


@router.get("/requests/me", response_model=list[PermissionRequestRead])
def my_requests(
    current_user: UserRead = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """본인의 권한 신청 내역."""
    items = PermissionRequestRepository(db).list_by_user(current_user.id)
    return [PermissionRequestRead.model_validate(r) for r in items]


# ═══════════════════════════════════════════
# 관리자 — 신청 승인/거부
# ═══════════════════════════════════════════

@admin_router.get("", response_model=list[PermissionRequestRead])
def list_requests(
    status: str | None = Query(default=None, description="pending/approved/rejected 필터"),
    _admin: UserRead = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """전체 권한 신청 목록 (사용자 ID 포함) — admin only."""
    if status and status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"유효하지 않은 상태: {status}")
    items = PermissionRequestRepository(db).list_all(status)
    return [PermissionRequestRead.model_validate(r) for r in items]


@admin_router.post("/{req_id}/approve", response_model=PermissionRequestRead)
def approve_request(
    req_id: int,
    admin: UserRead = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """신청 승인 → 해당 기능 권한 부여 (admin only)."""
    req_repo = PermissionRequestRepository(db)
    req = req_repo.get_by_id(req_id)
    if not req:
        raise HTTPException(status_code=404, detail="신청을 찾을 수 없습니다.")
    if req.status != "pending":
        raise HTTPException(status_code=409, detail=f"이미 처리된 신청입니다. (상태: {req.status})")

    UserPermissionRepository(db).add_permission(req.user_id, req.feature)
    req = req_repo.decide(req, "approved", admin.username)
    logger.info("permission request approved: id=%s feature=%s by=%s", req_id, req.feature, admin.username)
    return PermissionRequestRead.model_validate(req)


@admin_router.post("/{req_id}/reject", response_model=PermissionRequestRead)
def reject_request(
    req_id: int,
    admin: UserRead = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """신청 거부 (admin only)."""
    req_repo = PermissionRequestRepository(db)
    req = req_repo.get_by_id(req_id)
    if not req:
        raise HTTPException(status_code=404, detail="신청을 찾을 수 없습니다.")
    if req.status != "pending":
        raise HTTPException(status_code=409, detail=f"이미 처리된 신청입니다. (상태: {req.status})")

    req = req_repo.decide(req, "rejected", admin.username)
    logger.info("permission request rejected: id=%s feature=%s by=%s", req_id, req.feature, admin.username)
    return PermissionRequestRead.model_validate(req)
