"""Vercel Python 서버리스 함수 엔트리포인트. /api/* 요청이 모두 여기로 라우팅된다."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.main import app  # noqa: E402

__all__ = ["app"]
