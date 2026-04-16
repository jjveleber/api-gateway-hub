import pytest
from testcontainers.redis import RedisContainer
from redis import asyncio as aioredis

from app.services.cache_service import CacheService
from app.services.rate_limiter import RateLimiter
from app.integrations.base import RateLimitExceeded


@pytest.fixture(scope="module")
def redis_container():
    """Start Redis container for tests."""
    with RedisContainer("redis:7.2") as redis:
        yield redis


@pytest.fixture
async def redis_client(redis_container):
    """Create Redis client connected to test container."""
    host = redis_container.get_container_host_ip()
    port = redis_container.get_exposed_port(6379)
    redis_url = f"redis://{host}:{port}/0"
    client = await aioredis.from_url(redis_url, encoding="utf-8", decode_responses=True)

    yield client

    # Cleanup
    await client.flushdb()
    await client.aclose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cache_service_real_redis(redis_client):
    """Test cache service with real Redis container."""
    cache = CacheService(redis_client)

    # Set cache
    await cache.set("openweather", {"city": "London"}, {"temp": 15.2}, ttl=60)

    # Get cache - should hit
    data = await cache.get("openweather", {"city": "London"})
    assert data == {"temp": 15.2}

    # Different params - should miss
    data = await cache.get("openweather", {"city": "Paris"})
    assert data is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cache_expiry(redis_client):
    """Test cache TTL expiration."""
    cache = CacheService(redis_client)

    # Set with 1 second TTL
    await cache.set("test", {"key": "value"}, {"data": "test"}, ttl=1)

    # Should exist immediately
    data = await cache.get("test", {"key": "value"})
    assert data == {"data": "test"}

    # Wait for expiry
    import asyncio
    await asyncio.sleep(1.1)

    # Should be expired
    data = await cache.get("test", {"key": "value"})
    assert data is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_rate_limiter_real_redis(redis_client):
    """Test rate limiter with real Redis container."""
    limiter = RateLimiter(redis_client)

    # First 3 requests should pass
    for i in range(3):
        result = await limiter.check_limit("testapi", limit=5)
        assert result is True

    # Check usage
    usage = await limiter.get_usage("testapi")
    assert usage == 3


@pytest.mark.integration
@pytest.mark.asyncio
async def test_rate_limiter_exceeds_limit(redis_client):
    """Test rate limiter blocks when limit exceeded."""
    limiter = RateLimiter(redis_client)

    # Make requests up to limit
    for i in range(5):
        await limiter.check_limit("limitedapi", limit=5)

    # Next request should be blocked
    with pytest.raises(RateLimitExceeded) as exc_info:
        await limiter.check_limit("limitedapi", limit=5)

    assert "limitedapi" in str(exc_info.value)
    assert "5" in str(exc_info.value)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cache_delete(redis_client):
    """Test deleting cached entries."""
    cache = CacheService(redis_client)

    # Set cache
    await cache.set("test", {"id": 1}, {"result": "data"}, ttl=60)

    # Verify exists
    data = await cache.get("test", {"id": 1})
    assert data is not None

    # Delete
    await cache.delete("test", {"id": 1})

    # Verify deleted
    data = await cache.get("test", {"id": 1})
    assert data is None
