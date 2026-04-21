# API Gateway Hub - Development Guidelines

## Project Type

**Integration Service (Backend-for-Frontend Pattern)**

Aggregates multiple external APIs into unified interface with caching, rate limiting, retry logic, and error handling. BFF pattern for external API orchestration.

## Tech Stack

- FastAPI 0.115 + Python 3.12
- PostgreSQL 16 (request logging)
- Redis 7.2 (caching + rate limiting)
- Celery 5.3 (background tasks)
- httpx (async HTTP)
- Docker

## General Development Guidelines

Behavioral guidelines to reduce common LLM coding mistakes.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

### 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

### 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

## Architecture Principles

### API Client Pattern

```python
from abc import ABC, abstractmethod
from tenacity import retry, stop_after_attempt, wait_exponential
import httpx

class BaseAPIClient(ABC):
    """Abstract base for all external API clients."""
    
    base_url: str
    rate_limit: int  # requests per day
    cache_ttl: int   # seconds
    
    @abstractmethod
    async def fetch(self, **params) -> dict:
        """Fetch data from external API and normalize."""
        pass
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    async def _request(self, endpoint: str, params: dict = None) -> dict:
        """Make HTTP request with retry logic."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{self.base_url}/{endpoint}", params=params)
            response.raise_for_status()
            return response.json()
```

### Caching Strategy (Redis)

```python
import json
import hashlib
from redis import asyncio as aioredis

class CacheService:
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
```

### Rate Limiting (Per External API)

```python
from datetime import date

class RateLimiter:
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
```

### Response Format (Unified)

```python
from pydantic import BaseModel
from datetime import datetime

class APIResponse(BaseModel):
    """Unified response format for all APIs."""
    source: str           # "openweather", "coingecko", etc.
    data: dict           # Original API response
    cached: bool         # True if from cache
    cached_at: datetime | None
    request_id: str      # UUID for logging/debugging
```

### Error Handling

```python
from fastapi import HTTPException
import logging

logger = logging.getLogger(__name__)

class ExternalAPIError(Exception):
    """External API call failed."""
    pass

async def call_with_fallback(api_call, cache_service, api: str, params: dict):
    """Call API with fallback to stale cache on error."""
    try:
        # Try rate limit check
        await rate_limiter.check_limit(api, limit=1000)
        
        # Try API call
        data = await api_call()
        
        # Cache result
        await cache_service.set(api, params, data, ttl=900)
        
        return APIResponse(
            source=api,
            data=data,
            cached=False,
            request_id=str(uuid.uuid4())
        )
        
    except RateLimitExceeded:
        # Return cached data even if stale
        cached = await cache_service.get(api, params)
        if cached:
            logger.warning(f"Rate limit exceeded for {api}, returning stale cache")
            return APIResponse(source=api, data=cached, cached=True)
        raise HTTPException(status_code=429, detail="Rate limit exceeded, no cache available")
    
    except httpx.HTTPError as e:
        logger.error(f"External API error for {api}: {e}")
        
        # Try to return cached data
        cached = await cache_service.get(api, params)
        if cached:
            return APIResponse(source=api, data=cached, cached=True)
        
        raise HTTPException(status_code=503, detail=f"{api} unavailable")
```

### Request Logging (PostgreSQL)

```python
from sqlalchemy import Column, String, Integer, Boolean, JSON, DateTime
from sqlalchemy.dialects.postgresql import UUID
import uuid

class APIRequestLog(Base):
    __tablename__ = "api_request_logs"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    endpoint = Column(String(255), nullable=False)  # /api/weather
    params = Column(JSON, default={})
    external_api = Column(String(50))  # openweather, null if cached
    cached = Column(Boolean, default=False)
    response_time_ms = Column(Integer)
    status = Column(Integer)  # HTTP status code
    error_message = Column(String(500))
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)
```

### Background Cache Refresh (Celery)

```python
from celery import shared_task

@shared_task
def refresh_hot_cache():
    """Refresh cache for frequently requested data."""
    hot_cities = ["London", "New York", "Tokyo"]  # From analytics
    
    for city in hot_cities:
        asyncio.run(fetch_and_cache_weather(city))
    
    logger.info(f"Refreshed cache for {len(hot_cities)} hot cities")

# Schedule with Celery Beat
from celery.schedules import crontab

app.conf.beat_schedule = {
    'refresh-hot-cache': {
        'task': 'app.tasks.refresh_hot_cache',
        'schedule': crontab(minute='*/10'),  # Every 10 minutes
    }
}
```

## Testing Requirements

1. **Mock External APIs:**
   ```python
   import respx
   import httpx
   
   @pytest.mark.asyncio
   @respx.mock
   async def test_openweather_client():
       respx.get("https://api.openweathermap.org/data/2.5/weather").mock(
           return_value=httpx.Response(200, json={"temp": 20})
       )
       
       client = OpenWeatherClient()
       data = await client.fetch(city="London")
       
       assert data["temp"] == 20
   ```

2. **Test Caching:**
   ```python
   async def test_cache_hit():
       # First call: cache miss
       response1 = await client.get("/api/weather?city=London")
       assert response1.json()["cached"] is False
       
       # Second call: cache hit
       response2 = await client.get("/api/weather?city=London")
       assert response2.json()["cached"] is True
   ```

3. **Test Rate Limiting:**
   ```python
   async def test_rate_limit():
       # Exceed daily limit
       for _ in range(1001):
           await rate_limiter.check_limit("openweather", limit=1000)
       
       # Should raise
       with pytest.raises(RateLimitExceeded):
           await rate_limiter.check_limit("openweather", limit=1000)
   ```

## Code Quality

- **Type hints everywhere** (use mypy)
- **Async all I/O** (no blocking calls)
- **Structured logging** with context
- **Error recovery** (fallback to cache)
- **Retry logic** with exponential backoff

## API Endpoints

```python
@app.get("/api/weather")
async def get_weather(city: str, cache: CacheService = Depends(get_cache)):
    """Get weather for city with caching."""
    # Implementation using patterns above
    ...

@app.get("/api/crypto")
async def get_crypto(symbol: str):
    """Get crypto price."""
    ...

@app.get("/status")
async def get_status():
    """Return rate limit status for all APIs."""
    return {
        "openweather": await rate_limiter.get_usage("openweather"),
        "coingecko": await rate_limiter.get_usage("coingecko")
    }
```

## Environment Variables

Required:
- `DATABASE_URL`: PostgreSQL connection
- `REDIS_URL`: Redis connection

Optional (API keys):
- `OPENWEATHER_API_KEY`: OpenWeather API key
- `NEWS_API_KEY`: NewsAPI key

## Definition of Done

- ✅ 3+ external API integrations working
- ✅ Redis caching with appropriate TTLs
- ✅ Rate limiting per API enforced
- ✅ Retry logic with exponential backoff
- ✅ Fallback to stale cache on errors
- ✅ Request logging to PostgreSQL
- ✅ Status endpoint shows cache hit rate
- ✅ Tests >70% coverage
- ✅ Docker Compose runs full stack
- ✅ API docs in README

## Common Pitfalls

1. **Don't poll too frequently** - respect external API limits
2. **Don't cache errors** - only cache successful responses
3. **Don't use infinite retries** - cap at 3 attempts
4. **Don't expose API keys** - use env vars
5. **Don't ignore timeouts** - set on all HTTP requests
6. **Don't skip deduplication** - check cache before external call
7. **Don't use blocking Redis** - use aioredis

This demonstrates resilient integration patterns - critical for Upwork credibility.
