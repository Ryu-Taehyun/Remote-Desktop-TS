"""FastAPI 서버와 통신하는 타입 안전 HTTP 클라이언트."""
from typing import TypeVar

import requests
from pydantic import BaseModel

from .protocol import (
    FrameAck, FrameUpload, InputBatchOut, LoginRequest, Ok, SessionCreate, SessionOut,
    SessionUpdate, SignupRequest, TokenResponse,
)

T = TypeVar("T", bound=BaseModel)


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class ApiClient:
    def __init__(self, base_url: str, timeout: float = 15.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.token: str | None = None
        self.http = requests.Session()

    def _call(self, method: str, path: str, res: type[T], body: BaseModel | None = None) -> T:
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        r = self.http.request(
            method, self.base_url + path, headers=headers, timeout=self.timeout,
            json=body.model_dump() if body is not None else None,
        )
        if not r.ok:
            try:
                detail = r.json().get("detail")
            except ValueError:
                detail = None
            msg = detail if isinstance(detail, str) else f"요청 실패 ({r.status_code})"
            raise ApiError(r.status_code, msg)
        return res.model_validate(r.json())

    # 인증
    def login(self, email: str, password: str) -> TokenResponse:
        t = self._call("POST", "/api/auth/login", TokenResponse, LoginRequest(email=email, password=password))
        self.token = t.access_token
        return t

    def signup(self, email: str, username: str, password: str) -> TokenResponse:
        t = self._call(
            "POST", "/api/auth/signup", TokenResponse,
            SignupRequest(email=email, username=username, password=password),
        )
        self.token = t.access_token
        return t

    # 세션
    def create_session(self, name: str, allow_control: bool) -> SessionOut:
        return self._call("POST", "/api/sessions", SessionOut, SessionCreate(name=name, allow_control=allow_control))

    def set_control(self, session_id: str, allow: bool) -> SessionOut:
        return self._call("PATCH", f"/api/sessions/{session_id}", SessionOut, SessionUpdate(allow_control=allow))

    def end_session(self, session_id: str) -> Ok:
        return self._call("DELETE", f"/api/sessions/{session_id}", Ok)

    def upload_frame(self, session_id: str, frame: FrameUpload) -> FrameAck:
        return self._call("PUT", f"/api/sessions/{session_id}/frame", FrameAck, frame)

    def drain_input(self, session_id: str) -> InputBatchOut:
        return self._call("GET", f"/api/sessions/{session_id}/input", InputBatchOut)
