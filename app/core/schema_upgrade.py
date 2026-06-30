"""경량 스키마 보강 (Alembic 미사용 — create_all 보완).

`Base.metadata.create_all`은 '없는 테이블'만 생성하고 **기존 테이블에 컬럼을 추가하지 않는다.**
모델에 새 컬럼을 추가하면 기존 DB와 스키마가 어긋나 조회 시 'column does not exist'로 기동이 실패한다.
이 함수는 기동 시 누락 컬럼만 idempotent하게 ADD COLUMN 한다(신규 테이블은 create_all이 처리).
"""
import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

# 기존 테이블에 나중에 추가된 컬럼들: (table, column) -> 컬럼 DDL 타입/기본값
# 신규 테이블 전체는 create_all이 생성하므로 여기 넣지 않는다.
_ADDED_COLUMNS = [
    ("users", "department", "VARCHAR(100)"),
    ("users", "must_change_password", "BOOLEAN NOT NULL DEFAULT {false}"),
    ("resource_ledgers", "request_note", "VARCHAR(500)"),
    ("resource_ledgers", "assigned_to", "VARCHAR(50)"),
    ("resource_ledgers", "starts_at", "DATE"),
    ("resource_ledgers", "jupyterhub_size", "VARCHAR(20)"),
    ("capacity_estimates", "status", "VARCHAR(20) NOT NULL DEFAULT 'pending'"),
]


def ensure_schema_upgrades(engine: Engine) -> None:
    insp = inspect(engine)
    existing_tables = set(insp.get_table_names())
    false_literal = "false" if engine.dialect.name == "postgresql" else "0"

    for table, column, ddl in _ADDED_COLUMNS:
        if table not in existing_tables:
            continue  # create_all이 새로 만들 테이블 — 보강 불필요
        cols = {c["name"] for c in insp.get_columns(table)}
        if column in cols:
            continue
        type_ddl = ddl.format(false=false_literal)
        stmt = f"ALTER TABLE {table} ADD COLUMN {column} {type_ddl}"
        try:
            with engine.begin() as conn:
                conn.execute(text(stmt))
            logger.info("schema upgrade applied: %s.%s", table, column)
        except Exception:  # noqa: BLE001 — 보강 실패가 기동을 막지 않게 로깅만
            logger.warning("schema upgrade failed: %s.%s", table, column, exc_info=True)
