"""Sliding-window rate limiter: Redis when available (shared across
workers), in-process memory otherwise."""

import time
import uuid
from collections import defaultdict, deque

from app.services.redis_client import get_redis, mark_down


class RateLimiter:
    def __init__(self) -> None:
        self._mem: dict[str, deque] = defaultdict(deque)

    async def allow(self, key: str, limit: int, window_s: int) -> bool:
        """Record an attempt and return whether it is within `limit`
        attempts per `window_s` seconds. Refused attempts are not counted."""
        redis = await get_redis()
        if redis is not None:
            try:
                now = time.time()
                member = f"{now}:{uuid.uuid4().hex[:8]}"
                rkey = f"rl:{key}"
                pipe = redis.pipeline(transaction=True)
                pipe.zremrangebyscore(rkey, 0, now - window_s)
                pipe.zadd(rkey, {member: now})
                pipe.zcard(rkey)
                pipe.expire(rkey, window_s + 1)
                _, _, count, _ = await pipe.execute()
                if count > limit:
                    await redis.zrem(rkey, member)
                    return False
                return True
            except Exception:
                mark_down()
        return self._allow_memory(key, limit, window_s)

    def _allow_memory(self, key: str, limit: int, window_s: int) -> bool:
        now = time.time()
        q = self._mem[key]
        while q and q[0] <= now - window_s:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True

    def reset(self) -> None:
        self._mem.clear()


limiter = RateLimiter()
