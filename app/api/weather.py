from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime
import uuid
import logging

from app.schemas import APIResponse
from app.services.cache_service import CacheService
from app.services.rate_limiter import RateLimiter
from app.dependencies import get_cache, get_rate_limiter
from app.integrations.openweather import OpenWeatherClient
from app.integrations.base import RateLimitExceeded

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/weather", response_model=APIResponse)
async def get_weather(
    city: str,
    cache: CacheService = Depends(get_cache),
    rate_limiter: RateLimiter = Depends(get_rate_limiter),
):
    """Get weather data for a city."""
    request_id = str(uuid.uuid4())
    api_name = "openweather"
    params = {"city": city}

    # Check cache first
    cached_data = await cache.get(api_name, params)
    if cached_data:
        logger.info(f"Cache hit for {api_name} - {city}")
        return APIResponse(
            source=api_name,
            data=cached_data,
            cached=True,
            cached_at=datetime.now(),
            request_id=request_id,
        )

    # Check rate limit
    try:
        client = OpenWeatherClient()
        await rate_limiter.check_limit(api_name, client.rate_limit)
    except RateLimitExceeded:
        logger.warning(f"Rate limit exceeded for {api_name}, checking stale cache")
        # Try to return stale cache
        if cached_data:
            return APIResponse(
                source=api_name,
                data=cached_data,
                cached=True,
                cached_at=datetime.now(),
                request_id=request_id,
            )
        raise HTTPException(
            status_code=429, detail=f"{api_name} rate limit exceeded, no cache available"
        )

    # Fetch from API
    try:
        client = OpenWeatherClient()
        data = await client.fetch(city=city)

        # Cache result
        await cache.set(api_name, params, data, ttl=client.cache_ttl)

        logger.info(f"API call successful for {api_name} - {city}")
        return APIResponse(
            source=api_name,
            data=data,
            cached=False,
            cached_at=None,
            request_id=request_id,
        )

    except Exception as e:
        logger.error(f"API call failed for {api_name}: {e}")
        # Try to return stale cache
        if cached_data:
            return APIResponse(
                source=api_name,
                data=cached_data,
                cached=True,
                cached_at=datetime.now(),
                request_id=request_id,
            )
        raise HTTPException(status_code=503, detail=f"{api_name} unavailable: {str(e)}")
