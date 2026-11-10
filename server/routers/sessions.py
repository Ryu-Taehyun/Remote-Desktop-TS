import base64
import binascii
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ..config import HOST_TIMEOUT_SECONDS, MAX_FRAME_BYTES
from ..db import get_db
from ..models import Frame, InputEvent, RemoteSession, SessionViewer, User
from ..schemas import (
    FrameAck, FrameOut, FrameUpload, InputBatch, InputBatchOut, JoinRequest, Ok,
    SessionCreate, SessionOut, SessionUpdate,
)
from ..security import current_user

router = APIRouter(prefix="/api/sessions", tags=["sessions"])

_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # 헷갈리는 0/O, 1/I 제외


def _new_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))


def _online(s: RemoteSession) -> bool:
    if not s.active or s.last_seen is None:
        return False
    return datetime.now(timezone.utc) - s.last_seen < timedelta(seconds=HOST_TIMEOUT_SECONDS)


def _out(s: RemoteSession, user: User) -> SessionOut:
    owner = s.owner_id == user.id
    return SessionOut(
        id=s.id, name=s.name, access_code=s.access_code if owner else None,
        allow_control=s.allow_control, online=_online(s), is_owner=owner, created_at=s.created_at,
    )


def _get_session(db: Session, session_id: uuid.UUID) -> RemoteSession:
    s = db.get(RemoteSession, session_id)
    if s is None or not s.active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "세션을 찾을 수 없습니다")
    return s


def _require_owner(db: Session, session_id: uuid.UUID, user: User) -> RemoteSession:
    s = _get_session(db, session_id)
    if s.owner_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "세션 소유자만 가능합니다")
    return s


def _require_member(db: Session, session_id: uuid.UUID, user: User) -> RemoteSession:
    s = _get_session(db, session_id)
    if s.owner_id == user.id:
        return s
    joined = db.scalar(
        select(SessionViewer.id).where(SessionViewer.session_id == s.id, SessionViewer.user_id == user.id)
    )
    if joined is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "접속 코드로 먼저 참여하세요")
    return s


# ---------- 세션 관리 ----------
@router.post("", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
def create_session(body: SessionCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = RemoteSession(owner_id=user.id, name=body.name, allow_control=body.allow_control, access_code=_new_code())
    db.add(s)
    db.commit()
    db.refresh(s)
    return _out(s, user)


@router.get("", response_model=list[SessionOut])
def list_sessions(user: User = Depends(current_user), db: Session = Depends(get_db)):
    viewer_ids = select(SessionViewer.session_id).where(SessionViewer.user_id == user.id)
    rows = db.scalars(
        select(RemoteSession)
        .where(RemoteSession.active, (RemoteSession.owner_id == user.id) | RemoteSession.id.in_(viewer_ids))
        .order_by(RemoteSession.created_at.desc())
    ).all()
    return [_out(s, user) for s in rows]


@router.post("/join", response_model=SessionOut)
def join_session(body: JoinRequest, user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = db.scalar(
        select(RemoteSession).where(RemoteSession.access_code == body.access_code.strip().upper(), RemoteSession.active)
    )
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "유효하지 않은 접속 코드입니다")
    if s.owner_id != user.id:
        db.execute(insert(SessionViewer).values(session_id=s.id, user_id=user.id).on_conflict_do_nothing())
        db.commit()
    return _out(s, user)


@router.get("/{session_id}", response_model=SessionOut)
def get_session(session_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _out(_require_member(db, session_id, user), user)


@router.patch("/{session_id}", response_model=SessionOut)
def update_session(
    session_id: uuid.UUID, body: SessionUpdate, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    s = _require_owner(db, session_id, user)
    s.allow_control = body.allow_control
    if not body.allow_control:
        db.execute(delete(InputEvent).where(InputEvent.session_id == s.id))
    db.commit()
    return _out(s, user)


@router.delete("/{session_id}", response_model=Ok)
def end_session(session_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = _require_owner(db, session_id, user)
    s.active = False
    db.execute(delete(Frame).where(Frame.session_id == s.id))
    db.execute(delete(InputEvent).where(InputEvent.session_id == s.id))
    db.commit()
    return Ok()


# ---------- 화면 프레임 (호스트 → 서버 → 뷰어) ----------
@router.put("/{session_id}/frame", response_model=FrameAck)
def upload_frame(
    session_id: uuid.UUID, body: FrameUpload, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    s = _require_owner(db, session_id, user)
    try:
        data = base64.b64decode(body.data_b64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "data_b64 가 올바른 base64 가 아닙니다")
    if len(data) > MAX_FRAME_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "프레임이 너무 큽니다")

    stmt = insert(Frame).values(
        session_id=s.id, seq=1, width=body.width, height=body.height, mime=body.mime, data=data
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[Frame.session_id],
        set_={
            "seq": Frame.seq + 1, "width": stmt.excluded.width, "height": stmt.excluded.height,
            "mime": stmt.excluded.mime, "data": stmt.excluded.data, "updated_at": stmt.excluded.updated_at,
        },
    ).returning(Frame.seq)
    seq = db.execute(stmt).scalar_one()
    s.last_seen = datetime.now(timezone.utc)
    db.commit()
    return FrameAck(seq=seq, allow_control=s.allow_control)


@router.get("/{session_id}/frame", response_model=FrameOut, responses={204: {"description": "새 프레임 없음"}})
def get_frame(
    session_id: uuid.UUID,
    after: int = Query(0, ge=0, description="이미 받은 마지막 seq. 같거나 작으면 204"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    s = _require_member(db, session_id, user)
    f = db.get(Frame, s.id)
    if f is None or f.seq <= after:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    return FrameOut(seq=f.seq, width=f.width, height=f.height, mime=f.mime, data_b64=base64.b64encode(f.data).decode())


# ---------- 입력 이벤트 (뷰어 → 서버 → 호스트) ----------
@router.post("/{session_id}/input", response_model=Ok)
def send_input(
    session_id: uuid.UUID, body: InputBatch, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    s = _require_member(db, session_id, user)
    if not s.allow_control:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "호스트가 원격 제어를 허용하지 않았습니다")
    db.add_all(InputEvent(session_id=s.id, payload=e.model_dump()) for e in body.events)
    db.commit()
    return Ok()


@router.get("/{session_id}/input", response_model=InputBatchOut)
def drain_input(session_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """호스트 전용: 대기 중인 입력 이벤트를 가져오고 큐에서 삭제한다."""
    s = _require_owner(db, session_id, user)
    rows = db.execute(
        delete(InputEvent).where(InputEvent.session_id == s.id).returning(InputEvent.id, InputEvent.payload)
    ).all()
    db.commit()
    if not s.allow_control:
        return InputBatchOut(events=[])
    rows.sort(key=lambda r: r[0])
    return InputBatchOut.model_validate({"events": [r[1] for r in rows]})
