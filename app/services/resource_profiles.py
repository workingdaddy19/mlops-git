"""자원 프로파일 카탈로그 — JupyterHub 환경(named server)에 자원 사양 메타를 결합.

소스: Settings `JUPYTER_ENVS`(JupyterService.envs_config와 동일). 스키마 확장:
  [{"name":"표준 CPU","server":"","vcpu":4,"mem_gb":16,"gpu":0}, ...]
누락 필드는 None/0. `server`는 JupyterHub named server 키 = ResourceLedger.jupyter_server_type 매핑 키.
실제 sizing은 JupyterHub profile_list(인프라)가 수행하고, 포탈은 선택지/표시만 담당한다.
"""
import json
import logging

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class ResourceProfile(BaseModel):
    name: str
    server: str = ""
    vcpu: float | None = None
    mem_gb: float | None = None
    gpu: int | None = None


_DEFAULT: list[ResourceProfile] = [
    ResourceProfile(name="CPU 환경", server="", vcpu=4, mem_gb=16, gpu=0),
    ResourceProfile(name="GPU 환경", server="gpu", vcpu=8, mem_gb=32, gpu=1),
]


def load_profiles(db: Session | None = None) -> list[ResourceProfile]:
    """JUPYTER_ENVS 파싱 → 프로파일 목록. 실패 시 기본값."""
    if db is not None:
        from app.services.settings_service import SettingsService
        raw = SettingsService(db).get("JUPYTER_ENVS", get_settings().jupyter_envs)
    else:
        raw = get_settings().jupyter_envs
    try:
        data = json.loads(raw)
        profiles = [ResourceProfile(**item) for item in data]
        return profiles or list(_DEFAULT)
    except Exception:  # noqa: BLE001 — 파싱 실패가 기능을 막지 않게
        logger.warning("JUPYTER_ENVS 파싱 실패 — 기본 프로파일 사용", exc_info=True)
        return list(_DEFAULT)


def find_profile(profiles: list[ResourceProfile], server: str | None) -> ResourceProfile | None:
    target = server or ""
    return next((p for p in profiles if (p.server or "") == target), None)
