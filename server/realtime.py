"""WebSocket 실시간 중계 (상시 실행 서버용: uvicorn).

프레임은 DB 를 거치지 않고 메모리에서 바로 뷰어에게 전달되며, 뷰어가 느리면
중간 프레임은 버리고 항상 최신 프레임만 보낸다. 프록시·방화벽 등으로 WebSocket 이
막힌 환경에서는 클라이언트가 자동으로 HTTP 폴링(routers/sessions.py)으로 전환한다.

주의: 상태가 프로세스 메모리에 있으므로 uvicorn 워커는 1개로 실행해야 한다.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from .config import HOST_TIMEOUT_SECONDS, MAX_FRAME_BYTES
from .db import SessionLocal, init_db
from .models import InputEvent, RemoteSession, SessionViewer
from .schemas import WsAuth, WsError, WsFrameMeta, WsInput, WsStatus
from .security import user_from_token

router = APIRouter()

_JPEG_MAGIC = b"\xff\xd8"


class Peer:
    """WebSocket 하나. 여러 태스크/스레드에서 안전하게 보낼 수 있도록 잠금과 루프를 함께 보관."""

    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.loop = asyncio.get_running_loop()
        self.lock = asyncio.Lock()

    async def send_text(self, text: str) -> None:
        async with self.lock:
            await self.ws.send_text(text)

    async def send_bytes(self, data: bytes) -> None:
        async with self.lock:
            await self.ws.send_bytes(data)

    async def send_text_any(self, text: str) -> None:
        """어느 이벤트 루프에서 호출해도 안전한 전송."""
        if asyncio.get_running_loop() is self.loop:
            await self.send_text(text)
        else:
            await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(self.send_text(text), self.loop))

    def send_text_threadsafe(self, text: str, timeout: float = 2.0) -> bool:
        """동기 코드(HTTP 엔드포인트 스레드)에서 호출."""
        try:
            asyncio.run_coroutine_threadsafe(self.send_text(text), self.loop).result(timeout)
            return True
        except Exception:  # noqa: BLE001 — 연결이 이미 끊긴 경우 등
            return False

    def close_threadsafe(self, code: int = 1000) -> None:
        try:
            asyncio.run_coroutine_threadsafe(self.ws.close(code), self.loop)
        except RuntimeError:
            pass


@dataclass
class Viewer:
    peer: Peer
    wake: asyncio.Event = field(default_factory=asyncio.Event)


@dataclass
class Room:
    frame: bytes | None = None
    seq: int = 0
    width: int = 1
    height: int = 1
    last_frame_at: float = 0.0
    allow_control: bool = False
    host: Peer | None = None
    viewers: dict[int, Viewer] = field(default_factory=dict)

    def host_online(self) -> bool:
        return self.host is not None or time.monotonic() - self.last_frame_at < HOST_TIMEOUT_SECONDS

    def status(self) -> str:
        return WsStatus(
            type="status", allow_control=self.allow_control, host_online=self.host_online(), viewers=len(self.viewers)
        ).model_dump_json()


class Hub:
    def __init__(self) -> None:
        self.rooms: dict[uuid.UUID, Room] = {}

    def room(self, sid: uuid.UUID) -> Room:
        return self.rooms.setdefault(sid, Room())

    def get(self, sid: uuid.UUID) -> Room | None:
        return self.rooms.get(sid)

    def cleanup(self, sid: uuid.UUID) -> None:
        r = self.rooms.get(sid)
        if r and r.host is None and not r.viewers:
            self.rooms.pop(sid, None)

    def publish(self, sid: uuid.UUID, data: bytes, width: int | None = None, height: int | None = None) -> None:
        """새 프레임 등록 후 대기 중인 뷰어를 깨운다. 어느 스레드에서 호출해도 된다."""
        r = self.rooms.get(sid)
        if r is None:
            return
        r.frame, r.seq, r.last_frame_at = data, r.seq + 1, time.monotonic()
        if width and height:
            r.width, r.height = width, height
        for v in list(r.viewers.values()):
            try:
                v.peer.loop.call_soon_threadsafe(v.wake.set)
            except RuntimeError:
                pass

    # ----- HTTP 엔드포인트(동기 스레드)에서 쓰는 알림 -----
    def notify_control(self, sid: uuid.UUID, allow: bool) -> None:
        r = self.rooms.get(sid)
        if r is None:
            return
        r.allow_control = allow
        status = r.status()
        for peer in [r.host, *(v.peer for v in r.viewers.values())]:
            if peer is not None:
                peer.send_text_threadsafe(status)

    def push_input_threadsafe(self, sid: uuid.UUID, msg: WsInput) -> bool:
        r = self.rooms.get(sid)
        return bool(r and r.host and r.host.send_text_threadsafe(msg.model_dump_json()))

    def close_room(self, sid: uuid.UUID, reason: str) -> None:
        r = self.rooms.pop(sid, None)
        if r is None:
            return
        err = WsError(type="error", detail=reason).model_dump_json()
        for peer in [r.host, *(v.peer for v in r.viewers.values())]:
            if peer is not None:
                peer.send_text_threadsafe(err)
                peer.close_threadsafe(1000)


hub = Hub()


# ---------- DB 작업 (스레드풀에서 실행) ----------
class _Denied(Exception):
    pass


def _authorize(token: str, sid: uuid.UUID, role: str) -> bool:
    """권한 확인 후 현재 allow_control 값을 반환."""
    init_db()
    with SessionLocal() as db:
        user = user_from_token(db, token)
        if user is None:
            raise _Denied("인증이 필요합니다")
        s = db.get(RemoteSession, sid)
        if s is None or not s.active:
            raise _Denied("세션을 찾을 수 없습니다")
        if role == "host" and s.owner_id != user.id:
            raise _Denied("세션 소유자만 가능합니다")
        if role == "viewer" and s.owner_id != user.id:
            joined = db.scalar(
                select(SessionViewer.id).where(SessionViewer.session_id == sid, SessionViewer.user_id == user.id)
            )
            if joined is None:
                raise _Denied("접속 코드로 먼저 참여하세요")
        return s.allow_control


def _touch(sid: uuid.UUID) -> bool:
    """호스트 접속 상태 갱신. 세션이 종료됐으면 False."""
    from datetime import datetime, timezone

    with SessionLocal() as db:
        s = db.get(RemoteSession, sid)
        if s is None or not s.active:
            return False
        s.last_seen = datetime.now(timezone.utc)
        db.commit()
        return True


def _enqueue_input(sid: uuid.UUID, msg: WsInput) -> None:
    with SessionLocal() as db:
        db.add_all(InputEvent(session_id=sid, payload=e.model_dump()) for e in msg.events)
        db.commit()


async def _handshake(ws: WebSocket, sid: uuid.UUID, role: str) -> tuple[Peer, bool] | None:
    await ws.accept()
    peer = Peer(ws)
    try:
        auth = WsAuth.model_validate_json(await asyncio.wait_for(ws.receive_text(), timeout=10))
        allow = await run_in_threadpool(_authorize, auth.token, sid, role)
        return peer, allow
    except (ValidationError, asyncio.TimeoutError, _Denied, WebSocketDisconnect, KeyError) as e:
        detail = str(e) if isinstance(e, _Denied) else "인증 메시지가 올바르지 않습니다"
        try:
            await peer.send_text(WsError(type="error", detail=detail).model_dump_json())
            await ws.close(1008)
        except Exception:  # noqa: BLE001
            pass
        return None


@router.websocket("/api/ws/host/{session_id}")
async def ws_host(ws: WebSocket, session_id: uuid.UUID) -> None:
    hs = await _handshake(ws, session_id, "host")
    if hs is None:
        return
    peer, allow = hs
    room = hub.room(session_id)
    old, room.host, room.allow_control = room.host, peer, allow
    if old is not None:  # 같은 세션에 호스트가 다시 붙으면 이전 연결을 끊는다
        old.close_threadsafe(4000)
    await run_in_threadpool(_touch, session_id)
    await peer.send_text(room.status())
    last_touch = time.monotonic()
    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            data, text = msg.get("bytes"), msg.get("text")
            if data is not None:
                if not data.startswith(_JPEG_MAGIC) or len(data) > MAX_FRAME_BYTES:
                    await peer.send_text(WsError(type="error", detail="JPEG 프레임만 허용됩니다").model_dump_json())
                    continue
                hub.publish(session_id, data)
            elif text is not None:
                try:
                    meta = WsFrameMeta.model_validate_json(text)
                    room.width, room.height = meta.width, meta.height
                except ValidationError:
                    await peer.send_text(WsError(type="error", detail="알 수 없는 메시지").model_dump_json())
            now = time.monotonic()
            if now - last_touch > 5:
                last_touch = now
                if not await run_in_threadpool(_touch, session_id):
                    await peer.send_text(WsError(type="error", detail="세션이 종료되었습니다").model_dump_json())
                    break
    except WebSocketDisconnect:
        pass
    finally:
        if room.host is peer:
            room.host = None
        hub.cleanup(session_id)


@router.websocket("/api/ws/view/{session_id}")
async def ws_view(ws: WebSocket, session_id: uuid.UUID) -> None:
    hs = await _handshake(ws, session_id, "viewer")
    if hs is None:
        return
    peer, allow = hs
    room = hub.room(session_id)
    if room.host is None:
        room.allow_control = allow
    viewer = Viewer(peer)
    room.viewers[id(viewer)] = viewer
    if room.frame is not None:
        viewer.wake.set()

    async def send_frames() -> None:
        sent = -1
        while True:
            await viewer.wake.wait()
            viewer.wake.clear()
            if room.frame is not None and room.seq != sent:
                sent = room.seq
                await peer.send_bytes(room.frame)  # 항상 최신 프레임만 (느린 뷰어는 중간 프레임을 건너뜀)

    async def send_status() -> None:
        while True:
            await peer.send_text(room.status())
            await asyncio.sleep(2)

    tasks = [asyncio.create_task(send_frames()), asyncio.create_task(send_status())]
    try:
        while True:
            text = await ws.receive_text()
            try:
                msg = WsInput.model_validate_json(text)
            except ValidationError:
                await peer.send_text(WsError(type="error", detail="허용되지 않은 메시지 형식입니다").model_dump_json())
                continue
            if not room.allow_control:
                await peer.send_text(WsError(type="error", detail="호스트가 원격 제어를 허용하지 않았습니다").model_dump_json())
                continue
            if room.host is not None:
                await room.host.send_text_any(msg.model_dump_json())
            else:  # HTTP 폴링 호스트용 큐
                await run_in_threadpool(_enqueue_input, session_id, msg)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        for t in tasks:
            t.cancel()
        room.viewers.pop(id(viewer), None)
        hub.cleanup(session_id)
