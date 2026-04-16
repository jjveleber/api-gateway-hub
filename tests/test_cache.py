import pytest
from unittest.mock import AsyncMock, MagicMock

from app.services.cache_service import CacheService


@pytest.mark.asyncio
async def test_cache_service_set_and_get():
    """Test cache service stores and retrieves data."""
    # Mock Redis client
    redis_mock = AsyncMock()
    redis_mock.get.return_value = '{"temperature": 20}'
    redis_mock.setex.return_value = None

    cache = CacheService(redis_mock)

    # Set cache
    await cache.set("openweather", {"city": "London"}, {"temperature": 20}, ttl=900)
    redis_mock.setex.assert_called_once()

    # Get cache
    data = await cache.get("openweather", {"city": "London"})
    assert data == {"temperature": 20}


@pytest.mark.asyncio
async def test_cache_service_cache_key_generation():
    """Test cache key generation is consistent."""
    redis_mock = AsyncMock()
    cache = CacheService(redis_mock)

    # Same params should generate same key
    key1 = cache._cache_key("openweather", {"city": "London", "units": "metric"})
    key2 = cache._cache_key("openweather", {"units": "metric", "city": "London"})

    assert key1 == key2  # Order shouldn't matter


@pytest.mark.asyncio
async def test_cache_service_miss():
    """Test cache miss returns None."""
    redis_mock = AsyncMock()
    redis_mock.get.return_value = None

    cache = CacheService(redis_mock)
    data = await cache.get("openweather", {"city": "Paris"})

    assert data is None
