from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.config import get_settings
from app.services.settings_service import SettingsService

router = APIRouter(tags=["web"])
templates = Jinja2Templates(directory="app/templates")

# 정적 자원 캐시버스팅 — 프로세스 시작 시각 기준(배포/재기동마다 갱신 → 브라우저 강제 재요청)
import time as _time
templates.env.globals["ASSET_VERSION"] = str(int(_time.time()))


@router.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/dashboard")


@router.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
async def dashboard_page(request: Request):
    return templates.TemplateResponse(
        "pages/dashboard.html",
        {"request": request, "active_page": "dashboard"},
    )


@router.get("/login", response_class=HTMLResponse, include_in_schema=False)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


# ── Data ──────────────────────────────────────────────────────────────────
@router.get("/data/query", response_class=HTMLResponse, include_in_schema=False)
async def query_page(request: Request):
    return templates.TemplateResponse("pages/query.html",
        {"request": request, "active_page": "query"})


# ── Analysis ──────────────────────────────────────────────────────────────
@router.get("/aiml/jupyter", response_class=HTMLResponse, include_in_schema=False)
async def jupyter_page(request: Request):
    return templates.TemplateResponse("pages/jupyter.html",
        {"request": request, "active_page": "jupyter"})


# ── Models ────────────────────────────────────────────────────────────────
@router.get("/aiml/experiments", response_class=HTMLResponse, include_in_schema=False)
async def experiments_page(request: Request, db: Session = Depends(get_db)):
    """Experiments & Pipelines — MLflow / Kubeflow Pipelines / Katib 진입점.

    3개 URL은 코드 기본값 + DB(system_settings, 관리자 Settings)에서 관리.
    """
    settings = get_settings()
    svc = SettingsService(db)
    return templates.TemplateResponse("pages/experiments.html", {
        "request": request,
        "active_page": "experiments",
        "mlflow_url": svc.get("MLFLOW_BASE_URL", settings.mlflow_base_url),
        "kfp_url":    svc.get("KFP_BASE_URL", settings.kfp_base_url),
        "katib_url":  svc.get("KATIB_BASE_URL", settings.katib_base_url),
    })


# ── Notice ────────────────────────────────────────────────────────────────
@router.get("/board", response_class=HTMLResponse, include_in_schema=False)
async def board_page(request: Request):
    return templates.TemplateResponse("pages/board.html",
        {"request": request, "active_page": "board"})


# ── Files (S3 file) ────────────────────────────────────────────────────────
@router.get("/files", response_class=HTMLResponse, include_in_schema=False)
async def files_page(request: Request):
    from app.core.config import get_settings
    s3_bucket = get_settings().s3_bucket_name
    return templates.TemplateResponse("pages/files.html",
        {"request": request, "active_page": "files", "s3_bucket": s3_bucket})


# ── 권한 신청 (사용자) ──────────────────────────────────────────────────────
@router.get("/permissions", response_class=HTMLResponse, include_in_schema=False)
async def permissions_page(request: Request):
    return templates.TemplateResponse("pages/permissions.html",
        {"request": request, "active_page": "permissions"})


# ── 내정보 ─────────────────────────────────────────────────────────────────
@router.get("/me", response_class=HTMLResponse, include_in_schema=False)
async def my_info_page(request: Request):
    return templates.TemplateResponse("pages/my_info.html",
        {"request": request, "active_page": "my-info"})


# ── 분석 자원 관리 ──────────────────────────────────────────────────────────
@router.get("/resource/dashboard", response_class=HTMLResponse, include_in_schema=False)
async def resource_dashboard_page(request: Request):
    return templates.TemplateResponse("pages/resource_dashboard.html",
        {"request": request, "active_page": "resource-dashboard"})


@router.get("/resource/projects", response_class=HTMLResponse, include_in_schema=False)
async def resource_projects_page(request: Request):
    return templates.TemplateResponse("pages/resource_projects.html",
        {"request": request, "active_page": "resource-projects"})


@router.get("/resource/projects/{project_id}", response_class=HTMLResponse, include_in_schema=False)
async def resource_project_detail_page(request: Request, project_id: int):
    return templates.TemplateResponse("pages/resource_project_detail.html",
        {"request": request, "active_page": "resource-projects", "project_id": project_id})


@router.get("/admin/resource-reclaim", response_class=HTMLResponse, include_in_schema=False)
async def resource_reclaim_page(request: Request):
    return templates.TemplateResponse("pages/resource_reclaim.html",
        {"request": request, "active_page": "resource-reclaim"})


# ── Admin ─────────────────────────────────────────────────────────────────
@router.get("/admin/users", response_class=HTMLResponse, include_in_schema=False)
async def admin_users_page(request: Request):
    return templates.TemplateResponse("pages/admin_users.html",
        {"request": request, "active_page": "admin-users"})


@router.get("/admin/permission-requests", response_class=HTMLResponse, include_in_schema=False)
async def admin_permission_requests_page(request: Request):
    return templates.TemplateResponse("pages/admin_permission_requests.html",
        {"request": request, "active_page": "admin-permission-requests"})


@router.get("/admin/access-log", response_class=HTMLResponse, include_in_schema=False)
async def admin_access_log_page(request: Request):
    return templates.TemplateResponse("pages/admin_access_log.html",
        {"request": request, "active_page": "admin-access-log"})


@router.get("/admin/settings", response_class=HTMLResponse, include_in_schema=False)
async def admin_settings_page(request: Request):
    return templates.TemplateResponse("pages/admin_settings.html",
        {"request": request, "active_page": "admin-settings"})

