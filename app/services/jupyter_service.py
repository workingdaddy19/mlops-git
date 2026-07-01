"""JupyterHub 서비스 — on-demand 토큰 발급, 서버 자동 시작.

JupyterHub 2.x RBAC scope 참고:
  /hub/token 페이지에서 확인된 scope 포맷: access:servers!server={username}/
  관리자 API로 사용자 토큰 발급 시 동일 포맷 사용
"""
import json
import logging
from datetime import datetime, timedelta, UTC
import jwt  # PyJWT

import httpx
from sqlalchemy.orm import Session

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class JupyterService:
    def __init__(self, db: Session | None = None):
        settings = get_settings()

        if db is not None:
            from app.services.settings_service import SettingsService
            svc = SettingsService(db)
            self.admin_token = svc.get("JUPYTERHUB_ADMIN_TOKEN", settings.jupyterhub_admin_token)
            self.base_url = svc.get("JUPYTER_BASE_URL", settings.jupyter_base_url)
            self.jwt_secret = svc.get("JUPYTERHUB_JWT_SECRET", settings.jupyterhub_jwt_secret)
            envs_json     = svc.get("JUPYTER_ENVS", settings.jupyter_envs)
        else:
            self.admin_token = settings.jupyterhub_admin_token
            self.base_url = settings.jupyter_base_url
            self.jwt_secret = settings.jupyterhub_jwt_secret
            envs_json     = settings.jupyter_envs

        self.base_url = self.base_url.rstrip("/")
        try:
            self.envs_config: list[dict] = json.loads(envs_json)
        except (json.JSONDecodeError, ValueError):
            self.envs_config = [
                {"name": "CPU 환경", "server": ""},
                {"name": "GPU 환경", "server": "gpu"},
            ]

    @staticmethod
    def _get_setting(db: Session, key: str, fallback: str) -> str:
        try:
            from app.models.system_settings import SystemSetting
            row = db.get(SystemSetting, key)
            if row and row.value:
                return row.value
        except Exception as exc:
            logger.warning("DB setting read failed key=%s: %s", key, exc)
        return fallback

    def _http_client(self) -> httpx.AsyncClient:
        """httpx 클라이언트 — 내부망 자체서명 인증서 허용."""
        return httpx.AsyncClient(verify=False, timeout=10)

    # ──────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────

    async def get_user_envs(self) -> list[dict]:
        """Jupyter 환경 목록 반환 (토큰 미포함)."""
        return [
            {
                "name":            env.get("name", env.get("server") or "기본"),
                "server":          env.get("server", ""),
                "token_available": bool(self.admin_token),
            }
            for env in self.envs_config
        ]

    async def get_token_url(self, username: str, server: str = "", size: str = "") -> dict:
        """버튼 클릭 시 SSO JWT 발급 → JupyterHub 접속 URL 반환.

        JupyterHub jwtauthenticator가 ``/hub/login?token=<JWT>`` 의 token을
        get_argument("token")으로 읽어 로그인하고, spawner가 payload의
        ``jupyterhub_size`` 클레임으로 프리셋 용량을 스폰한다.
        → payload 자체가 인증정보이므로 admin API 토큰 발급/서버 선시작은 불필요
          (로그인 후 Hub가 자동 스폰). 로컬 실증 확인(2026-07-01).

        Returns:
          url   - ?token=<JWT> 포함된 JupyterHub 로그인 URL
          error - 실패 사유 (성공 시 "")
        """
        # SSO JWT payload — iat: jwtauthenticator 발급시각 검증 / exp 15분: clock skew 허용
        now = datetime.now(UTC)
        payload = {
            "username": username,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=15)).timestamp()),
        }
        if size:
            payload["jupyterhub_size"] = size   # 용량 타입 클레임 (small/medium/large)

        def _direct_lab_url() -> str:
            lab_path = f"/user/{username}/{server}/lab" if server else f"/user/{username}/lab"
            return f"{self.base_url}{lab_path}"

        if not self.jwt_secret:
            logger.warning("JUPYTERHUB_JWT_SECRET 미설정 — SSO 토큰 생략, 직접 접속 URL 반환")
            return {"url": _direct_lab_url(), "error": "JWT 시크릿 미설정"}

        try:
            sso_jwt = jwt.encode(payload, self.jwt_secret, algorithm="HS256")
        except Exception as e:
            logger.error("Failed to generate JWT: %s", e)
            return {"url": _direct_lab_url(), "error": str(e)}

        # jwtauthenticator가 top-level token을 읽어 로그인 → spawner가 클레임으로 프리셋 스폰
        return {"url": f"{self.base_url}/hub/login?token={sso_jwt}", "error": ""}

    async def get_hub_stats(self) -> dict:
        """JupyterHub 사용자/서버 현황."""
        if not self.admin_token:
            return {"running_servers": 0, "total_users": 0, "available": False}
        try:
            async with self._http_client() as client:
                resp = await client.get(
                    f"{self.base_url}/hub/api/users",
                    headers={"Authorization": f"token {self.admin_token}"},
                )
            if resp.status_code != 200:
                return {"running_servers": 0, "total_users": 0, "available": False}
            users   = resp.json()
            total   = len(users)
            running = sum(
                1 for u in users
                if u.get("servers") and any(
                    s.get("ready") for s in u["servers"].values()
                )
            )
            return {"running_servers": running, "total_users": total, "available": True}
        except Exception as exc:
            logger.warning("JupyterHub stats error: %s", exc)
            return {"running_servers": 0, "total_users": 0, "available": False}

    async def check_health(self) -> bool:
        try:
            headers = {}
            if self.admin_token:
                headers["Authorization"] = f"token {self.admin_token}"
            async with self._http_client() as client:
                resp = await client.get(
                    f"{self.base_url}/hub/api/",
                    headers=headers,
                )
                return resp.status_code in (200, 401)
        except Exception:
            return False

    async def validate_token(self, token: str) -> dict | None:
        """토큰 유효성 검증."""
        if not self.admin_token:
            return None
        try:
            async with self._http_client() as client:
                resp = await client.get(
                    f"{self.base_url}/hub/api/authorizations/token/{token}",
                    headers={"Authorization": f"token {self.admin_token}"},
                )
            return resp.json() if resp.status_code == 200 else None
        except Exception as exc:
            logger.warning("token validation error: %s", exc)
            return None

    def get_lab_url(self, username: str = "admin", server: str = "") -> str:
        if server:
            return f"{self.base_url}/user/{username}/{server}/lab"
        return f"{self.base_url}/user/{username}/lab"

    # admin_token은 get_hub_stats/validate_token/check_health(관리자 조회)에서만 사용.
    # 사용자 접속(get_token_url)은 SSO JWT(top-level token)만으로 로그인·스폰되므로
    # 별도 admin API 토큰 발급/서버 선시작 헬퍼는 두지 않는다.
