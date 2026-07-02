"""분석 자원 라이프사이클 서비스 — 코드생성 / Peak 산정 / 상태전이 / D-14 분류 / 대시보드."""
import secrets
from datetime import date

from sqlalchemy.orm import Session

from app.models.resource import (
    LEDGER_TRANSITIONS,
    RECLAIM_REASONS,
    AnalysisProject,
    CapacityEstimate,
    CapacityWorksheetStep,
    ResourceLedger,
)
from app.repositories.resource_repo import ResourceRepository
from app.schemas.auth import UserRead
from app.schemas.resource import (
    CapacityEstimateCreate,
    ResourceLedgerRead,
)
from app.services.resource_profiles import find_profile, find_profile_by_size, load_profiles

EXPIRY_SOON_DAYS = 14


class ResourceService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = ResourceRepository(db)
        self._profiles_cache = None  # 요청 수명 내 프로파일 캐시(대시보드 size_label N+1 방지)

    def _profiles(self):
        if self._profiles_cache is None:
            self._profiles_cache = load_profiles(self.db)
        return self._profiles_cache

    def _names_for(self, usernames) -> dict[str, str]:
        """사번 목록 → {사번: 성명} 일괄 조회(N+1 방지)."""
        ids = sorted({u for u in usernames if u})
        if not ids:
            return {}
        from app.repositories.user_repo import UserRepository
        return {u.username: (u.name or "") for u in UserRepository(self.db).get_by_usernames(ids)}

    # ── Project ─────────────────────────────────────────────────────────────
    def generate_code(self) -> str:
        for _ in range(5):
            code = f"PRJ-{date.today():%Y%m%d}-{secrets.token_hex(2).upper()}"
            if not self.repo.get_project_by_code(code):
                return code
        return f"PRJ-{date.today():%Y%m%d}-{secrets.token_hex(4).upper()}"

    # ── Capacity Estimate (Peak 산정) ────────────────────────────────────────
    @staticmethod
    def build_estimate(project_id: int, body: CapacityEstimateCreate) -> CapacityEstimate:
        """스텝 누적으로 Peak 메모리/ vCPU 산출. 스텝이 없으면 입력값 사용."""
        est = CapacityEstimate(
            project_id=project_id,
            dataset_summary=body.dataset_summary,
            recommended_node=body.recommended_node,
            basis_note=body.basis_note,
            estimated_by=body.estimated_by,
            derived_peak_memory_gb=body.derived_peak_memory_gb,
            derived_peak_vcpu=body.derived_peak_vcpu,
        )

        if body.steps:
            cum = 0.0
            running: list[float] = []
            for s in body.steps:
                cum += (s.mem_delta_gb or 0.0)
                running.append(round(cum, 3))
            peak_mem = max(running)
            peak_idx = running.index(peak_mem)
            vcpus = [s.vcpu for s in body.steps if s.vcpu is not None]
            peak_vcpu = max(vcpus) if vcpus else None

            for i, s in enumerate(body.steps):
                est.steps.append(CapacityWorksheetStep(
                    step_no=i + 1,
                    operation=s.operation,
                    data_scale=s.data_scale,
                    rationale=s.rationale,
                    vcpu=s.vcpu,
                    mem_delta_gb=s.mem_delta_gb,
                    cumulative_peak_gb=running[i],
                    is_peak=(i == peak_idx),
                ))
            est.derived_peak_memory_gb = peak_mem
            est.derived_peak_vcpu = peak_vcpu
        return est

    # ── Ledger 상태 전이 ─────────────────────────────────────────────────────
    def transition_ledger(
        self, ledger: ResourceLedger, to_status: str, *,
        reclaim_reason: str | None = None, reclaimed_at: date | None = None, actor: str | None = None,
    ) -> ResourceLedger:
        allowed = LEDGER_TRANSITIONS.get(ledger.status, ())
        if to_status not in allowed:
            raise ValueError(f"'{ledger.status}' → '{to_status}' 전이는 허용되지 않습니다. (가능: {', '.join(allowed) or '없음'})")

        if to_status == "reclaimed":
            if reclaim_reason not in RECLAIM_REASONS:
                raise ValueError(f"회수 사유가 필요합니다. (가능: {', '.join(RECLAIM_REASONS)})")
            ledger.reclaim_reason = reclaim_reason
            ledger.reclaimed_at = reclaimed_at or date.today()

        ledger.status = to_status
        if actor:
            ledger.recorded_by = actor
        self.repo.save()
        self.db.refresh(ledger)
        return ledger

    # ── D-14 만료 분류 ───────────────────────────────────────────────────────
    @staticmethod
    def expiry_info(expires_at: date | None, today: date | None = None) -> tuple[int | None, str]:
        if not expires_at:
            return None, "none"
        today = today or date.today()
        days = (expires_at - today).days
        if days < 0:
            return days, "overdue"
        if days <= EXPIRY_SOON_DAYS:
            return days, "soon"
        return days, "ok"

    def to_ledger_read(self, ledger: ResourceLedger) -> ResourceLedgerRead:
        days, state = self.expiry_info(ledger.expires_at)
        read = ResourceLedgerRead.model_validate(ledger)
        read.days_to_expiry = days
        read.expiry_state = state
        return read

    # ── 공통: ledger → 과제명·신청자 포함 dict ───────────────────────────────
    def _ledger_row(self, l: ResourceLedger, name_map: dict[str, str] | None = None) -> dict:
        d = self.to_ledger_read(l).model_dump(mode="json")
        d["project_name"] = l.project.name if l.project else None
        d["project_code"] = l.project.code if l.project else None
        d["requester"] = l.recorded_by   # 신청자 = 요청 작성자
        d["assigned_to"] = l.assigned_to
        d["assignee_name"] = (name_map or {}).get(l.assigned_to or "", "")
        prof = find_profile_by_size(self._profiles(), l.jupyterhub_size)
        d["size_label"] = prof.name if prof else (l.jupyterhub_size or "")
        return d

    # ── 대시보드 ─────────────────────────────────────────────────────────────
    def dashboard(self) -> dict:
        active = self.repo.list_ledgers_by_statuses(("active",))
        name_map = self._names_for([l.assigned_to for l in active])
        rows = [self._ledger_row(l, name_map) for l in active]
        expiring = [r for r in rows if r["expiry_state"] == "soon"]
        overdue = [r for r in rows if r["expiry_state"] == "overdue"]

        totals = {
            "vcpu": round(sum((l.alloc_vcpu or 0) for l in active), 2),
            "mem_gb": round(sum((l.alloc_mem_gb or 0) for l in active), 2),
            "gpu": sum((l.alloc_gpu or 0) for l in active),
        }
        return {
            "active_count": len(active),
            "expiring_count": len(expiring),
            "overdue_count": len(overdue),
            "capacity_totals": totals,
            "active": rows,
            "expiring": expiring,
            "overdue": overdue,
        }

    def reclaim_view(self, dt_from=None, dt_to=None, name=None, requester=None) -> dict:
        pending = self.repo.list_ledgers_by_statuses(("reclaim_pending",))
        reclaimed = self.repo.list_ledgers_by_statuses(("reclaimed",))
        if dt_from or dt_to:
            reclaimed = [l for l in reclaimed if l.reclaimed_at
                         and (not dt_from or l.reclaimed_at >= dt_from)
                         and (not dt_to or l.reclaimed_at <= dt_to)]

        def keep(l):
            if name and not (l.project and name.lower() in (l.project.name or "").lower()):
                return False
            if requester and requester.lower() not in (l.recorded_by or "").lower():
                return False
            return True
        pending = [l for l in pending if keep(l)]
        reclaimed = [l for l in reclaimed if keep(l)]
        return {
            "pending": [self._ledger_row(l) for l in pending],
            "reclaimed": [self._ledger_row(l) for l in reclaimed],
        }

    # ── 사용자 스코프 ────────────────────────────────────────────────────────
    def list_my_projects(self, user: UserRead, dt_from=None, dt_to=None) -> list[AnalysisProject]:
        return self.repo.list_projects_for_user(
            user.username, (user.name or "").strip() or None, dt_from, dt_to)

    # ── 멤버 1인 1회(동시 1건) 신청 제한 ──────────────────────────────────────
    def assert_member_single_request(self, project_id: int, username: str) -> None:
        """멤버당 진행중(submitted/approved/active·만료 전) 신청이 있으면 차단.

        오토스케일링 전제로 '산정서 한도' 개념은 제거. 대신 멤버당 동시 1건만 허용
        (회수·만료 후 재신청 가능).
        """
        today = date.today()
        proj = self.repo.get_project(project_id)
        for l in (proj.ledgers if proj else []):
            if l.assigned_to != username:
                continue
            if l.status in ("submitted", "approved", "active") and (l.expires_at is None or l.expires_at >= today):
                raise ValueError("이미 진행 중인 분석기 신청이 있습니다. 회수·만료 후 다시 신청하세요.")

    def my_allocations(self, user: UserRead) -> dict:
        """본인(assigned_to)에게 부여된 active 할당 + 시작일 접근게이팅 + 합계 + 프로파일."""
        profiles = load_profiles(self.db)
        today = date.today()
        allocations: list[dict] = []
        my = {"vcpu": 0.0, "mem_gb": 0.0, "gpu": 0}
        for l in self.repo.list_active_ledgers_for_user(user.username):
            days, state = self.expiry_info(l.expires_at)
            if state == "overdue":
                continue  # 만료분은 제외
            # 시작일 접근 게이팅: 시작 전이면 접속 불가(upcoming)
            if l.starts_at and l.starts_at > today:
                access, days_to_start = "upcoming", (l.starts_at - today).days
            else:
                access, days_to_start = "open", None
            proj = l.project
            # 용량 타입(size) 우선 해석 → 라벨, 없으면 레거시 server 매칭
            prof = find_profile_by_size(profiles, l.jupyterhub_size) or find_profile(profiles, l.jupyter_server_type)
            allocations.append({
                "ledger_id": l.id,
                "project_code": proj.code if proj else None,
                "project_name": proj.name if proj else None,
                "jupyter_server_type": l.jupyter_server_type,
                "jupyterhub_size": l.jupyterhub_size,
                "size_label": prof.name if prof else None,
                "profile_name": prof.name if prof else None,
                "alloc_vcpu": l.alloc_vcpu,
                "alloc_mem_gb": l.alloc_mem_gb,
                "alloc_gpu": l.alloc_gpu,
                "starts_at": l.starts_at,
                "expires_at": l.expires_at,
                "days_to_expiry": days,
                "expiry_state": state,
                "access_state": access,
                "days_to_start": days_to_start,
            })
            my["vcpu"] += l.alloc_vcpu or 0
            my["mem_gb"] += l.alloc_mem_gb or 0
            my["gpu"] += l.alloc_gpu or 0

        overall_active = self.repo.list_ledgers_by_statuses(("active",))
        overall = {
            "vcpu": round(sum((l.alloc_vcpu or 0) for l in overall_active), 2),
            "mem_gb": round(sum((l.alloc_mem_gb or 0) for l in overall_active), 2),
            "gpu": sum((l.alloc_gpu or 0) for l in overall_active),
        }
        return {
            "allocations": allocations,
            "my_totals": {"vcpu": round(my["vcpu"], 2), "mem_gb": round(my["mem_gb"], 2), "gpu": my["gpu"]},
            "overall_totals": overall,
            "profiles": [p.model_dump() for p in profiles],
        }

    # ── 산정서 승인 / 배분 검증 ──────────────────────────────────────────────
    def approve_estimate(self, estimate_id: int) -> CapacityEstimate:
        est = self.repo.get_estimate(estimate_id)
        if not est:
            raise ValueError("산정서를 찾을 수 없습니다.")
        est.status = "approved"
        self.repo.save()
        self.db.refresh(est)
        return est

    def assert_allocatable(self, ledger: ResourceLedger) -> None:
        """자원 배분 승인/활성 전 검증 — 필수값만(오토스케일링: 산정서 한도 검증 제거)."""
        if ledger.alloc_vcpu is None or ledger.alloc_mem_gb is None:
            raise ValueError("vCPU·메모리 용량을 입력하세요.")
        if not ledger.assigned_to:
            raise ValueError("대상 사용자를 지정하세요.")
        if not ledger.starts_at or not ledger.expires_at:
            raise ValueError("시작일과 만료일을 지정하세요.")
        if ledger.starts_at > ledger.expires_at:
            raise ValueError("시작일이 만료일보다 늦을 수 없습니다.")

    def my_ledgers(self, user: UserRead, dt_from=None, dt_to=None) -> list[dict]:
        """본인 과제들의 전체 자원 대장(라이프사이클) + 과제명/만료/접근상태."""
        projects = self.list_my_projects(user)
        pmap = {p.id: p for p in projects}
        today = date.today()
        out: list[dict] = []
        for l in self.repo.list_ledgers_for_projects(list(pmap.keys())):
            cd = l.created_at.date() if l.created_at else None
            if dt_from and (cd is None or cd < dt_from):
                continue
            if dt_to and (cd is None or cd > dt_to):
                continue
            proj = pmap.get(l.project_id)
            read = self.to_ledger_read(l).model_dump(mode="json")
            read["project_code"] = proj.code if proj else None
            read["project_name"] = proj.name if proj else None
            if l.status == "active" and l.starts_at and l.starts_at > today:
                read["access_state"] = "upcoming"
            elif l.status == "active":
                read["access_state"] = "open"
            else:
                read["access_state"] = None
            out.append(read)
        return out

    def pending_requests(self) -> list[dict]:
        """관리자 승인 대기(submitted) 큐 — 과제명·신청자·요청 사양."""
        out: list[dict] = []
        for l in self.repo.list_ledgers_for_queue(("submitted",)):
            proj = l.project
            read = self.to_ledger_read(l).model_dump(mode="json")
            read["project_code"] = proj.code if proj else None
            read["project_name"] = proj.name if proj else None
            read["requester"] = l.recorded_by
            read["request_note"] = l.request_note
            out.append(read)
        return out
