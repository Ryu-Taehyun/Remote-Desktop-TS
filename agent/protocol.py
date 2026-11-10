"""호스트 앱이 송수신하는 타입. server/schemas.py, web/src/protocol.ts 와 동일 규칙."""
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginRequest(Strict):
    email: str
    password: str


class SignupRequest(Strict):
    email: str
    username: str = Field(min_length=2, max_length=50)
    password: str = Field(min_length=8, max_length=128)


class UserOut(Strict):
    id: str
    email: str
    username: str
    created_at: str


class TokenResponse(Strict):
    access_token: str
    token_type: Literal["bearer"]
    user: UserOut


class SessionCreate(Strict):
    name: str = Field(min_length=1, max_length=100)
    allow_control: bool


class SessionUpdate(Strict):
    allow_control: bool


class SessionOut(Strict):
    id: str
    name: str
    access_code: str | None
    allow_control: bool
    online: bool
    is_owner: bool
    created_at: str


class FrameUpload(Strict):
    width: int
    height: int
    mime: Literal["image/jpeg", "image/png", "image/webp"]
    data_b64: str


class FrameAck(Strict):
    seq: int
    allow_control: bool


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
    key: str = Field(min_length=1, max_length=32)
    code: str = Field(max_length=32)


InputEvent = Annotated[Union[MouseMove, MouseButtonEvent, MouseWheel, KeyEvent], Field(discriminator="type")]


class InputBatchOut(Strict):
    events: list[InputEvent]


class Ok(Strict):
    ok: Literal[True]


# ---------- WebSocket 메시지 (실시간 모드) ----------
class WsAuth(Strict):
    type: Literal["auth"]
    token: str


class WsFrameMeta(Strict):
    type: Literal["frame_meta"]
    width: int
    height: int


class WsInput(Strict):
    type: Literal["input"]
    events: list[InputEvent]


class WsStatus(Strict):
    type: Literal["status"]
    allow_control: bool
    host_online: bool
    viewers: int


class WsError(Strict):
    type: Literal["error"]
    detail: str


WsServerMessage = Annotated[Union[WsInput, WsStatus, WsError], Field(discriminator="type")]
