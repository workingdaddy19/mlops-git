"""JupyterHub API 라우트 — 토큰 발급 기반 자동 로그인."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.schemas.auth import UserRead
from app.services.jupyter_service import JupyterService

router = APIRouter(prefix="/jupyter", tags=["jupyter"])
logger = logging.getLogger(__name__)


class TokenRequest(BaseModel):
    server: str = ""
    size: str = ""        # 용량 타입 small/medium/large (JWT 클레임 jupyterhub_size로 전달)


@router.get("/envs")
async def get_jupyter_envs(
    current_user: UserRead = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Jupyter 환경 목록 반환 (토큰 미포함)."""
    svc = JupyterService(db=db)
    try:
        envs = await svc.get_user_envs()
        return {"username": current_user.username, "envs": envs}
    except Exception as e:
        logger.error("JupyterHub envs error: %s", e)
        raise HTTPException(status_code=502, detail=f"JupyterHub 연결 오류: {e}") from e


@router.get("/token")
async def get_jupyter_token(
    server: str = Query(default="", description="Named server 이름 (비워두면 기본 서버)"),
    size: str = Query(default="", description="용량 타입 small/medium/large → JWT 클레임 jupyterhub_size"),
    current_user: UserRead = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """버튼 클릭 → 토큰 발급 → 접속 URL 반환.

    응답:
      url          : 새 탭으로 열어야 할 JupyterLab URL (토큰 포함)
      token_issued : 토큰 발급 성공 여부 (false면 로그인 페이지로 이동될 수 있음)
      error        : 실패 사유 (성공 시 null)
      username     : 접속 대상 JupyterHub 사용자명
    """
    svc = JupyterService(db=db)
    try:
        result = await svc.get_token_url(current_user.username, server, size)
        logger.info(
            "token request  user=%-12s  server=%r  size=%r  token_issued=%s  url=%s",
            current_user.username, server or "(default)", size or "(none)",
            result["token_issued"], result["url"],
        )
        # JupyterHub 5.x: token_issued는 서버 자동시작 확인용.
        # 브라우저 접속은 항상 직접 lab URL로 이동 (세션 쿠키로 인증).
        return {
            "url":          result["url"],
            "token_issued": result["token_issued"],
            "error":        result.get("error") or None,
            "username":     current_user.username,
            "server":       server,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("JupyterHub token error for %s: %s", current_user.username, e)
        raise HTTPException(status_code=502, detail=f"JupyterHub 토큰 발급 오류: {e}") from e


@router.post("/token")
async def post_jupyter_token(
    body: TokenRequest,
    current_user: UserRead = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """POST 방식 토큰 발급 — server는 request body에 담아 전송."""
    svc = JupyterService(db=db)
    try:
        result = await svc.get_token_url(current_user.username, body.server, body.size)
        logger.info(
            "token request  user=%-12s  server=%r  size=%r  token_issued=%s",
            current_user.username, body.server or "(default)", body.size or "(none)", result["token_issued"],
        )
        return {
            "url":          result["url"],
            "token_issued": result["token_issued"],
            "error":        result.get("error") or None,
            "username":     current_user.username,
            "server":       body.server,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("JupyterHub token error for %s: %s", current_user.username, e)
        raise HTTPException(status_code=502, detail=f"JupyterHub 토큰 발급 오류: {e}") from e


@router.get("/health")
async def jupyter_health(db: Session = Depends(get_db)):
    """JupyterHub 헬스체크"""
    svc = JupyterService(db=db)
    healthy = await svc.check_health()
    url = svc.get_lab_url()
    return {"status": "ok" if healthy else "unavailable", "url": url}


@router.get("/stats")
async def jupyter_stats(
    _: UserRead = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """JupyterHub 서버 현황."""
    svc = JupyterService(db=db)
    return await svc.get_hub_stats()

