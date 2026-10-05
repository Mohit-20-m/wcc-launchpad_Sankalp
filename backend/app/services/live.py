"""
Live updates over WebSockets. Messages are only "something changed,
refetch these topics" -- they never carry data, so a WebSocket can't leak
anything the REST API would refuse (the REST endpoints still enforce
every permission). Organizer-only topics are delivered only to
connections that own the event.

Redis pub/sub bridges multiple backend workers; without Redis (or with
one worker) delivery is direct and in-process.
"""

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass

from fastapi import WebSocket

from app.core.config import settings
from app.services.redis_client import get_redis, mark_down

logger = logging.getLogger("launchpad.live")
WORKER_ID = uuid.uuid4().hex
CHANNEL = "launchpad:live"
ORGANIZER_ONLY = {"stats", "submissions", "progress", "audit", "ballots", "conflicts", "similarity"}


@dataclass(eq=False)
class Conn:
    ws: WebSocket
    organizer: bool


class Hub:
    def __init__(self) -> None:
        self.by_event: dict[str, set[Conn]] = {}
        self._task: asyncio.Task | None = None

    def register(self, event_id: str, conn: Conn) -> None:
        self.by_event.setdefault(event_id, set()).add(conn)

    def unregister(self, event_id: str, conn: Conn) -> None:
        conns = self.by_event.get(event_id)
        if conns:
            conns.discard(conn)
            if not conns:
                self.by_event.pop(event_id, None)

    async def _deliver(self, event_id: str, topics: list[str]) -> None:
        for conn in list(self.by_event.get(event_id, ())):
            allowed = [t for t in topics if conn.organizer or t not in ORGANIZER_ONLY]
            if not allowed:
                continue
            try:
                await conn.ws.send_json({"type": "refresh", "event_id": event_id, "topics": allowed})
            except Exception:
                self.unregister(event_id, conn)

    async def publish(self, event_id: str, *topics: str) -> None:
        """Tell everyone watching this event to refetch `topics`."""
        await self._deliver(event_id, list(topics))
        redis = await get_redis()
        if redis is not None:
            try:
                await redis.publish(CHANNEL, json.dumps({"w": WORKER_ID, "e": event_id, "t": list(topics)}))
            except Exception:
                mark_down()

    async def _subscribe_loop(self) -> None:
        import redis.asyncio as aioredis

        while True:
            try:
                client = aioredis.from_url(settings.redis_url, socket_connect_timeout=1, decode_responses=True)
                pubsub = client.pubsub()
                await pubsub.subscribe(CHANNEL)
                async for message in pubsub.listen():
                    if message.get("type") != "message":
                        continue
                    data = json.loads(message["data"])
                    if data.get("w") == WORKER_ID:
                        continue  # already delivered locally
                    await self._deliver(data["e"], data["t"])
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(5)  # Redis down: retry quietly

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._subscribe_loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None


hub = Hub()
