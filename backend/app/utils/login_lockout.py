"""Redis-backed login failure lockout — brute-force protection per account.

The counter auto-expires after the window; once ``max_attempts`` consecutive
failures accumulate, the account is locked for the remainder of the window.
Successful login resets the counter.

Fail-open policy: if Redis is unavailable every check passes and login
proceeds unprotected (the global IP rate limiter still applies), consistent
with the rest of the Redis usage in this codebase.
"""

from __future__ import annotations

import structlog

from app.config import get_settings
from app.utils.redis_client import get_redis

logger = structlog.get_logger()
settings = get_settings()

_KEY_PREFIX = "login_fail"


class LoginLockout:
    def __init__(self, max_attempts: int = 5, window_seconds: int = 900) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds

    def _key(self, identifier: str) -> str:
        return f"{_KEY_PREFIX}:{identifier.lower()}"

    async def is_locked(self, identifier: str) -> bool:
        try:
            redis = get_redis()
            count = await redis.get(self._key(identifier))
            return count is not None and int(count) >= self.max_attempts
        except Exception as e:
            logger.warning("login_lockout_unavailable", error=str(e))
            return False

    async def record_failure(self, identifier: str) -> int:
        """Increment the failure counter; returns the new count (0 on Redis error)."""
        try:
            redis = get_redis()
            key = self._key(identifier)
            count = await redis.incr(key)
            if count == 1:
                await redis.expire(key, self.window_seconds)
            return int(count)
        except Exception as e:
            logger.warning("login_lockout_record_failed", error=str(e))
            return 0

    async def reset(self, identifier: str) -> None:
        try:
            redis = get_redis()
            await redis.delete(self._key(identifier))
        except Exception as e:
            logger.warning("login_lockout_reset_failed", error=str(e))


login_lockout = LoginLockout(
    max_attempts=settings.login_max_attempts,
    window_seconds=settings.login_lockout_window_seconds,
)
