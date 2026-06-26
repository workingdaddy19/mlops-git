"""시스템 설정 초기 seed 데이터 삽입."""
import logging

from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app.models.system_settings import SETTINGS_SEED, SystemSetting

logger = logging.getLogger(__name__)

# 제거된 기능의 잔존 설정 키 — 기동 시 DB에서 정리(Settings 화면 탭 제거)
_OBSOLETE_KEYS = ("AIRFLOW_BASE_URL", "AIRFLOW_USERNAME", "AIRFLOW_PASSWORD")


def ensure_default_settings(engine: Engine) -> None:
    """system_settings 테이블에 seed 데이터 삽입 + 폐기된 키 정리."""
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = SessionLocal()
    try:
        for item in SETTINGS_SEED:
            existing = session.get(SystemSetting, item["key"])
            if existing is None:
                session.add(SystemSetting(**item))
                logger.info("settings seed: inserted key=%s", item["key"])
        for key in _OBSOLETE_KEYS:
            row = session.get(SystemSetting, key)
            if row is not None:
                session.delete(row)
                logger.info("settings prune: removed obsolete key=%s", key)
        session.commit()
    except Exception as exc:
        logger.error("settings seed error: %s", exc)
        session.rollback()
    finally:
        session.close()
