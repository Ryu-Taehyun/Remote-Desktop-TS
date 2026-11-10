"""송수신 타입 정의. web/src/protocol.ts 및 agent/protocol.py 와 1:1 로 대응한다.

모든 모델은 extra="forbid" 이므로 정의되지 않은 필드는 422 로 거부된다.
"""
import uuid
from datetime import datetime
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------- 인증 ----------
class SignupRequest(Strict):
    email: EmailStr
    username: str = Field(min_length=2, max_length=50)
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(Strict):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserOut(Strict):
    id: uuid.UUID
    email: EmailStr
    username: str
    created_at: datetime


class TokenResponse(Strict):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    user: UserOut


# ---------- 세션 ----------
class SessionCreate(Strict):
    name: str = Field(min_length=1, max_length=100)
    allow_control: bool = False


class SessionUpdate(Strict):
    allow_control: bool


class SessionOut(Strict):
    id: uuid.UUID
    name: str
    access_code: str | None  # 소유자에게만 노출
    allow_control: bool
    online: bool
    is_owner: bool
    created_at: datetime


class JoinRequest(Strict):
    access_code: str = Field(min_length=4, max_length=12)


# ---------- 화면 프레임 ----------
class FrameUpload(Strict):
    width: int = Field(gt=0, le=8192)
    height: int = Field(gt=0, le=8192)
    mime: Literal["image/jpeg", "image/png", "image/webp"]
    data_b64: str


class FrameOut(Strict):
    seq: int
    width: int
    height: int
    mime: Literal["image/jpeg", "image/png", "image/webp"]
    data_b64: str


class FrameAck(Strict):
    seq: int
    allow_control: bool


# ---------- 입력 이벤트 (뷰어 → 호스트) ----------
# 좌표는 화면 크기에 대한 0~1 정규화 값
Coord = Annotated[float, Field(ge=0.0, le=1.0)]
MouseButton = Literal["left", "right", "middle"]


class MouseMove(Strict):
    type: Literal["mouse_move"]
    x: Coord
    y: Coord


class MouseButtonEvent(Strict):
    type: Literal["mouse_down", "mouse_up"]
    x: Coord
    y: Coord
    button: MouseButton


class MouseWheel(Strict):
    type: Literal["wheel"]
    dx: int = Field(ge=-50, le=50)
    dy: int = Field(ge=-50, le=50)


class KeyEvent(Strict):
    type: Literal["key_down", "key_up"]
    key: str = Field(min_length=1, max_length=32)  # KeyboardEvent.key
    code: str = Field(max_length=32)  # KeyboardEvent.code


InputEventPayload = Annotated[
    Union[MouseMove, MouseButtonEvent, MouseWheel, KeyEvent],
    Field(discriminator="type"),
]


class InputBatch(Strict):
    events: list[InputEventPayload] = Field(min_length=1, max_length=200)


class InputBatchOut(Strict):
    events: list[InputEventPayload]


class Ok(Strict):
    ok: Literal[True] = True
