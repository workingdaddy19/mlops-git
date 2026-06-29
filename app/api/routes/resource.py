"""분석 자원 라이프사이클 API — 과제 / 용량 산정 / 자원 대장 / 대시보드 / 회수 현황.

접근제어(resource-aware-jupyter):
  - 사용자: 본인 과제 조회/등록, 자원 신청(Ledger submitted), 본인 할당/프로파일 조회.
  - 관리자: 전체 과제·대장 관리, 용량 산정, 승인 전이(자기승인 차단), 회수.
실제 프로비저닝·회수는 인프라팀 수행, 포탈은 기록(System of Record) + 라이프사이클 + 만료 D-14 가시화.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import _is_project_member, get_current_user, get_db, get_owned_project, require_admin
from app.core.dateutil import parse_date
from app.models.resource import (
    LEDGER_STATUSES,
    PROJECT_STATUSES,
    AnalysisProject,
    ResourceLedger,
)
from app.repositories.resource_repo import ResourceRepository
from app.repositories.user_repo import UserRepository
from app.schemas.auth import UserRead
from app.schemas.resource import (
    AnalysisProjectCreate,
    AnalysisProjectDetail,
    AnalysisProjectRead,
    AnalysisProjectUpdate,
    CapacityEstimateCreate,
    CapacityEstimateRead,
    LedgerTransition,
    ResourceLedgerCreate,
    ResourceLedgerRead,
    ResourceLedgerUpdate,
    ResourceRequestCreate,
)
from app.services.resource_profiles import find_profile, load_profiles
from app.services.resource_service import ResourceService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/resource", tags=["resource"])


def _assert_owns(db: Session, project_id: int, user: UserRead):
    """ledger/estimate 등 하위 엔티티의 소유권 확인(본인 과제 or admin)."""
    proj = ResourceRepository(db).get_project(project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="과제를 찾을 수 없습니다.")
    if not _is_project_member(proj, user):
        raise HTTPException(status_code=403, detail="본인 과제의 자원만 접근할 수 있습니다.")
    return proj


# ═══════════════════════════════════════════ Projects ═══════════════════════
@router.get("/projects", response_model=list[AnalysisProjectRead])
def list_projects(
    status: str | None = Query(default=None),
    name: str | None = None,
    owner: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    db: Session = Depends(get_db),
    _: UserRead = Depends(require_admin),
):
    """전체 과제 (admin). 과제명·담당자·기간 필터."""
    if status and status not in PROJECT_STATUSES:
        raise HTTPException(status_code=400, detail=f"유효하지 않은 상태: {status}")
    projects = ResourceRepository(db).list_projects(
        status, name or None, owner or None, parse_date(date_from), parse_date(date_to))
    return [AnalysisProjectRead.model_validate(p) for p in projects]


@router.get("/projects/mine", response_model=list[AnalysisProjectRead])
def list_my_projects(
    date_from: str | None = None,
    date_to: str | None = None,
    db: Session = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    """본인 참여 과제 (모든 사용자). 기간 필터(created_at)."""
    projects = ResourceService(db).list_my_projects(current_user, parse_date(date_from), parse_date(date_to))
    return [AnalysisProjectRead.model_validate(p) for p in projects]


@router.get("/users/lookup")
def lookup_users(
    q: str = "",
    db: Session = Depends(get_db),
    _: UserRead = Depends(get_current_user),
):
    """멤버 선택용 사용자 검색(인증 필요, 비-admin 허용). 사번/성명 부분일치·상한 20·최소 필드."""
    q = (q or "").strip()
    if len(q) < 1:
        return []
    users = UserRepository(db).search(q, limit=20)
    return [{"username": u.username, "name": u.name, "department": u.department} for u in users]


@router.get("/users/resolve")
def resolve_users(
    usernames: str = "",
    db: Session = Depends(get_db),
    _: UserRead = Depends(get_current_user),
):
    """사번 CSV → 이름 해석(인증). 멤버 사번을 성명으로 표시할 때 사용."""
    ids = [s.strip() for s in (usernames or "").split(",") if s.strip()][:50]
    if not ids:
        return []
    users = UserRepository(db).get_by_usernames(ids)
    return [{"username": u.username, "name": u.name} for u in users]


@router.post("/projects", response_model=AnalysisProjectRead, status_code=201)
def create_project(
    body: AnalysisProjectCreate,
    db: Session = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    """과제 등록. 비-admin은 owner/created_by가 본인으로 강제된다."""
    svc = ResourceService(db)
    repo = svc.repo
    code = (body.code or "").strip() or svc.generate_code()
    if repo.get_project_by_code(code):
        raise HTTPException(status_code=409, detail=f"과제 코드 '{code}'가 이미 존재합니다.")

    if current_user.role == "admin":
        owner = body.owner
    else:
        owner = (current_user.name or "").strip() or current_user.username

    project = AnalysisProject(
        code=code, name=body.name, purpose=body.purpose,
        period_start=body.period_start, period_end=body.period_end,
        owner=owner, member_count=body.member_count, members=body.members,
        data_types=body.data_types, datasets=body.datasets,
        security_review_status=body.security_review_status,
        security_review_date=body.security_review_date,
        itsm_ticket=body.itsm_ticket, status="planning", created_by=current_user.username,
    )
    created = repo.create_project(project)
    logger.info("analysis project created: code=%s by=%s", code, current_user.username)
    return AnalysisProjectRead.model_validate(created)


@router.get("/projects/{project_id}", response_model=AnalysisProjectDetail)
def get_project(
    project: AnalysisProject = Depends(get_owned_project),
    db: Session = Depends(get_db),
):
    """과제 상세 (본인/admin)."""
    svc = ResourceService(db)
    detail = AnalysisProjectDetail.model_validate(project)
    detail.ledgers = [svc.to_ledger_read(l) for l in project.ledgers]
    return detail


@router.put("/projects/{project_id}", response_model=AnalysisProjectRead)
def update_project(
    body: AnalysisProjectUpdate,
    project: AnalysisProject = Depends(get_owned_project),
    db: Session = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    """과제 수정 (본인/멤버/admin). 상태 변경은 사용자도 가능, 담당자(owner) 변경은 admin 전용."""
    if body.status and body.status not in PROJECT_STATUSES:
        raise HTTPException(status_code=400, detail=f"유효하지 않은 상태: {body.status}")
    data = body.model_dump(exclude_unset=True)
    if current_user.role != "admin":
        data.pop("owner", None)   # 담당자 변경은 admin 전용 (상태는 사용자도 허용)
    for field, value in data.items():
        setattr(project, field, value)
    db.commit()
    db.refresh(project)
    return AnalysisProjectRead.model_validate(project)


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: int, db: Session = Depends(get_db), _: UserRead = Depends(require_admin)):
    repo = ResourceRepository(db)
    project = repo.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="과제를 찾을 수 없습니다.")
    if project.status != "planning":
        raise HTTPException(status_code=400, detail="계획(planning) 상태의 과제만 삭제할 수 있습니다.")
    repo.delete_project(project)


# ═══════════════════ Capacity Estimate (작성=사용자, 승인=admin) ═════════════
@router.post("/projects/{project_id}/estimates", response_model=CapacityEstimateRead, status_code=201)
def create_estimate(
    body: CapacityEstimateCreate,
    project: AnalysisProject = Depends(get_owned_project),  # 본인 과제 or admin
    db: Session = Depends(get_db),
):
    """용량 산정서 작성 — 본인 과제면 사용자도 가능(pending). 승인은 admin."""
    svc = ResourceService(db)
    estimate = svc.build_estimate(project.id, body)
    created = svc.repo.create_estimate(estimate)
    return CapacityEstimateRead.model_validate(created)


def _check_no_active_ledgers(repo: ResourceRepository, project_id: int):
    proj = repo.get_project(project_id)
    if not proj:
        return
    active = [l for l in proj.ledgers if l.status in ("submitted", "approved", "active")]
    if active:
        raise HTTPException(status_code=400, detail="제출/승인/활성 중인 자원 배분이 있어 산정서를 변경하거나 삭제할 수 없습니다.")


@router.post("/estimates/{estimate_id}/approve", response_model=CapacityEstimateRead)
def approve_estimate(estimate_id: int, db: Session = Depends(get_db), _: UserRead = Depends(require_admin)):
    """산정서 승인 (admin 전용) — 승인된 산정서만 자원 배분의 용량 한도 기준이 된다."""
    svc = ResourceService(db)
    try:
        est = svc.approve_estimate(estimate_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return CapacityEstimateRead.model_validate(est)


@router.delete("/estimates/{estimate_id}", status_code=204)
def delete_estimate(estimate_id: int, db: Session = Depends(get_db), current_user: UserRead = Depends(get_current_user)):
    repo = ResourceRepository(db)
    est = repo.get_estimate(estimate_id)
    if not est:
        raise HTTPException(status_code=404, detail="산정서를 찾을 수 없습니다.")
    if current_user.role != "admin":
        _assert_owns(db, est.project_id, current_user)
        if est.status == "approved":
            raise HTTPException(status_code=403, detail="승인된 산정서는 삭제할 수 없습니다.")
    _check_no_active_ledgers(repo, est.project_id)
    repo.delete_estimate(est)


@router.put("/estimates/{estimate_id}", response_model=CapacityEstimateRead)
def update_estimate(
    estimate_id: int, body: CapacityEstimateCreate,
    db: Session = Depends(get_db), current_user: UserRead = Depends(get_current_user)
):
    svc = ResourceService(db)
    est = svc.repo.get_estimate(estimate_id)
    if not est:
        raise HTTPException(status_code=404, detail="산정서를 찾을 수 없습니다.")
    if current_user.role != "admin":
        _assert_owns(db, est.project_id, current_user)
        if est.status == "approved":
            raise HTTPException(status_code=403, detail="승인된 산정서는 수정할 수 없습니다.")
    
    _check_no_active_ledgers(svc.repo, est.project_id)
    
    new_est = svc.build_estimate(est.project_id, body)
    
    est.dataset_summary = new_est.dataset_summary
    est.recommended_node = new_est.recommended_node
    est.basis_note = new_est.basis_note
    est.estimated_by = new_est.estimated_by
    est.derived_peak_memory_gb = new_est.derived_peak_memory_gb
    est.derived_peak_vcpu = new_est.derived_peak_vcpu
    
    for step in list(est.steps):
        db.delete(step)
    for step in new_est.steps:
        est.steps.append(step)
        
    svc.repo.save()
    db.refresh(est)
    return CapacityEstimateRead.model_validate(est)


# ═══════════════════════════════════════════ 사용자 자원 신청 ═══════════════
@router.post("/projects/{project_id}/resource-request", response_model=ResourceLedgerRead, status_code=201)
def create_resource_request(
    body: ResourceRequestCreate,
    project: AnalysisProject = Depends(get_owned_project),
    db: Session = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    """사용자 자원 신청 — 프로파일(용량)+기간(필수) → Ledger(submitted), 대상=신청자."""
    svc = ResourceService(db)
    profiles = load_profiles(db)
    prof = find_profile(profiles, body.profile_server)  # server="" 도 유효(기본 CPU)
    if not prof:
        raise HTTPException(status_code=400, detail="유효하지 않은 자원 프로파일입니다.")
    if body.period_start > body.period_end:
        raise HTTPException(status_code=400, detail="시작일이 종료일보다 늦을 수 없습니다.")
    # FR-6: 신청 시점 산정서 한도 검증
    try:
        svc.assert_request_capacity(project.id, prof.vcpu, prof.mem_gb)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    ledger = ResourceLedger(
        project_id=project.id, status="submitted",
        jupyter_server_type=body.profile_server or None,
        alloc_vcpu=prof.vcpu, alloc_mem_gb=prof.mem_gb, alloc_gpu=prof.gpu,
        assigned_to=current_user.username,          # 권한은 신청 사용자에게만
        starts_at=body.period_start, expires_at=body.period_end,
        request_note=body.request_note, recorded_by=current_user.username,
    )
    created = svc.repo.create_ledger(ledger)
    logger.info("resource request: project=%s profile=%r by=%s", project.code, body.profile_server, current_user.username)
    return svc.to_ledger_read(created)


# ═══════════════ Resource Ledger (등록·수정·제출=사용자, 승인·회수=admin) ════
@router.post("/projects/{project_id}/ledgers", response_model=ResourceLedgerRead, status_code=201)
def create_ledger(
    body: ResourceLedgerCreate,
    project: AnalysisProject = Depends(get_owned_project),  # 본인 과제 or admin
    db: Session = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    """자원 대장 직접 등록(수동 수치) — admin 전용. 사용자는 'resource-request'(간편 신청) 사용."""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="자원 배분 직접 등록은 관리자만 가능합니다. 사용자는 '자원 신청'을 이용하세요.")
    svc = ResourceService(db)
    data = body.model_dump()
    # FR-6: 등록 시점 산정서 한도 검증
    try:
        svc.assert_request_capacity(project.id, data.get("alloc_vcpu"), data.get("alloc_mem_gb"))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    ledger = ResourceLedger(project_id=project.id, status="draft", recorded_by=current_user.username, **data)
    created = svc.repo.create_ledger(ledger)
    return svc.to_ledger_read(created)


@router.put("/ledgers/{ledger_id}", response_model=ResourceLedgerRead)
def update_ledger(
    ledger_id: int, body: ResourceLedgerUpdate,
    db: Session = Depends(get_db), current_user: UserRead = Depends(get_current_user),
):
    svc = ResourceService(db)
    ledger = svc.repo.get_ledger(ledger_id)
    if not ledger:
        raise HTTPException(status_code=404, detail="자원 대장을 찾을 수 없습니다.")
    if current_user.role != "admin":
        _assert_owns(db, ledger.project_id, current_user)
        if ledger.status not in ("draft", "submitted"):
            raise HTTPException(status_code=403, detail="승인 단계 이후에는 수정할 수 없습니다.")
    data = body.model_dump(exclude_unset=True)

    if "alloc_vcpu" in data or "alloc_mem_gb" in data:
        new_vcpu = data.get("alloc_vcpu", ledger.alloc_vcpu)
        new_mem = data.get("alloc_mem_gb", ledger.alloc_mem_gb)
        cap = svc.remaining_capacity(ledger.project_id)
        if cap["has_approved_estimate"]:
            used_v = cap["used_vcpu"]
            used_m = cap["used_mem"]
            if ledger.status in ("approved", "active"):
                used_v -= (ledger.alloc_vcpu or 0)
                used_m -= (ledger.alloc_mem_gb or 0)
            remain_v = cap["peak_vcpu"] - used_v
            remain_m = cap["peak_mem"] - used_m
            if new_vcpu is not None and cap["peak_vcpu"] and new_vcpu > remain_v + 1e-9:
                raise HTTPException(status_code=400, detail=f"vCPU 한도 초과 — 남은 {round(remain_v, 2)} vCPU (요청 {new_vcpu})")
            if new_mem is not None and cap["peak_mem"] and new_mem > remain_m + 1e-9:
                raise HTTPException(status_code=400, detail=f"메모리 한도 초과 — 남은 {round(remain_m, 2)} GB (요청 {new_mem})")

    for field, value in data.items():
        setattr(ledger, field, value)
    svc.repo.save()
    db.refresh(ledger)
    return svc.to_ledger_read(ledger)


@router.post("/ledgers/{ledger_id}/transition", response_model=ResourceLedgerRead)
def transition_ledger(
    ledger_id: int, body: LedgerTransition,
    db: Session = Depends(get_db), current_user: UserRead = Depends(get_current_user),
):
    svc = ResourceService(db)
    ledger = svc.repo.get_ledger(ledger_id)
    if not ledger:
        raise HTTPException(status_code=404, detail="자원 대장을 찾을 수 없습니다.")
    if body.to_status not in LEDGER_STATUSES:
        raise HTTPException(status_code=400, detail=f"유효하지 않은 상태: {body.to_status}")
    # 사용자는 본인 과제의 제출/철회(draft↔submitted)만, 승인·활성·회수는 admin
    if current_user.role != "admin":
        _assert_owns(db, ledger.project_id, current_user)
        if body.to_status not in ("submitted", "draft"):
            raise HTTPException(status_code=403, detail="승인·활성·회수는 관리자만 가능합니다.")
    # 승인/활성 전이 시: 필수값 + 승인된 산정서 + 총용량 한도 검증
    if body.to_status in ("approved", "active"):
        try:
            svc.assert_allocatable(ledger)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
    try:
        svc.transition_ledger(
            ledger, body.to_status,
            reclaim_reason=body.reclaim_reason, reclaimed_at=body.reclaimed_at, actor=current_user.username,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    logger.info("ledger %s -> %s by %s", ledger_id, body.to_status, current_user.username)
    return svc.to_ledger_read(ledger)


@router.delete("/ledgers/{ledger_id}", status_code=204)
def delete_ledger(ledger_id: int, db: Session = Depends(get_db), current_user: UserRead = Depends(get_current_user)):
    repo = ResourceRepository(db)
    ledger = repo.get_ledger(ledger_id)
    if not ledger:
        raise HTTPException(status_code=404, detail="자원 대장을 찾을 수 없습니다.")
    if current_user.role != "admin":
        _assert_owns(db, ledger.project_id, current_user)
        if ledger.status not in ("draft", "submitted"):
            raise HTTPException(status_code=403, detail="승인 단계 이후에는 삭제할 수 없습니다.")
    repo.delete_ledger(ledger)


# ═══════════════════════════════════════════ 프로파일 / 본인 할당 (user) ════
@router.get("/profiles")
def list_profiles(db: Session = Depends(get_db), _: UserRead = Depends(get_current_user)):
    """자원 프로파일 카탈로그 (모든 사용자)."""
    return [p.model_dump() for p in load_profiles(db)]


@router.get("/my-allocations")
def my_allocations(db: Session = Depends(get_db), current_user: UserRead = Depends(get_current_user)):
    """본인 active(미만료) 할당 + 본인/전체 합계 + 프로파일."""
    return ResourceService(db).my_allocations(current_user)


@router.get("/my-ledgers")
def my_ledgers(
    date_from: str | None = None,
    date_to: str | None = None,
    db: Session = Depends(get_db),
    current_user: UserRead = Depends(get_current_user),
):
    """본인 과제들의 전체 자원 대장(라이프사이클). 기간 필터(created_at)."""
    return ResourceService(db).my_ledgers(current_user, parse_date(date_from), parse_date(date_to))


@router.get("/projects/{project_id}/capacity")
def project_capacity(
    project: AnalysisProject = Depends(get_owned_project),
    db: Session = Depends(get_db),
):
    """승인된 산정서 한도 + 잔여 용량 (폼 표시·검증용, 본인/admin)."""
    return ResourceService(db).remaining_capacity(project.id)


# ═══════════════════════════════════════════ Dashboard / Reclaim / 승인큐 ═══
@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db), _: UserRead = Depends(require_admin)):
    """활성/만료임박(D-14)/회수대상 + 용량 합계."""
    return ResourceService(db).dashboard()


@router.get("/requests")
def pending_requests(db: Session = Depends(get_db), _: UserRead = Depends(require_admin)):
    """자원 신청 승인 대기(submitted) 큐."""
    return ResourceService(db).pending_requests()


@router.get("/reclaim")
def reclaim_view(
    date_from: str | None = None,
    date_to: str | None = None,
    name: str | None = None,
    requester: str | None = None,
    db: Session = Depends(get_db),
    _: UserRead = Depends(require_admin),
):
    """자원 회수 현황. 과제명·신청자 필터 + 회수완료 기간 필터(reclaimed_at)."""
    return ResourceService(db).reclaim_view(
        parse_date(date_from), parse_date(date_to), name or None, requester or None)
