from redis import asyncio as aioredis
from app.services.cache_service import CacheService
from app.services.rate_limiter import RateLimiter
from app.config import settings

_redis_client = None


async def get_redis() -> aioredis.Redis:
    """Get Redis client (singleton)."""
    global _redis_client
    if _redis_client is None:
        _redis_client = await aioredis.from_url(
            settings.redis_url, encoding="utf-8", decode_responses=True
        )
    return _redis_client


async def get_cache() -> CacheService:
    """Get cache service."""
    redis = await get_redis()
    return CacheService(redis)


async def get_rate_limiter() -> RateLimiter:
    """Get rate limiter."""
    redis = await get_redis()
    return RateLimiter(redis)
