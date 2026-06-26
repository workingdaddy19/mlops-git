"""접속 기록 / 감사 로그 (금융권 보안).

- POST /api/access-log         : 인증된 프론트엔드 비콘(메뉴 접속/로그아웃 기록)
- GET  /api/admin/access-logs  : 관리자 조회(필터·페이지네이션)
- GET  /api/admin/access-logs/export : CSV 내보내기
- log_login_event()            : auth 라우트에서 로그인 성공/실패 기록에 재사용
"""
import csv
import io
import logging
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, require_admin
from app.models.access_log import AccessLog
from app.repositories.access_log_repo import AccessLogRepository
from app.repositories.user_repo import UserRepository
from app.schemas.access_log import AccessLogCreate, AccessLogRead
from app.schemas.auth import UserRead

logger = logging.getLogger(__name__)
router = APIRouter(tags=["access-log"])


# ── 경로 → 메뉴명 매핑 ────────────────────────────────────────────────────
MENU_MAP = {
    "/dashboard": "Home",
    "/board": "Notice",
    "/permissions": "권한 신청",
    "/me": "내정보",
    "/files": "저장소 (S3)",
    "/data/query": "데이터조회(Athena)",
    "/aiml/jupyter": "분석기(Jupyter)",
    "/aiml/experiments": "실험/모델",
    "/resource/projects": "분석 과제",
    "/resource/dashboard": "자원 대시보드",
    "/admin/resource-reclaim": "자원 회수",
    "/admin/users": "사용자 관리",
    "/admin/permission-requests": "권한 신청 관리",
    "/admin/settings": "설정",
    "/admin/access-log": "접속 기록",
}


def resolve_menu(path: str | None) -> str:
    """요청 경로를 메뉴명으로 변환. 정확 일치 우선, 없으면 prefix 매칭."""
    p = (path or "").split("?")[0].rstrip("/") or "/"
    if p in MENU_MAP:
        return MENU_MAP[p]
    for key, label in MENU_MAP.items():
        if p.startswith(key + "/"):
            return label
    return p


def get_client_ip(request: Request) -> str | None:
    """ALB 뒤이므로 실제 클라이언트 IP는 X-Forwarded-For 첫 항목에서 추출."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()[:64]
    return request.client.host if request.client else None


def record_event(
    db: Session,
    request: Request,
    *,
    user_id: int | None,
    username: str,
    name: str | None = None,
    department: str | None = None,
    menu: str,
    action: str,
) -> None:
    """임의 보안 이벤트(비번 변경/초기화 등)를 감사 로그로 기록(best-effort)."""
    try:
        AccessLogRepository(db).create(
            AccessLog(
                user_id=user_id,
                username=username[:50],
                name=name,
                department=department,
                client_ip=get_client_ip(request),
                menu=menu,
                path=None,
                action=action,
            )
        )
    except Exception:  # noqa: BLE001
        logger.warning("이벤트 기록 실패: action=%s username=%s", action, username, exc_info=True)


def log_login_event(db: Session, request: Request, username: str, *, success: bool) -> None:
    """로그인 성공/실패 이벤트를 기록(best-effort — 실패해도 로그인 흐름을 막지 않음)."""
    try:
        user = UserRepository(db).get_by_username(username)
        AccessLogRepository(db).create(
            AccessLog(
                user_id=user.id if user else None,
                username=username[:50],
                name=user.name if user else None,
                department=user.department if user else None,
                client_ip=get_client_ip(request),
                menu="로그인",
                path="/login",
                action="login" if success else "login_fail",
            )
        )
    except Exception:  # noqa: BLE001 — 감사로그 실패가 로그인을 막으면 안 됨
        logger.warning("로그인 이벤트 기록 실패: username=%s", username, exc_info=True)


# ── 비콘: 메뉴 접속 / 로그아웃 ────────────────────────────────────────────
@router.post("/access-log", status_code=status.HTTP_204_NO_CONTENT)
def log_access(
    body: AccessLogCreate,
    request: Request,
    current_user: UserRead = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """인증된 프론트엔드가 현재 페이지/로그아웃을 기록(localStorage 토큰 기반)."""
    action = body.action if body.action in ("view", "logout") else "view"
    menu = "로그아웃" if action == "logout" else resolve_menu(body.path)
    try:
        AccessLogRepository(db).create(
            AccessLog(
                user_id=current_user.id,
                username=current_user.username,
                name=current_user.name,
                department=current_user.department,
                client_ip=get_client_ip(request),
                menu=menu,
                path=(body.path or "")[:200] or None,
                action=action,
            )
        )
    except Exception:  # noqa: BLE001 — 기록 실패가 화면 동작을 막지 않도록
        logger.warning("접속 기록 실패: path=%s", body.path, exc_info=True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── 관리자 조회 ──────────────────────────────────────────────────────────
def _parse_date(s: str | None, *, end: bool = False) -> datetime | None:
    """YYYY-MM-DD 또는 ISO 문자열 파싱. end=True면 해당 일자의 다음날 0시(상한 배타)."""
    if not s:
        return None
    try:
        if len(s) <= 10:
            d = datetime.combine(date.fromisoformat(s), datetime.min.time())
            return d + timedelta(days=1) if end else d
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _query_filters(
    username: str | None,
    department: str | None,
    menu: str | None,
    action: str | None,
    date_from: str | None,
    date_to: str | None,
) -> dict:
    return {
        "username": username or None,
        "department": department or None,
        "menu": menu or None,
        "action": action or None,
        "dt_from": _parse_date(date_from),
        "dt_to": _parse_date(date_to, end=True),
    }


@router.get("/admin/access-logs")
def list_access_logs(
    username: str | None = None,
    department: str | None = None,
    menu: str | None = None,
    action: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    _admin: UserRead = Depends(require_admin),
):
    """접속 기록 조회 (admin only). 필터 + 페이지네이션."""
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    filters = _query_filters(username, department, menu, action, date_from, date_to)
    rows, total = AccessLogRepository(db).list_filtered(limit=limit, offset=offset, **filters)
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [AccessLogRead.model_validate(r).model_dump(mode="json") for r in rows],
    }


@router.get("/admin/access-logs/export")
def export_access_logs(
    username: str | None = None,
    department: str | None = None,
    menu: str | None = None,
    action: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    db: Session = Depends(get_db),
    _admin: UserRead = Depends(require_admin),
):
    """접속 기록 CSV 내보내기 (admin only, 최대 100,000건)."""
    filters = _query_filters(username, department, menu, action, date_from, date_to)
    rows, _ = AccessLogRepository(db).list_filtered(limit=100_000, offset=0, **filters)

    buf = io.StringIO()
    buf.write("﻿")  # Excel 한글 깨짐 방지 BOM
    writer = csv.writer(buf)
    writer.writerow(["시각", "아이디", "성명", "부서", "접속IP", "메뉴", "동작"])
    for r in rows:
        ts = r.accessed_at.strftime("%Y-%m-%d %H:%M:%S") if r.accessed_at else ""
        writer.writerow([
            ts, r.username, r.name or "", r.department or "",
            r.client_ip or "", r.menu or "", r.action,
        ])

    filename = f"access_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
