from sqlalchemy.orm import Session

from app.models.user_permission import UserFeaturePermission, VALID_FEATURES


class UserPermissionRepository:
    def __init__(self, db: Session):
        self._db = db

    def get_by_user(self, user_id: int) -> list[str]:
        rows = (
            self._db.query(UserFeaturePermission.feature)
            .filter(UserFeaturePermission.user_id == user_id)
            .all()
        )
        return [r.feature for r in rows]

    def set_permissions(self, user_id: int, features: list[str]) -> list[str]:
        valid = [f for f in features if f in VALID_FEATURES]
        self._db.query(UserFeaturePermission).filter(
            UserFeaturePermission.user_id == user_id
        ).delete()
        for feature in valid:
            self._db.add(UserFeaturePermission(user_id=user_id, feature=feature))
        self._db.commit()
        return valid

    def add_permission(self, user_id: int, feature: str) -> bool:
        """단일 기능 권한 부여 (기존 권한 유지). 이미 있으면 False."""
        if feature not in VALID_FEATURES:
            raise ValueError(f"유효하지 않은 기능: {feature}")
        exists = (
            self._db.query(UserFeaturePermission.id)
            .filter(
                UserFeaturePermission.user_id == user_id,
                UserFeaturePermission.feature == feature,
            )
            .first()
        )
        if exists:
            return False
        self._db.add(UserFeaturePermission(user_id=user_id, feature=feature))
        self._db.commit()
        return True
