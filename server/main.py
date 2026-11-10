from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from .config import CORS_ORIGINS, WEB_DIST
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


# 빌드된 웹 화면(web/dist)을 같은 서버에서 제공 → http://<서버IP>:8000 하나로 접속.
# API 라우트를 모두 등록한 뒤 마지막에 마운트해야 /api 가 우선한다.
if (WEB_DIST / "index.html").is_file():
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
else:
    @app.get("/", include_in_schema=False)
    def no_web() -> JSONResponse:
        return JSONResponse({"detail": "웹 화면이 빌드되지 않았습니다. web 폴더에서 npm install && npm run build 를 실행하세요."})
