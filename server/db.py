"""DB 엔진/세션. 서버리스 환경에서는 커넥션을 유지할 수 없으므로 NullPool 사용."""
import os
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import NullPool

from .config import DATABASE_URL

_serverless = bool(os.getenv("VERCEL"))
engine = create_engine(
    DATABASE_URL,
    poolclass=NullPool if _serverless else None,
    pool_pre_ping=True,
    # DB 가 꺼져 있거나 주소가 틀리면 무한정 기다리지 않고 5초 안에 실패
    connect_args={"connect_timeout": 5},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


_initialized = False


def init_db() -> None:
    """테이블이 없으면 생성 (콜드 스타트마다 1회)."""
    global _initialized
    if _initialized:
        return
    from . import models  # noqa: F401  (모델 등록)

    Base.metadata.create_all(engine)
    _initialized = True


def get_db() -> Iterator[Session]:
    init_db()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
