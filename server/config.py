"""환경 변수 기반 설정."""
import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """프로젝트 루트의 .env (KEY=VALUE) 를 읽는다. 이미 설정된 환경 변수는 덮어쓰지 않는다."""
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv(ROOT / ".env")


def _database_url() -> str:
    url = os.getenv("DATABASE_URL") or "postgresql://postgres:postgres@localhost:5432/remote_desktop"
    # SQLAlchemy 가 psycopg(v3) 드라이버를 쓰도록 스킴 정규화
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def _jwt_secret() -> str:
    """JWT_SECRET 이 없으면 랜덤 키를 만들어 .jwt_secret 파일에 저장해 재시작 후에도 로그인이 유지되게 한다."""
    if env := os.getenv("JWT_SECRET"):
        return env
    path = ROOT / ".jwt_secret"
    try:
        if path.exists() and (saved := path.read_text(encoding="utf-8").strip()):
            return saved
        key = secrets.token_urlsafe(48)
        path.write_text(key, encoding="utf-8")
        return key
    except OSError:  # 쓰기 불가한 위치면 프로세스 동안만 유지
        return secrets.token_urlsafe(48)


DATABASE_URL = _database_url()
JWT_SECRET = _jwt_secret()
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "720"))
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]
# 호스트가 이 시간(초) 동안 프레임을 올리지 않으면 오프라인으로 간주
HOST_TIMEOUT_SECONDS = int(os.getenv("HOST_TIMEOUT_SECONDS", "15"))
# 프레임 1장 최대 크기 (1280px, 품질 60 기준 보통 30–150KB)
MAX_FRAME_BYTES = int(os.getenv("MAX_FRAME_BYTES", str(3 * 1024 * 1024)))
# 빌드된 웹(web/dist)을 이 서버가 함께 서비스 (없으면 API 만)
WEB_DIST = Path(os.getenv("WEB_DIST", str(ROOT / "web" / "dist")))
