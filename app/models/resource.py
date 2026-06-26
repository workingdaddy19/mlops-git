"""분석 자원 라이프사이클 — 과제 / 용량 산정서 / 자원 대장.

신규 테이블은 `Base.metadata.create_all`(앱 기동 시)로 자동 생성된다.
실제 EKS/JupyterHub 프로비저닝·회수는 인프라팀이 수행하고, 포탈은 기록(System of Record)을 담당한다.
"""
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

# ── 코드값 ────────────────────────────────────────────────────────────────
PROJECT_STATUSES = ("planning", "active", "completed")

# 자원 대장 라이프사이클 상태
LEDGER_STATUSES = ("draft", "submitted", "approved", "active", "reclaim_pending", "reclaimed")
# 허용 상태 전이 (현재 → 가능한 다음)
LEDGER_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "draft": ("submitted",),
    "submitted": ("approved", "draft"),
    "approved": ("active", "submitted"),
    "active": ("reclaim_pending",),
    "reclaim_pending": ("reclaimed", "active"),
    "reclaimed": (),
}
RECLAIM_REASONS = ("expired", "idle", "event")  # 정기(만료) / 유휴 / 이벤트(과제중단·담당자변경)


class AnalysisProject(Base):
    """분석 과제 — 등록 산출물 = '과제 정의서'."""

    __tablename__ = "analysis_projects"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    purpose: Mapped[str | None] = mapped_column(Text)
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    owner: Mapped[str] = mapped_column(String(100), nullable=False)
    member_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    members: Mapped[str | None] = mapped_column(Text)
    data_types: Mapped[str | None] = mapped_column(Text)        # 분석 데이터 종류
    datasets: Mapped[str | None] = mapped_column(Text)
    # 정보보안 협의
    security_review_status: Mapped[str] = mapped_column(String(20), nullable=False, default="none")  # none/requested/done
    security_review_date: Mapped[date | None] = mapped_column(Date)
    itsm_ticket: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="planning", index=True)
    created_by: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    estimates: Mapped[list["CapacityEstimate"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="CapacityEstimate.id.desc()")
    ledgers: Mapped[list["ResourceLedger"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="ResourceLedger.id.desc()")


class CapacityEstimate(Base):
    """용량 산정 워크시트 헤더 — Peak 기반(평균 아님). 과제별 1:N(개정 이력)."""

    __tablename__ = "capacity_estimates"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("analysis_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    dataset_summary: Mapped[str | None] = mapped_column(Text)         # 원본 행수·row당 크기 등
    derived_peak_memory_gb: Mapped[float | None] = mapped_column(Float)
    derived_peak_vcpu: Mapped[float | None] = mapped_column(Float)
    recommended_node: Mapped[str | None] = mapped_column(String(200))  # 노드타입·수
    basis_note: Mapped[str | None] = mapped_column(Text)
    estimated_by: Mapped[str | None] = mapped_column(String(50))
    # 산정서 승인 상태 — approved 산정서만 자원 배분의 용량 한도 기준이 된다.
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", server_default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped["AnalysisProject"] = relationship(back_populates="estimates")
    steps: Mapped[list["CapacityWorksheetStep"]] = relationship(
        back_populates="estimate", cascade="all, delete-orphan", order_by="CapacityWorksheetStep.step_no")


class CapacityWorksheetStep(Base):
    """산정 워크시트 라인아이템 — 단계별 메모리 증감을 누적해 Peak 산출."""

    __tablename__ = "capacity_worksheet_steps"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    estimate_id: Mapped[int] = mapped_column(
        ForeignKey("capacity_estimates.id", ondelete="CASCADE"), nullable=False, index=True)
    step_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    operation: Mapped[str] = mapped_column(String(200), nullable=False)   # 로드/Join/get_dummies/groupby/학습...
    data_scale: Mapped[str | None] = mapped_column(String(200))           # 데이터 규모
    rationale: Mapped[str | None] = mapped_column(Text)                   # 산출 근거(merge 내부 copy 3배 등)
    vcpu: Mapped[float | None] = mapped_column(Float)
    mem_delta_gb: Mapped[float | None] = mapped_column(Float)             # 메모리 증감
    cumulative_peak_gb: Mapped[float | None] = mapped_column(Float)       # 누적 Peak
    is_peak: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")

    estimate: Mapped["CapacityEstimate"] = relationship(back_populates="steps")


class ResourceLedger(Base):
    """자원 대장 / 배분 — 라이프사이클 상태기계 + 만료일 + ITSM 티켓 참조."""

    __tablename__ = "resource_ledgers"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("analysis_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    namespace: Mapped[str | None] = mapped_column(String(100))
    node_group: Mapped[str | None] = mapped_column(String(100))
    jupyter_server_type: Mapped[str | None] = mapped_column(String(100))
    alloc_vcpu: Mapped[float | None] = mapped_column(Float)
    alloc_mem_gb: Mapped[float | None] = mapped_column(Float)
    alloc_gpu: Mapped[int | None] = mapped_column(Integer)
    itsm_ticket: Mapped[str | None] = mapped_column(String(100))
    allocated_at: Mapped[date | None] = mapped_column(Date)
    expires_at: Mapped[date | None] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", index=True)
    reclaimed_at: Mapped[date | None] = mapped_column(Date)
    reclaim_reason: Mapped[str | None] = mapped_column(String(20))
    recorded_by: Mapped[str | None] = mapped_column(String(50))
    request_note: Mapped[str | None] = mapped_column(String(500))  # 사용자 자원 신청 사유
    assigned_to: Mapped[str | None] = mapped_column(String(50), index=True)  # 권한 부여 대상 사용자(username)
    starts_at: Mapped[date | None] = mapped_column(Date)                     # 접속 가능 시작일(이전엔 접속 불가)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    project: Mapped["AnalysisProject"] = relationship(back_populates="ledgers")
