# API Gateway Hub - Project Plan

**Project Type:** Integration Service (BFF Pattern)  
**Build Time:** 1-2 days  
**Difficulty:** Intermediate

## What You're Building

Integration service aggregating multiple external APIs (weather, crypto, country data) with Redis caching, rate limiting, retry logic, and error handling. BFF pattern demonstrating resilient API integration.

**Key Value:** Shows external API integration expertise (50%+ of Upwork jobs).

## Clarifying Questions (Ask User First)

1. **Which external APIs?** OpenWeather, CoinGecko, REST Countries, NewsAPI?  
   *Recommendation: Pick 3 free APIs*

2. **Caching TTL?** Weather 15min, Crypto 5min, Countries 24h?  
   *Recommendation: Yes, depends on data freshness*

3. **Rate limiting:** Track requests per API, enforce limits?  
   *Recommendation: Yes, prevent hitting API limits*

4. **Background refresh?** Proactive cache refresh or on-demand only?  
   *Recommendation: On-demand for MVP*

## Tech Stack

- **Framework:** FastAPI 0.115 + Python 3.12
- **Database:** PostgreSQL 16 (request logging)
- **Cache:** Redis 7.2
- **Queue:** Celery 5.3 (background tasks)
- **HTTP:** httpx (async) + tenacity (retry)
- **Deployment:** Docker

## Implementation Plan

### Phase 1: Foundation (2 hours)

**Setup:**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install fastapi==0.115.0 uvicorn[standard]==0.30.6 \
  httpx==0.27.2 redis==5.0.4 celery==5.3.6 \
  sqlalchemy[asyncio]==2.0.31 asyncpg==0.29.0 \
  tenacity==9.0.0 pydantic-settings==2.4.0

mkdir -p app/{api,integrations,services,tasks,models}
```

**Config (app/config.py):**
```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str
    redis_url: str
    openweather_api_key: str
    log_level: str = "INFO"
    
    class Config:
        env_file = ".env"

settings = Settings()
```

### Phase 2: API Client Pattern (3 hours)

**Base Client (app/integrations/base.py):**
```python
from abc import ABC, abstractmethod
from tenacity import retry, stop_after_attempt, wait_exponential
import httpx

class BaseAPIClient(ABC):
    base_url: str
    rate_limit: int  # requests per day
    cache_ttl: int   # seconds
    
    @abstractmethod
    async def fetch(self, **params) -> dict:
        """Fetch and normalize data from external API."""
        pass
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    async def _request(self, endpoint: str, params: dict = None):
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{self.base_url}/{endpoint}",
                params=params
            )
            response.raise_for_status()
            return response.json()
```

**OpenWeather Client (app/integrations/openweather.py):**
```python
class OpenWeatherClient(BaseAPIClient):
    base_url = "https://api.openweathermap.org/data/2.5"
    rate_limit = 1000  # free tier
    cache_ttl = 900    # 15 minutes
    
    async def fetch(self, city: str) -> dict:
        data = await self._request("weather", {
            "q": city,
            "appid": settings.openweather_api_key,
            "units": "metric"
        })
        
        return {
            "city": data["name"],
            "temperature": data["main"]["temp"],
            "description": data["weather"][0]["description"]
        }
```

**Similar clients for CoinGecko, REST Countries**

### Phase 3: Caching Layer (2 hours)

**Cache Service (app/services/cache_service.py):**
```python
import json
import hashlib
from redis import asyncio as aioredis

class CacheService:
    def __init__(self, redis: aioredis.Redis):
        self.redis = redis
    
    def _cache_key(self, api: str, params: dict) -> str:
        param_str = json.dumps(params, sort_keys=True)
        param_hash = hashlib.md5(param_str.encode()).hexdigest()
        return f"{api}:{param_hash}"
    
    async def get(self, api: str, params: dict):
        key = self._cache_key(api, params)
        data = await self.redis.get(key)
        return json.loads(data) if data else None
    
    async def set(self, api: str, params: dict, data: dict, ttl: int):
        key = self._cache_key(api, params)
        await self.redis.setex(key, ttl, json.dumps(data))
```

**Rate Limiter (app/services/rate_limiter.py):**
```python
from datetime import date

