from datetime import date, datetime

from pydantic import BaseModel


# ── Worksheet Step ──────────────────────────────────────────────────────────
class WorksheetStepIn(BaseModel):
    operation: str
    data_scale: str | None = None
    rationale: str | None = None
    vcpu: float | None = None
    mem_delta_gb: float | None = None


class WorksheetStepRead(BaseModel):
    id: int
    step_no: int
    operation: str
    data_scale: str | None = None
    rationale: str | None = None
    vcpu: float | None = None
    mem_delta_gb: float | None = None
    cumulative_peak_gb: float | None = None
    is_peak: bool = False

    class Config:
        from_attributes = True


# ── Capacity Estimate ───────────────────────────────────────────────────────
class CapacityEstimateCreate(BaseModel):
    dataset_summary: str | None = None
    recommended_node: str | None = None
    basis_note: str | None = None
    estimated_by: str | None = None
    # 직접 입력값(스텝이 없을 때 사용). 스텝이 있으면 자동 산출로 덮어씀.
    derived_peak_memory_gb: float | None = None
    derived_peak_vcpu: float | None = None
    steps: list[WorksheetStepIn] = []


class CapacityEstimateRead(BaseModel):
    id: int
    project_id: int
    dataset_summary: str | None = None
    derived_peak_memory_gb: float | None = None
    derived_peak_vcpu: float | None = None
    recommended_node: str | None = None
    basis_note: str | None = None
    estimated_by: str | None = None
    status: str = "pending"
    created_at: datetime | None = None
    steps: list[WorksheetStepRead] = []

    class Config:
        from_attributes = True


# ── Resource Ledger ─────────────────────────────────────────────────────────
class ResourceLedgerCreate(BaseModel):
    assigned_to: str | None = None
    namespace: str | None = None
    node_group: str | None = None
    jupyter_server_type: str | None = None
    alloc_vcpu: float | None = None
    alloc_mem_gb: float | None = None
    alloc_gpu: int | None = None
    itsm_ticket: str | None = None
    allocated_at: date | None = None
    starts_at: date | None = None
    expires_at: date | None = None


class ResourceLedgerUpdate(BaseModel):
    assigned_to: str | None = None
    namespace: str | None = None
    node_group: str | None = None
    jupyter_server_type: str | None = None
    alloc_vcpu: float | None = None
    alloc_mem_gb: float | None = None
    alloc_gpu: int | None = None
    itsm_ticket: str | None = None
    allocated_at: date | None = None
    starts_at: date | None = None
    expires_at: date | None = None


class LedgerTransition(BaseModel):
    """상태 전이 요청. reclaimed 전이 시 reclaim_reason 필요."""
    to_status: str
    reclaim_reason: str | None = None
    reclaimed_at: date | None = None


class ResourceRequestCreate(BaseModel):
    """사용자 자원 신청 — 프로파일(용량) + 기간(필수). Ledger를 submitted로 생성."""
    profile_server: str = ""          # 프로파일(JupyterHub named server) 키 = 용량
    period_start: date                # 사용 시작일(필수)
    period_end: date                  # 사용 종료(만료)일(필수)
    request_note: str | None = None   # 신청 사유


class ResourceLedgerRead(BaseModel):
    id: int
    project_id: int
    assigned_to: str | None = None
    namespace: str | None = None
    node_group: str | None = None
    jupyter_server_type: str | None = None
    alloc_vcpu: float | None = None
    alloc_mem_gb: float | None = None
    alloc_gpu: int | None = None
    itsm_ticket: str | None = None
    allocated_at: date | None = None
    starts_at: date | None = None
    expires_at: date | None = None
    status: str
    reclaimed_at: date | None = None
    reclaim_reason: str | None = None
    recorded_by: str | None = None
    request_note: str | None = None
    # 파생(만료 임박/경과) — 서비스에서 채움
    days_to_expiry: int | None = None
    expiry_state: str | None = None  # ok / soon / overdue / none

    class Config:
        from_attributes = True


# ── Analysis Project ────────────────────────────────────────────────────────
class AnalysisProjectCreate(BaseModel):
    code: str | None = None
    name: str
    purpose: str | None = None
    period_start: date | None = None
    period_end: date | None = None
    owner: str
    member_count: int = 1
    members: str | None = None
    data_types: str | None = None
    datasets: str | None = None
    security_review_status: str = "none"
    security_review_date: date | None = None
    itsm_ticket: str | None = None


class AnalysisProjectUpdate(BaseModel):
    name: str | None = None
    purpose: str | None = None
    period_start: date | None = None
    period_end: date | None = None
    owner: str | None = None
    member_count: int | None = None
    members: str | None = None
    data_types: str | None = None
    datasets: str | None = None
    security_review_status: str | None = None
    security_review_date: date | None = None
    itsm_ticket: str | None = None
    status: str | None = None


class AnalysisProjectRead(BaseModel):
    id: int
    code: str
    name: str
    purpose: str | None = None
    period_start: date | None = None
    period_end: date | None = None
    owner: str
    member_count: int
    members: str | None = None
    data_types: str | None = None
    datasets: str | None = None
    security_review_status: str
    security_review_date: date | None = None
    itsm_ticket: str | None = None
    status: str
    created_by: str | None = None
    created_at: datetime | None = None

    class Config:
        from_attributes = True


class AnalysisProjectDetail(AnalysisProjectRead):
    estimates: list[CapacityEstimateRead] = []
    ledgers: list[ResourceLedgerRead] = []
