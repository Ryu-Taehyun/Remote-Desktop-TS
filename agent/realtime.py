"""WebSocket 실시간 전송 클라이언트 (서버가 지원하지 않으면 connect 가 None 을 반환)."""
from __future__ import annotations

from pydantic import TypeAdapter, ValidationError
from websockets.exceptions import WebSocketException
from websockets.sync.client import ClientConnection, connect

from .protocol import WsAuth, WsError, WsFrameMeta, WsServerMessage, WsStatus

_server_msg = TypeAdapter(WsServerMessage)


class RealtimeHost:
    def __init__(self, conn: ClientConnection, status: WsStatus):
        self.conn = conn
        self.status = status
        self._size: tuple[int, int] | None = None

    @classmethod
    def connect(cls, base_url: str, token: str, session_id: str, timeout: float = 4.0) -> RealtimeHost | None:
        url = base_url.rstrip("/").replace("https://", "wss://", 1).replace("http://", "ws://", 1)
        try:
            # JPEG 은 이미 압축돼 있으므로 WebSocket 압축은 끔 (CPU 절약)
            conn = connect(f"{url}/api/ws/host/{session_id}", open_timeout=timeout, compression=None,
                           max_size=4 * 1024 * 1024)
        except (OSError, WebSocketException, TimeoutError):
            return None
        try:
            conn.send(WsAuth(type="auth", token=token).model_dump_json())
            first = _server_msg.validate_json(conn.recv(timeout=timeout))
        except (OSError, WebSocketException, TimeoutError, ValidationError):
            conn.close()
            return None
        if isinstance(first, WsError) or not isinstance(first, WsStatus):
            conn.close()
            return None
        return cls(conn, first)

    def send_frame(self, jpeg: bytes, width: int, height: int) -> None:
        if self._size != (width, height):
            self.conn.send(WsFrameMeta(type="frame_meta", width=width, height=height).model_dump_json())
            self._size = (width, height)
        self.conn.send(jpeg)

    def recv(self, timeout: float):
        """WsInput | WsStatus | WsError | None(시간 초과). 연결이 끊기면 예외."""
        try:
            raw = self.conn.recv(timeout=timeout)
        except TimeoutError:
            return None
        if isinstance(raw, bytes):
            return None
        try:
            return _server_msg.validate_json(raw)
        except ValidationError:
            return None  # 정의되지 않은 메시지는 무시

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:  # noqa: BLE001
            pass
