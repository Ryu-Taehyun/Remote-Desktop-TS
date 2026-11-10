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
