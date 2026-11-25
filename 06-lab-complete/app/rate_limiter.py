"""Rate limiting (tiêu chí 7) — sliding window 60s lưu trong Redis."""
import threading
import time
import uuid
from collections import defaultdict, deque

from fastapi import HTTPException
from redis.exceptions import RedisError

from app.config import settings
from app.redis_client import r

WINDOW_SECONDS = 60.0
_memory_lock = threading.Lock()
_memory_windows: dict[str, deque[float]] = defaultdict(deque)


def check_rate_limit(key: str) -> None:
    """Giới hạn số request trong 60 giây theo từng API key; vượt -> HTTP 429."""
    limit = settings.rate_limit_per_minute
    now = time.time()
    window_start = now - WINDOW_SECONDS

    if r is not None:
        redis_key = f"ratelimit:{key}"
        try:
            pipe = r.pipeline()
            pipe.zremrangebyscore(redis_key, 0, window_start)
            pipe.zcard(redis_key)
            _, count = pipe.execute()

            if int(count) >= limit:
                raise HTTPException(
                    status_code=429,
                    detail="Rate limit exceeded",
                    headers={"Retry-After": "60"},
                )

            pipe = r.pipeline()
            pipe.zadd(redis_key, {f"{now}:{uuid.uuid4().hex}": now})
            pipe.expire(redis_key, 65)
            pipe.execute()
            return
        except HTTPException:
            raise
        except RedisError as exc:
            raise HTTPException(
                status_code=503,
                detail="Rate limiter storage unavailable",
            ) from exc

    with _memory_lock:
        window = _memory_windows[key]
        while window and window[0] < window_start:
            window.popleft()
        if len(window) >= limit:
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded",
                headers={"Retry-After": "60"},
            )
        window.append(now)
