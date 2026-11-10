from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from fastapi.middleware.cors import CORSMiddleware

from .config import CORS_ORIGINS
from .db import engine
from . import realtime
from .routers import auth, sessions

app = FastAPI(title="Remote Desktop API", version="1.0.0", docs_url="/api/docs", openapi_url="/api/openapi.json")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,  # 토큰은 Authorization 헤더로만 전달
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(sessions.router)
app.include_router(realtime.router)


def _db_error_text(exc: Exception) -> str:
    orig = getattr(exc, "orig", exc)
    return str(orig).strip().splitlines()[0][:300] if str(orig).strip() else type(orig).__name__


@app.exception_handler(OperationalError)
def db_unavailable(_: Request, exc: OperationalError) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={"detail": f"데이터베이스에 연결할 수 없습니다. PostgreSQL 실행 여부와 DATABASE_URL 을 확인하세요. ({_db_error_text(exc)})"},
    )


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/health/db")
def health_db() -> JSONResponse:
    """DB 연결 확인용."""
    try:
        with engine.connect() as conn:
            conn.execute(text("select 1"))
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=503, content={"status": "error", "detail": _db_error_text(e)})
    return JSONResponse({"status": "ok", "database": "connected"})
