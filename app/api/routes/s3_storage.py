import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from sqlalchemy.orm import Session
from app.api.deps import get_current_user, get_db
from app.schemas.auth import UserRead
from app.services.s3_service import S3Service

# 참고: 파일 다운로드(Presigned URL 발급) 기능은 보안 정책에 따라 제거되었습니다.

router = APIRouter(prefix="/s3", tags=["s3"])
logger = logging.getLogger(__name__)


@router.get("/browse")
def browse_s3(
    prefix: str = Query(default="", description="S3 경로 prefix (예: data/models/)"),
    _: UserRead = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """S3 버켓 파일/폴더 목록 조회"""
    try:
        svc = S3Service(db=db)
        return svc.browse(prefix)
    except ConnectionError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    except Exception as e:
        logger.error(f"S3 browse error: {e}")
        raise HTTPException(status_code=500, detail=f"S3 오류: {e}") from e
