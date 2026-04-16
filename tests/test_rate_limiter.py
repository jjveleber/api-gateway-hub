import pytest
from unittest.mock import AsyncMock
from datetime import date

from app.services.rate_limiter import RateLimiter
from app.integrations.base import RateLimitExceeded


@pytest.mark.asyncio
async def test_rate_limiter_allows_within_limit():
    """Test rate limiter allows requests within limit."""
    redis_mock = AsyncMock()
    redis_mock.incr.return_value = 5  # 5th request
    redis_mock.expire.return_value = None

    limiter = RateLimiter(redis_mock)
    result = await limiter.check_limit("openweather", limit=1000)

    assert result is True
    redis_mock.incr.assert_called_once_with(f"ratelimit:openweather:{date.today()}")


@pytest.mark.asyncio
async def test_rate_limiter_blocks_over_limit():
    """Test rate limiter blocks requests over limit."""
    redis_mock = AsyncMock()
    redis_mock.incr.return_value = 1001  # Exceeded limit

    limiter = RateLimiter(redis_mock)

    with pytest.raises(RateLimitExceeded) as exc_info:
        await limiter.check_limit("openweather", limit=1000)

    assert "openweather" in str(exc_info.value)
    assert "1000" in str(exc_info.value)


@pytest.mark.asyncio
async def test_rate_limiter_sets_expiry_on_first_request():
    """Test rate limiter sets 24h expiry on first request."""
    redis_mock = AsyncMock()
    redis_mock.incr.return_value = 1  # First request

    limiter = RateLimiter(redis_mock)
    await limiter.check_limit("openweather", limit=1000)

    redis_mock.expire.assert_called_once_with(
        f"ratelimit:openweather:{date.today()}", 86400
    )


@pytest.mark.asyncio
async def test_rate_limiter_get_usage():
    """Test getting current usage count."""
    redis_mock = AsyncMock()
    redis_mock.get.return_value = "42"

    limiter = RateLimiter(redis_mock)
    usage = await limiter.get_usage("openweather")

    assert usage == 42
