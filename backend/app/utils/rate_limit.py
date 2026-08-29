"""Rate limiting using Redis token bucket algorithm."""

from __future__ import annotations

import time

import structlog

from app.utils.redis_client import get_redis

logger = structlog.get_logger()


class RateLimiter:
    """Token bucket rate limiter backed by Redis.

    Uses a sliding window approach with Redis for distributed rate limiting.
    """

    def __init__(
        self,
        max_tokens: int = 100,
        refill_rate: float = 10.0,
        prefix: str = "rate_limit",
    ) -> None:
        """Initialize rate limiter.

        Args:
            max_tokens: Maximum number of tokens (burst capacity).
            refill_rate: Tokens refilled per second.
            prefix: Redis key prefix.
        """
        self.max_tokens = max_tokens
        self.refill_rate = refill_rate
        self.prefix = prefix

    async def allow(self, key: str, tokens_needed: int = 1) -> bool:
        """Check if a request is allowed and consume tokens.

        Args:
            key: Rate limit key (e.g., user_id or IP).
            tokens_needed: Number of tokens to consume.

        Returns:
            True if allowed, False if rate limited.
        """
        redis = get_redis()
        redis_key = f"{self.prefix}:{key}"

        # Use Lua script for atomicity
        script = """
        local key = KEYS[1]
        local max_tokens = tonumber(ARGV[1])
        local refill_rate = tonumber(ARGV[2])
        local tokens_needed = tonumber(ARGV[3])
        local now = tonumber(ARGV[4])

        local data = redis.call('HMGET', key, 'tokens', 'last_refill')
        local tokens = data[1]
        local last_refill = data[2]

        if tokens == false then
            tokens = max_tokens
            last_refill = now
        else
            tokens = tonumber(tokens)
            last_refill = tonumber(last_refill)

            -- Refill tokens
            local elapsed = now - last_refill
            local new_tokens = tokens + elapsed * refill_rate
            tokens = math.min(new_tokens, max_tokens)
        end

        if tokens >= tokens_needed then
            tokens = tokens - tokens_needed
            redis.call('HMSET', key, 'tokens', tokens, 'last_refill', now)
            redis.call('EXPIRE', key, math.ceil(max_tokens / refill_rate) + 60)
            return 1
        else
            return 0
        end
        """

        now = time.time()
        try:
            result = await redis.eval(
                script,
                1,
                redis_key,
                str(self.max_tokens),
                str(self.refill_rate),
                str(tokens_needed),
                str(now),
            )
            return bool(result)
        except Exception as e:
            logger.warning("rate_limit_redis_error", error=str(e), key=key)
            # Fail open - allow request if Redis is down
            return True

    async def get_remaining(self, key: str) -> int:
        """Get remaining tokens for a key.

        Args:
            key: Rate limit key.

        Returns:
            Number of remaining tokens.
        """
        redis = get_redis()
        redis_key = f"{self.prefix}:{key}"

        try:
            data = await redis.hmget(redis_key, "tokens", "last_refill")
            tokens = data[0]
            last_refill = data[1]

            if tokens is None:
                return self.max_tokens

            now = time.time()
            elapsed = now - float(last_refill)
            new_tokens = float(tokens) + elapsed * self.refill_rate
            return int(min(new_tokens, self.max_tokens))
        except Exception as e:
            logger.warning("rate_limit_redis_error", error=str(e), key=key)
            return self.max_tokens


# Default rate limiter instances
default_rate_limiter = RateLimiter(max_tokens=100, refill_rate=10.0, prefix="rl:default")

# User-level rate limiter for chat (10 requests/min burst, 30/min sustained)
chat_rate_limiter = RateLimiter(max_tokens=10, refill_rate=0.5, prefix="rl:chat")

# Upload rate limiter (5 uploads/min burst)
upload_rate_limiter = RateLimiter(max_tokens=5, refill_rate=0.083, prefix="rl:upload")
