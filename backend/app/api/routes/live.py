"""WebSocket endpoint for live refresh signals. See services/live.py:
messages carry no data, only "refetch these topics"."""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.ownership import can_manage
from app.core.security import decode_access_token
from app.models.event import Event
from app.models.user import User
from app.services.live import Conn, hub

router = APIRouter()


@router.websocket("/ws/live/{event_id}")
async def live(websocket: WebSocket, event_id: str, token: str | None = None):
    organizer = False
    async with AsyncSessionLocal() as db:
        event = (await db.execute(select(Event).where(Event.id == event_id))).scalar_one_or_none()
        if event is None:
            await websocket.close(code=4404)
            return
        if token:
            try:
                uid = decode_access_token(token).get("sub")
                user = (await db.execute(select(User).where(User.id == uid))).scalar_one_or_none()
                organizer = bool(user and can_manage(event, user))
            except Exception:
                organizer = False  # a bad token just means "treat me as the public"

    await websocket.accept()
    conn = Conn(ws=websocket, organizer=organizer)
    hub.register(event_id, conn)
    try:
        while True:
            await websocket.receive_text()  # keep-alive pings from the client
    except WebSocketDisconnect:
        pass
    finally:
        hub.unregister(event_id, conn)
