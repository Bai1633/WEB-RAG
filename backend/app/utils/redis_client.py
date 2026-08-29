"""Redis client with connection pool singleton."""

from __future__ import annotations

import redis.asyncio as redis

from app.config import get_settings

_settings = get_settings()

_redis_client: redis.Redis | None = None


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
            socket_connect_timeout=5,
            socket_timeout=5,
        )
    return _redis_client


async def close_redis() -> None:
    """Close the Redis connection pool."""
    global _redis_client
    if _redis_client is not None:
        await _redis_client.close()
        _redis_client = None
