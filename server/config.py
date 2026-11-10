"""환경 변수 기반 설정. Vercel/Neon(Postgres) 변수명을 모두 지원한다."""
import os


def _database_url() -> str:
    url = (
        os.getenv("DATABASE_URL")
        or os.getenv("POSTGRES_URL")  # Vercel Postgres / Neon 통합 시 자동 주입
        or "postgresql://postgres:postgres@localhost:5432/remote_desktop"
    )
    # SQLAlchemy 가 psycopg(v3) 드라이버를 쓰도록 스킴 정규화
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


DATABASE_URL = _database_url()
JWT_SECRET = os.getenv("JWT_SECRET", "dev-only-change-me")
if os.getenv("VERCEL") and JWT_SECRET == "dev-only-change-me":
    raise RuntimeError("Vercel 배포 시 JWT_SECRET 환경 변수를 반드시 설정하세요")
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "720"))
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]
# 호스트가 이 시간(초) 동안 프레임을 올리지 않으면 오프라인으로 간주
HOST_TIMEOUT_SECONDS = int(os.getenv("HOST_TIMEOUT_SECONDS", "15"))
# Vercel 서버리스 요청 본문 한도(4.5MB)보다 작게
MAX_FRAME_BYTES = int(os.getenv("MAX_FRAME_BYTES", str(3 * 1024 * 1024)))
