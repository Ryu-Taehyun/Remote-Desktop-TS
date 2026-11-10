"""실제 PostgreSQL 에 대해 실행되는 통합 테스트.

    TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/remote_desktop_test pytest
"""
import base64
import os
import uuid

os.environ["DATABASE_URL"] = os.getenv(
    "TEST_DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/remote_desktop_test"
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from server.db import Base, engine, init_db  # noqa: E402
from server.main import app  # noqa: E402


@pytest.fixture(autouse=True, scope="module")
def fresh_db():
    init_db()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


client = TestClient(app)


def signup(name: str) -> dict:
    r = client.post("/api/auth/signup", json={
        "email": f"{name}-{uuid.uuid4().hex[:6]}@example.com", "username": name, "password": "password123",
    })
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"} | {"_email": r.json()["user"]["email"]}


def h(user: dict) -> dict:
    return {"Authorization": user["Authorization"]}


def test_auth_flow():
    u = signup("alice")
    r = client.post("/api/auth/login", json={"email": u["_email"], "password": "password123"})
    assert r.status_code == 200
    assert client.post("/api/auth/login", json={"email": u["_email"], "password": "wrong"}).status_code == 401
    assert client.get("/api/auth/me", headers=h(u)).json()["username"] == "alice"
    assert client.get("/api/auth/me").status_code == 401
    # 중복 가입
    assert client.post("/api/auth/signup", json={"email": u["_email"], "username": "xx", "password": "password123"}).status_code == 409


def test_rejects_unknown_fields_and_types():
    r = client.post("/api/auth/signup", json={"email": "a@b.com", "username": "ab", "password": "password123", "admin": True})
    assert r.status_code == 422
    r = client.post("/api/auth/signup", json={"email": "not-an-email", "username": "ab", "password": "password123"})
    assert r.status_code == 422


def test_full_remote_session():
    host, viewer, stranger = signup("host"), signup("viewer"), signup("stranger")

    s = client.post("/api/sessions", json={"name": "Office PC"}, headers=h(host)).json()
    sid, code = s["id"], s["access_code"]
    assert s["online"] is False and s["allow_control"] is False

    # 참여 전에는 접근 불가
    assert client.get(f"/api/sessions/{sid}/frame", headers=h(viewer)).status_code == 403
    j = client.post("/api/sessions/join", json={"access_code": code.lower()}, headers=h(viewer)).json()
    assert j["id"] == sid and j["access_code"] is None and j["is_owner"] is False

    # 아직 프레임 없음
    assert client.get(f"/api/sessions/{sid}/frame", headers=h(viewer)).status_code == 204

    img = base64.b64encode(b"\xff\xd8fakejpeg").decode()
    frame = {"width": 1920, "height": 1080, "mime": "image/jpeg", "data_b64": img}
    assert client.put(f"/api/sessions/{sid}/frame", json=frame, headers=h(viewer)).status_code == 403
    ack = client.put(f"/api/sessions/{sid}/frame", json=frame, headers=h(host)).json()
    assert ack == {"seq": 1, "allow_control": False}
    assert client.put(f"/api/sessions/{sid}/frame", json=frame, headers=h(host)).json()["seq"] == 2

    f = client.get(f"/api/sessions/{sid}/frame?after=0", headers=h(viewer)).json()
    assert f["seq"] == 2 and f["data_b64"] == img
    assert client.get(f"/api/sessions/{sid}/frame?after=2", headers=h(viewer)).status_code == 204
    assert client.get(f"/api/sessions/{sid}", headers=h(viewer)).json()["online"] is True

    events = {"events": [
        {"type": "mouse_move", "x": 0.5, "y": 0.5},
        {"type": "mouse_down", "x": 0.5, "y": 0.5, "button": "left"},
        {"type": "key_down", "key": "a", "code": "KeyA"},
    ]}
    # 제어 미허용
    assert client.post(f"/api/sessions/{sid}/input", json=events, headers=h(viewer)).status_code == 403
    client.patch(f"/api/sessions/{sid}", json={"allow_control": True}, headers=h(host))
    assert client.post(f"/api/sessions/{sid}/input", json=events, headers=h(viewer)).status_code == 200
    # 정의되지 않은 이벤트 타입/범위 밖 좌표는 거부
    bad = {"events": [{"type": "shell_exec", "cmd": "rm -rf /"}]}
    assert client.post(f"/api/sessions/{sid}/input", json=bad, headers=h(viewer)).status_code == 422
    bad = {"events": [{"type": "mouse_move", "x": 2, "y": 0}]}
    assert client.post(f"/api/sessions/{sid}/input", json=bad, headers=h(viewer)).status_code == 422

    assert client.get(f"/api/sessions/{sid}/input", headers=h(viewer)).status_code == 403
    drained = client.get(f"/api/sessions/{sid}/input", headers=h(host)).json()["events"]
    assert [e["type"] for e in drained] == ["mouse_move", "mouse_down", "key_down"]
    assert client.get(f"/api/sessions/{sid}/input", headers=h(host)).json()["events"] == []

    # 관계없는 사용자
    assert client.get(f"/api/sessions/{sid}", headers=h(stranger)).status_code == 403
    assert [x["id"] for x in client.get("/api/sessions", headers=h(viewer)).json()] == [sid]

    assert client.delete(f"/api/sessions/{sid}", headers=h(host)).status_code == 200
    assert client.get(f"/api/sessions/{sid}", headers=h(viewer)).status_code == 404


# ---------------------------------------------------------------- WebSocket 실시간 모드
import json  # noqa: E402

JPEG = b"\xff\xd8\xff\xe0fake-jpeg-bytes"


def ws_recv(ws, want: str, pred=lambda m: True, limit: int = 20):
    """원하는 종류(bytes 또는 메시지 type)가 올 때까지 수신."""
    for _ in range(limit):
        m = ws.receive()
        if m.get("bytes") is not None:
            if want == "bytes":
                return m["bytes"]
            continue
        if m.get("text") is not None:
            msg = json.loads(m["text"])
            if msg["type"] == want and pred(msg):
                return msg
        if m["type"] == "websocket.close":
            raise AssertionError(f"closed while waiting for {want}")
    raise AssertionError(f"did not receive {want}")


def test_websocket_realtime():
    host, viewer = signup("wshost"), signup("wsviewer")
    s = client.post("/api/sessions", json={"name": "WS PC"}, headers=h(host)).json()
    sid = s["id"]
    client.post("/api/sessions/join", json={"access_code": s["access_code"]}, headers=h(viewer))
    htok = host["Authorization"].split()[1]
    vtok = viewer["Authorization"].split()[1]

    # 인증 실패
    with client.websocket_connect(f"/api/ws/view/{sid}") as bad:
        bad.send_text(json.dumps({"type": "auth", "token": "nope"}))
        assert ws_recv(bad, "error")["detail"] == "인증이 필요합니다"
    # 뷰어는 호스트 소켓에 붙을 수 없음
    with client.websocket_connect(f"/api/ws/host/{sid}") as bad:
        bad.send_text(json.dumps({"type": "auth", "token": vtok}))
        assert ws_recv(bad, "error")["detail"] == "세션 소유자만 가능합니다"

    with client.websocket_connect(f"/api/ws/host/{sid}") as hws, client.websocket_connect(f"/api/ws/view/{sid}") as vws:
        hws.send_text(json.dumps({"type": "auth", "token": htok}))
        assert ws_recv(hws, "status")["allow_control"] is False
        vws.send_text(json.dumps({"type": "auth", "token": vtok}))
        ws_recv(vws, "status")

        # 프레임: 호스트 → 뷰어 (DB 미경유)
        hws.send_text(json.dumps({"type": "frame_meta", "width": 1280, "height": 720}))
        hws.send_bytes(JPEG)
        assert ws_recv(vws, "bytes") == JPEG
        # JPEG 이 아닌 바이너리 / 정의되지 않은 텍스트는 거부
        hws.send_bytes(b"MZ-not-a-jpeg")
        assert "JPEG" in ws_recv(hws, "error")["detail"]
        hws.send_text(json.dumps({"type": "shell_exec", "cmd": "whoami"}))
        ws_recv(hws, "error")

        # HTTP 폴링 뷰어도 WebSocket 호스트의 프레임을 받음
        f = client.get(f"/api/sessions/{sid}/frame", headers=h(viewer)).json()
        assert base64.b64decode(f["data_b64"]) == JPEG and f["width"] == 1280
        assert client.get(f"/api/sessions/{sid}/frame?after={f['seq']}", headers=h(viewer)).status_code == 204

        # 제어 미허용 시 입력 거부
        move = {"type": "input", "events": [{"type": "mouse_move", "x": 0.1, "y": 0.2}]}
        vws.send_text(json.dumps(move))
        assert "허용" in ws_recv(vws, "error")["detail"]

        # 허용하면 호스트에 즉시 상태 알림, 입력이 바로 전달됨
        client.patch(f"/api/sessions/{sid}", json={"allow_control": True}, headers=h(host))
        ws_recv(hws, "status", lambda m: m["allow_control"] is True)
        vws.send_text(json.dumps(move))
        got = ws_recv(hws, "input")
        assert got["events"] == [{"type": "mouse_move", "x": 0.1, "y": 0.2}]
        # 잘못된 이벤트는 호스트까지 가지 않음
        vws.send_text(json.dumps({"type": "input", "events": [{"type": "mouse_move", "x": 5, "y": 0}]}))
        ws_recv(vws, "error")

        # HTTP 로 보낸 입력도 WebSocket 호스트에 바로 전달 (DB 큐에 쌓이지 않음)
        r = client.post(f"/api/sessions/{sid}/input", json={"events": [{"type": "key_down", "key": "a", "code": "KeyA"}]},
                        headers=h(viewer))
        assert r.status_code == 200
        assert ws_recv(hws, "input")["events"][0]["key"] == "a"
        assert client.get(f"/api/sessions/{sid}/input", headers=h(host)).json()["events"] == []

        # 세션 종료 시 양쪽 모두 알림
        client.delete(f"/api/sessions/{sid}", headers=h(host))
        assert "종료" in ws_recv(hws, "error")["detail"]
        assert "종료" in ws_recv(vws, "error")["detail"]
