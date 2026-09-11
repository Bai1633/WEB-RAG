"""Redis client with connection pool singleton."""

from __future__ import annotations

import time

import redis.asyncio as redis

from app.config import get_settings

_settings = get_settings()

_redis_client: redis.Redis | None = None

# ---------------------------------------------------------------------------
# Circuit breaker
#
# Every call site fails open when Redis is unreachable, which is the correct
# behaviour. But with a 5s socket timeout, "fail open" still cost 5 SECONDS of
# wall time per request (visible in logs as elapsed_ms=5016).
#
# The breaker short-circuits the whole Redis round trip for `cooldown` seconds
# after the first failure, so a dead Redis degrades to ~0ms instead of
# stalling the entire request path.
# ---------------------------------------------------------------------------
_REDIS_COOLDOWN_SECONDS = 10.0
_redis_unavailable_until: float = 0.0


def is_redis_available() -> bool:
    """Return False while the circuit breaker is open."""
    return time.monotonic() >= _redis_unavailable_until


def mark_redis_unavailable(cooldown: float = _REDIS_COOLDOWN_SECONDS) -> None:
    """Open the circuit breaker for `cooldown` seconds after a Redis failure."""
    global _redis_unavailable_until
    _redis_unavailable_until = time.monotonic() + cooldown


def mark_redis_available() -> None:
    """Close the circuit breaker once Redis answers again."""
    global _redis_unavailable_until
    _redis_unavailable_until = 0.0


def get_redis() -> redis.Redis:
    """Get or create the Redis client (singleton).

    Returns:
        Async Redis client instance.
    """
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(
            _settings.redis_url,
            max_connections=_settings.redis_pool_size,
            decode_responses=True,
            # Fail fast: callers fail open, so a dead Redis must not stall
            # the request for seconds. 0.5s is enough for a local/LAN Redis.
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
            retry_on_timeout=False,
        )
    return _redis_client


async def close_redis() -> None:
    """Close the Redis connection pool."""
    global _redis_client
    if _redis_client is not None:
        await _redis_client.close()
        _redis_client = None
