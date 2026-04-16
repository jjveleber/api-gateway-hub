from datetime import date
from redis import asyncio as aioredis
from app.integrations.base import RateLimitExceeded


class RateLimiter:
    """Redis-based rate limiter per API."""

    def __init__(self, redis: aioredis.Redis):
        self.redis = redis

    async def check_limit(self, api: str, limit: int) -> bool:
        """Check if API rate limit exceeded."""
        key = f"ratelimit:{api}:{date.today()}"
        count = await self.redis.incr(key)

        if count == 1:  # First request today
            await self.redis.expire(key, 86400)  # Reset at midnight

        if count > limit:
            raise RateLimitExceeded(f"{api} daily limit ({limit}) exceeded")

        return True

    async def get_usage(self, api: str) -> int:
        """Get current usage count for API."""
        key = f"ratelimit:{api}:{date.today()}"
        count = await self.redis.get(key)
        return int(count) if count else 0

    async def reset(self, api: str):
        """Reset rate limit for API (for testing)."""
        key = f"ratelimit:{api}:{date.today()}"
        await self.redis.delete(key)
