from functools import lru_cache
from urllib.parse import quote_plus

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = Field(default="AI 데이터 분석", alias="APP_NAME")
    app_port: int = Field(default=6080, alias="APP_PORT")

    # ── 애플리케이션 마스터 키 (환경변수 필수) ───────────────────────
    #   용도: 비밀번호 해시 pepper(salt) + 로그인 JWT 서명 키 (app/core/security.py)
    #   env 이름: APP_SECRET_KEY  (구 이름 SECRET_KEY 도 호환 인식)
    #   ⚠️ 값 변경 금지 — 바뀌면 전 사용자 로그인 불가·토큰 무효
    secret_key: SecretStr = Field(
        validation_alias=AliasChoices("APP_SECRET_KEY", "SECRET_KEY"),
    )

    access_token_ttl_minutes: int = Field(default=480, alias="ACCESS_TOKEN_TTL_MINUTES")

    # ── Database (환경변수 필수) ──────────────────────────────────────
    db_host: str = Field(alias="DB_HOST")
    db_port: int = Field(default=5432, alias="DB_PORT")
    db_name: str = Field(default="mlops", alias="DB_NAME")
    db_user: str = Field(default="mlops", alias="DB_USER")
    db_password: SecretStr = Field(alias="DB_PASSWORD")

    # ── JupyterHub ──────────────────────────────────────────────────
    #   비민감 설정(URL/ENVS)은 코드 기본값 + DB(system_settings)에서 관리.
    #   민감값(ADMIN_TOKEN, JWT_SECRET)은 k8s Secret(env)으로 주입.
    jupyter_base_url: str = Field(default="http://jupyterhub.mlops.click", alias="JUPYTER_BASE_URL")
    jupyter_token: str = Field(default="", alias="JUPYTER_TOKEN")
    jupyterhub_admin_token: str = Field(default="", alias="JUPYTERHUB_ADMIN_TOKEN")
    jupyterhub_jwt_secret: str = Field(default="", alias="JUPYTERHUB_JWT_SECRET")
    jupyter_envs: str = Field(
        # 자원 프로파일 카탈로그 — 사양(vcpu/mem_gb/gpu)은 JupyterHub profile_list와 매칭(인프라 구성 전제).
        default='[{"name":"CPU 환경","server":"","vcpu":4,"mem_gb":16,"gpu":0},'
                '{"name":"GPU 환경","server":"gpu","vcpu":8,"mem_gb":32,"gpu":1}]',
        alias="JUPYTER_ENVS",
    )

    # ── MLFlow UI (외부 접속용) ──────────────────────────────────────
    mlflow_base_url: str = Field(default="http://mlflow.mlops.click", alias="MLFLOW_BASE_URL")

    # ── Kubeflow Pipelines / Katib (Experiments & Pipelines 페이지 링크) ──
    #   비민감 URL — 코드 기본값 + DB(system_settings, 관리자 Settings)에서 관리
    kfp_base_url: str = Field(default="http://kfp.kubeflow.mlops.click/", alias="KFP_BASE_URL")
    katib_base_url: str = Field(default="http://katib.kubeflow.mlops.click/katib/", alias="KATIB_BASE_URL")

    # ── Inference (추론 API 호출 — 별도 Pod의 invest-app 서비스) ──────
    # 포탈은 추론을 자체 처리하지 않고 invest-app(=invest-inference) 서비스를 HTTP 호출만 한다.
    # api.mlops.click 도메인 등록 완료 → 외부 인터넷에서도 직접 호출 가능 (Host 헤더 불필요)
    inference_base_url: str = Field(
        default="http://api.mlops.click/predict",
        alias="INFERENCE_BASE_URL",
    )
    # 도메인 등록 전 ALB Host 라우팅 우회용 (현재는 불필요 → 기본 빈 값)
    inference_default_host: str = Field(default="", alias="INFERENCE_DEFAULT_HOST")
    inference_allowed_hosts: list[str] = Field(default_factory=list, alias="INFERENCE_ALLOWED_HOSTS")

    streamlit_port: int = Field(default=6501, alias="STREAMLIT_PORT")

    # ── AWS Athena ────────────────────────────────────────────────────
    athena_region: str = Field(default="ap-northeast-2", alias="ATHENA_REGION")
    athena_database: str = Field(default="mlops", alias="ATHENA_DATABASE")
    athena_s3_output: str = Field(default="", alias="ATHENA_S3_OUTPUT")

    # ── AWS S3 ────────────────────────────────────────────────────────
    s3_bucket_name: str = Field(default="", alias="S3_BUCKET_NAME")
    s3_region: str = Field(default="ap-northeast-2", alias="S3_REGION")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def sqlalchemy_database_uri(self) -> str:
        password = quote_plus(self.db_password.get_secret_value())
        return (
            f"postgresql+psycopg://{self.db_user}:{password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

