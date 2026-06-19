from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.permission_request import PermissionRequest


class PermissionRequestRepository:
    def __init__(self, db: Session):
        self._db = db

    def create(self, req: PermissionRequest) -> PermissionRequest:
        self._db.add(req)
        self._db.commit()
        self._db.refresh(req)
        return req

    def get_by_id(self, req_id: int) -> PermissionRequest | None:
        return self._db.get(PermissionRequest, req_id)

    def list_by_user(self, user_id: int) -> list[PermissionRequest]:
        return (
            self._db.query(PermissionRequest)
            .filter(PermissionRequest.user_id == user_id)
            .order_by(PermissionRequest.id.desc())
            .all()
        )

    def list_all(self, status: str | None = None) -> list[PermissionRequest]:
        q = self._db.query(PermissionRequest)
        if status:
            q = q.filter(PermissionRequest.status == status)
        return q.order_by(PermissionRequest.id.desc()).all()

    def has_pending(self, user_id: int, feature: str) -> bool:
        return (
            self._db.query(PermissionRequest.id)
            .filter(
                PermissionRequest.user_id == user_id,
                PermissionRequest.feature == feature,
                PermissionRequest.status == "pending",
            )
            .first()
            is not None
        )

    def decide(self, req: PermissionRequest, status: str, decided_by: str) -> PermissionRequest:
        req.status = status
        req.decided_by = decided_by
        req.decided_at = datetime.now(timezone.utc)
        self._db.commit()
        self._db.refresh(req)
        return req
