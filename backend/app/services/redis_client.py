"""A shared, optional Redis connection. If Redis is unreachable the app
keeps working: rate limiting and live updates fall back to in-process
memory (correct on a single worker, which is how compose runs it)."""

import logging
import time
from typing import Optional

import redis.asyncio as aioredis

from app.core.config import settings

logger = logging.getLogger("launchpad.redis")
_client: Optional[aioredis.Redis] = None
_failed_at = 0.0
RETRY_AFTER_S = 15.0


async def get_redis() -> Optional[aioredis.Redis]:
    global _client, _failed_at
    if _client is not None:
        return _client
    if time.time() - _failed_at < RETRY_AFTER_S:
        return None
    try:
        client = aioredis.from_url(
            settings.redis_url, socket_connect_timeout=1, socket_timeout=2, decode_responses=True
        )
        await client.ping()
        _client = client
        logger.info("Redis connected.")
        return _client
    except Exception:
        _failed_at = time.time()
        logger.warning("Redis unavailable; using in-memory fallback.")
        return None


def mark_down() -> None:
    global _client, _failed_at
    _client = None
    _failed_at = time.time()


async def close_redis() -> None:
    """Close the shared connection cleanly on shutdown."""
    global _client
    if _client is not None:
        try:
            await _client.aclose()
        except Exception:
            pass
        _client = None