class RateLimiter:
    def __init__(self, redis: aioredis.Redis):
        self.redis = redis
    
    async def check_limit(self, api: str, limit: int):
        key = f"ratelimit:{api}:{date.today()}"
        count = await self.redis.incr(key)
        
        if count == 1:
            await self.redis.expire(key, 86400)
        
        if count > limit:
            raise RateLimitExceeded(f"{api} daily limit exceeded")
        
        return True
```

### Phase 4: Unified API Endpoints (2 hours)

**API Response Schema (app/schemas.py):**
```python
from pydantic import BaseModel
from datetime import datetime

class APIResponse(BaseModel):
    source: str
    data: dict
    cached: bool
    cached_at: datetime | None
    request_id: str
```

**Weather Endpoint (app/api/weather.py):**
```python
from fastapi import APIRouter, Depends, HTTPException
import uuid

router = APIRouter()

@router.get("/weather")
async def get_weather(
    city: str,
    cache: CacheService = Depends(get_cache),
    rate_limiter: RateLimiter = Depends(get_rate_limiter)
):
    request_id = str(uuid.uuid4())
    
    # Check cache
    cached = await cache.get("openweather", {"city": city})
    if cached:
        return APIResponse(
            source="openweather",
            data=cached,
            cached=True,
            cached_at=datetime.now(),
            request_id=request_id
        )
    
    # Check rate limit
    try:
        await rate_limiter.check_limit("openweather", limit=1000)
    except RateLimitExceeded:
        if cached := await cache.get("openweather", {"city": city}):
            return APIResponse(source="openweather", data=cached, cached=True)
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    
    # Fetch from API
    client = OpenWeatherClient()
    data = await client.fetch(city=city)
    
    # Cache result
    await cache.set("openweather", {"city": city}, data, ttl=900)
    
    # Log request
    await log_request(request_id, "/weather", {"city": city}, "openweather")
    
    return APIResponse(
        source="openweather",
        data=data,
        cached=False,
        cached_at=None,
        request_id=request_id
    )
```

**Similar endpoints for /crypto, /countries**

### Phase 5: Request Logging (1 hour)

**Model (app/models/request_log.py):**
```python
class APIRequestLog(Base):
    __tablename__ = "api_request_logs"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    endpoint = Column(String(255))
    params = Column(JSON)
    external_api = Column(String(50))  # null if cached
    cached = Column(Boolean, default=False)
    response_time_ms = Column(Integer)
    status = Column(Integer)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
```

**Status Endpoint:**
```python
@app.get("/status")
async def get_status(rate_limiter: RateLimiter = Depends()):
    return {
        "openweather": {
            "usage": await rate_limiter.get_usage("openweather"),
            "limit": 1000
        },
        "coingecko": {
            "usage": await rate_limiter.get_usage("coingecko"),
            "limit": 10000
        }
    }
```

### Phase 6: Docker & Testing (2 hours)

**docker-compose.yml:**
```yaml
services:
  api:
    build: .
    ports:
      - "8000:8000"
    env_file: .env
    depends_on:
      - db
      - redis

  db:
    image: postgres:16
    environment:
      POSTGRES_DB: api_gateway
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres

  redis:
    image: redis:7.2
```

**Testing:**
```python
import respx
import httpx

@pytest.mark.asyncio
@respx.mock
async def test_openweather_client():
    respx.get("https://api.openweathermap.org/data/2.5/weather").mock(
        return_value=httpx.Response(200, json={"main": {"temp": 20}})
    )
    
    client = OpenWeatherClient()
    data = await client.fetch(city="London")
    assert data["temperature"] == 20
```

## Environment Variables

```
DATABASE_URL=postgresql://postgres:postgres@db/api_gateway
REDIS_URL=redis://redis:6379/0
OPENWEATHER_API_KEY=your-api-key
NEWS_API_KEY=your-news-api-key
```

## Testing Locally

```bash
# Start services
docker-compose up

# Get weather (cache miss)
curl "http://localhost:8000/api/weather?city=London"

# Get weather again (cache hit)
curl "http://localhost:8000/api/weather?city=London"

# Check rate limit status
curl http://localhost:8000/status
```

## Success Criteria

- ✅ 3+ external APIs integrated
- ✅ Redis caching with appropriate TTLs
- ✅ Rate limiting enforced
- ✅ Retry logic with exponential backoff
- ✅ Fallback to stale cache on errors
- ✅ Request logging to PostgreSQL
- ✅ Docker Compose works

## Reference

See CLAUDE.md for caching strategies, retry patterns, error handling.
