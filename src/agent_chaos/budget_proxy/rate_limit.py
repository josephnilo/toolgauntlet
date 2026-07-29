from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock
from typing import Protocol
from uuid import uuid4


class RateLimiter(Protocol):
    def allow(self, key: str, limit: int, window_seconds: float = 60.0) -> bool: ...


class InMemoryRateLimiter:
    """Simple fixed-window-ish limiter using sliding timestamps per key."""

    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, key: str, limit: int, window_seconds: float = 60.0) -> bool:
        if limit <= 0:
            return False

        now = time.time()
        cutoff = now - window_seconds
        with self._lock:
            bucket = self._events[key]
            while bucket and bucket[0] < cutoff:
                bucket.popleft()

            if len(bucket) >= limit:
                return False

            bucket.append(now)
            return True


_REDIS_SLIDING_WINDOW_LUA = """
local key = KEYS[1]
local now_ms = tonumber(ARGV[1])
local window_ms = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]
local cutoff = now_ms - window_ms

redis.call('ZREMRANGEBYSCORE', key, '-inf', cutoff)
local count = redis.call('ZCARD', key)
if count >= limit then
  return 0
end

redis.call('ZADD', key, now_ms, member)
redis.call('PEXPIRE', key, window_ms)
return 1
"""


class RedisRateLimiter:
    """Distributed sliding-window limiter backed by Redis sorted sets."""

    def __init__(
        self,
        *,
        redis_url: str,
        key_prefix: str = "toolgauntlet_proxy_rl",
        client: object | None = None,
    ) -> None:
        if not redis_url:
            raise ValueError("redis_url is required for RedisRateLimiter")
        self.redis_url = redis_url
        self.key_prefix = key_prefix
        self.client = client or self._build_client(redis_url)

    @staticmethod
    def _build_client(redis_url: str) -> object:
        try:
            import redis
        except ImportError as exc:  # pragma: no cover - depends on optional install
            raise RuntimeError("Redis backend requires 'redis' package. Install with: pip install toolgauntlet[redis]") from exc
        return redis.Redis.from_url(redis_url)

    def allow(self, key: str, limit: int, window_seconds: float = 60.0) -> bool:
        if limit <= 0:
            return False

        now_ms = int(time.time() * 1000)
        window_ms = max(1, int(window_seconds * 1000))
        member = f"{now_ms}:{uuid4().hex}"
        redis_key = f"{self.key_prefix}:{key}"
        result = self.client.eval(
            _REDIS_SLIDING_WINDOW_LUA,
            1,
            redis_key,
            now_ms,
            window_ms,
            limit,
            member,
        )
        try:
            return int(result) == 1
        except (TypeError, ValueError):
            return False


def build_rate_limiter(
    *,
    backend: str = "memory",
    redis_url: str | None = None,
    redis_key_prefix: str = "toolgauntlet_proxy_rl",
) -> RateLimiter:
    mode = (backend or "memory").strip().lower()
    if mode == "memory":
        return InMemoryRateLimiter()
    if mode == "redis":
        if not redis_url:
            raise ValueError("redis_url is required when rate limit backend is 'redis'")
        return RedisRateLimiter(redis_url=redis_url, key_prefix=redis_key_prefix)
    raise ValueError(f"Unsupported rate limit backend: {backend}")
