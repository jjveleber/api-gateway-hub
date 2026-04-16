import json
import hashlib
from redis import asyncio as aioredis


class CacheService:
    """Redis-based caching service."""

    def __init__(self, redis: aioredis.Redis):
        self.redis = redis

    def _cache_key(self, api: str, params: dict) -> str:
        """Generate cache key from API name and params."""
        param_str = json.dumps(params, sort_keys=True)
        param_hash = hashlib.md5(param_str.encode()).hexdigest()
        return f"{api}:{param_hash}"

    async def get(self, api: str, params: dict) -> dict | None:
        """Get cached data if exists."""
        key = self._cache_key(api, params)
        data = await self.redis.get(key)
        return json.loads(data) if data else None

    async def set(self, api: str, params: dict, data: dict, ttl: int):
        """Cache data with TTL."""
        key = self._cache_key(api, params)
        await self.redis.setex(key, ttl, json.dumps(data))

    async def delete(self, api: str, params: dict):
        """Delete cached data."""
        key = self._cache_key(api, params)
        await self.redis.delete(key)

    async def clear_all(self):
        """Clear all cached data."""
        await self.redis.flushdb()
