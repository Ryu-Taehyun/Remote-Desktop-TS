"""setup.bat 에서 호출: PostgreSQL 접속 확인 → remote_desktop DB 생성 → 필요하면 .env 에 DATABASE_URL 저장.

    python scripts/setup_db.py [--yes]

비밀번호는 다음 순서로 시도한다: 환경 변수 RD_PG_PASSWORD → 기존 .env 의 DATABASE_URL → "postgres".
모두 실패하면 (대화형일 때) 화면에 표시되지 않는 입력으로 최대 3번 물어본다.

종료 코드: 0 성공 · 2 비밀번호 불일치 · 3 PostgreSQL 에 연결할 수 없음
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys
import time
import urllib.parse
from pathlib import Path

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
DB_NAME = "remote_desktop"
DEFAULT_PASSWORD = "postgres"
HOST, PORT = "127.0.0.1", 5432


class AuthFailed(Exception):
    pass


class ServerDown(Exception):
    pass


def try_connect(password: str, dbname: str = "postgres") -> psycopg.Connection:
    try:
        return psycopg.connect(host=HOST, port=PORT, user="postgres", password=password, dbname=dbname,
                               connect_timeout=5, autocommit=True)
    except psycopg.OperationalError as e:
        text = str(e).lower()
        # 한국어 Windows 에서는 메시지가 깨져도 "password" 단어는 그대로 남는다
        if getattr(e, "sqlstate", None) in ("28P01", "28000") or "password" in text or "authentication" in text:
            raise AuthFailed() from e
        raise ServerDown(str(e).splitlines()[0] if str(e) else type(e).__name__) from e


def env_password() -> str | None:
    """기존 .env 의 DATABASE_URL 에서 비밀번호 추출."""
    try:
        for line in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
            if line.strip().startswith("DATABASE_URL="):
                url = urllib.parse.urlsplit(line.split("=", 1)[1].strip().strip('"'))
                return urllib.parse.unquote(url.password) if url.password else None
    except OSError:
        pass
    return None


def write_env(password: str) -> None:
    """.env 의 DATABASE_URL 만 교체하고 나머지 줄은 그대로 둔다."""
    url = f"postgresql://postgres:{urllib.parse.quote(password, safe='')}@{HOST}:{PORT}/{DB_NAME}"
    lines: list[str] = []
    if ENV_FILE.exists():
        lines = [ln for ln in ENV_FILE.read_text(encoding="utf-8-sig").splitlines()
                 if not ln.strip().startswith("DATABASE_URL=")]
    lines.insert(0, f"DATABASE_URL={url}")
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true", help="묻지 않고 진행 (자동 설치/CI)")
    args = ap.parse_args()

    candidates: list[str] = []
    for pw in (os.getenv("RD_PG_PASSWORD"), env_password(), DEFAULT_PASSWORD):
        if pw and pw not in candidates:
            candidates.append(pw)

    # PostgreSQL 서비스가 막 시작된 경우를 위해 최대 30초 기다린다
    deadline, password, conn, last_down = time.monotonic() + 30, None, None, ""
    while conn is None:
        down = False
        for pw in candidates:
            try:
                conn, password = try_connect(pw), pw
                break
            except AuthFailed:
                continue
            except ServerDown as e:
                down, last_down = True, str(e)
                break
        if conn is not None or not down:
            break
        if time.monotonic() > deadline:
            print(f"  [오류] PostgreSQL({HOST}:{PORT})에 연결할 수 없습니다: {last_down}")
            print("         PostgreSQL 서비스가 실행 중인지 확인하세요 (services.msc → postgresql-x64-…).")
            return 3
        time.sleep(1)

    if conn is None:
        if args.yes or not sys.stdin.isatty():
            print("  [오류] postgres 계정 비밀번호가 맞지 않습니다. RD_PG_PASSWORD 환경 변수로 지정하세요.")
            return 2
        print("  postgres 계정 비밀번호가 'postgres' 가 아닙니다.")
        for _ in range(3):
            pw = getpass.getpass("  PostgreSQL 설치 때 정한 postgres 비밀번호 (입력이 화면에 표시되지 않음): ")
            try:
                conn, password = try_connect(pw), pw
                break
            except AuthFailed:
                print("  비밀번호가 맞지 않습니다.")
            except ServerDown as e:
                print(f"  [오류] PostgreSQL 에 연결할 수 없습니다: {e}")
                return 3
        if conn is None:
            return 2

    assert password is not None
    with conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DB_NAME,)).fetchone()
        if exists:
            print(f"  데이터베이스 '{DB_NAME}' 이미 있음")
        else:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(DB_NAME)))
            print(f"  데이터베이스 '{DB_NAME}' 생성 완료")

    if password != DEFAULT_PASSWORD or env_password() not in (None, DEFAULT_PASSWORD):
        write_env(password)
        print("  접속 정보를 .env 에 저장했습니다 (git 에는 올라가지 않음)")
    print("  PostgreSQL 준비 완료")
    return 0


if __name__ == "__main__":
    sys.exit(main())
