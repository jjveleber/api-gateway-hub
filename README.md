# API Gateway Hub

Integration service aggregating multiple external APIs (weather, crypto, country data) with Redis caching, rate limiting, retry logic, and error handling. Demonstrates Backend-for-Frontend (BFF) pattern for resilient API integration.

## Features

- **3 External API Integrations:**
  - OpenWeather API (weather data)
  - CoinGecko API (cryptocurrency prices)
  - REST Countries API (country information)

- **Redis Caching:**
  - Weather: 15min TTL
  - Crypto: 5min TTL
  - Countries: 24h TTL
  - Stale cache fallback on errors

- **Rate Limiting:**
  - Per-API daily limits enforced
  - Automatic fallback to cached data when limit exceeded

- **Retry Logic:**
  - Exponential backoff (3 attempts)
  - Automatic retry on transient failures

- **Error Handling:**
  - Graceful fallback to stale cache
  - Detailed error responses

## Tech Stack

- **Framework:** FastAPI 0.115 + Python 3.12
- **Database:** PostgreSQL 16 (request logging)
- **Cache:** Redis 7.2
- **HTTP:** httpx (async) + tenacity (retry)
- **Deployment:** Docker Compose

## Quick Start

### 1. Clone & Setup

```bash
git clone <repo-url>
cd api-gateway-hub
cp .env.example .env
```

### 2. Get OpenWeather API Key (Free)

**Required for `/api/weather` endpoint**

1. **Sign up at OpenWeather:**
   - Go to https://openweathermap.org/api
   - Click "Sign Up" (top right)
   - Create free account (email + password)

2. **Get your API key:**
   - After signup, go to https://home.openweathermap.org/api_keys
   - Default key is auto-generated ("Default API key")
   - Or click "Generate" to create new key
   - Copy the key (looks like: `a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6`)

3. **Add key to `.env` file:**

```bash
# Open .env file
nano .env

# Add your key:
OPENWEATHER_API_KEY=your_api_key_here
```

**Note:** Free tier = 1,000 calls/day. Key activates in ~10 minutes.

**Optional APIs (no key needed):**
- CoinGecko: Works immediately, no signup
- REST Countries: Works immediately, no signup

### 3. Start Services

```bash
docker-compose up
```

API runs at: http://localhost:8000

## API Endpoints

### Weather

```bash
GET /api/weather?city=London
```

Response:
```json
{
  "source": "openweather",
  "data": {
    "city": "London",
    "country": "GB",
    "temperature": 15.2,
    "feels_like": 14.1,
    "humidity": 72,
    "description": "cloudy",
    "wind_speed": 3.5
  },
  "cached": false,
  "cached_at": null,
  "request_id": "123e4567-e89b-12d3-a456-426614174000"
}
```

### Cryptocurrency

```bash
GET /api/crypto?symbol=btc
```

Response:
```json
{
  "source": "coingecko",
  "data": {
    "symbol": "BTC",
    "coin_id": "bitcoin",
    "price_usd": 45000.0,
    "market_cap_usd": 850000000000,
    "change_24h_percent": 2.5
  },
  "cached": false,
  "cached_at": null,
  "request_id": "123e4567-e89b-12d3-a456-426614174001"
}
```

Supported symbols: `btc`, `eth`, `usdt`, `bnb`, `sol`, `usdc`, `xrp`, `ada`, `doge`, `trx`

### Country Data

```bash
GET /api/countries?country=Japan
```

Response:
```json
{
  "source": "restcountries",
  "data": {
    "name": "Japan",
    "official_name": "Japan",
    "capital": "Tokyo",
    "region": "Asia",
    "subregion": "Eastern Asia",
    "population": 125000000,
    "area_km2": 377975,
    "languages": ["Japanese"],
    "currencies": ["JPY"],
    "timezones": ["UTC+09:00"],
    "flag_emoji": "🇯🇵"
  },
  "cached": false,
  "cached_at": null,
  "request_id": "123e4567-e89b-12d3-a456-426614174002"
}
```

### Status

```bash
GET /status
```

Response:
```json
{
  "openweather": {
    "usage": 42,
    "limit": 1000,
    "remaining": 958
  },
  "coingecko": {
    "usage": 15,
    "limit": 10000,
    "remaining": 9985
  },
  "restcountries": {
    "usage": 3,
    "limit": 100000,
    "remaining": 99997
  }
}
```

## Development

### Local Setup

```bash
# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Start PostgreSQL and Redis
docker-compose up db redis

# Run API locally
uvicorn app.main:app --reload
```

### Run Tests

**Quick Tests (Unit + Mocked Integration):**
```bash
# Run unit tests (no Docker required)
pytest tests/ -v --ignore=tests/test_database_integration.py --ignore=tests/test_redis_integration.py

# With coverage
pytest tests/ --cov=app --cov-report=term-missing \
  --ignore=tests/test_database_integration.py \
  --ignore=tests/test_redis_integration.py
```

**Full Tests (Including Testcontainers):**

Requires Docker running. Uses real PostgreSQL + Redis containers.

```bash
# Setup Docker (WSL users)
# Install Docker Desktop for Windows
# Enable WSL integration: Settings → Resources → WSL Integration

# Verify Docker works
docker ps

# Run all tests (including testcontainers)
pytest tests/ -v

# With coverage
pytest tests/ --cov=app --cov-report=html
```

**Test Structure:**

- **Unit Tests (20 tests):** Mock external dependencies
  - `test_openweather.py` - OpenWeather client (2)
  - `test_coingecko.py` - CoinGecko client (3)
  - `test_countries.py` - REST Countries client (2)
  - `test_cache.py` - Cache service with mocked Redis (3)
  - `test_rate_limiter.py` - Rate limiter with mocked Redis (4)
  - `test_api_integration.py` - API endpoints with mocks (6)

- **Integration Tests (8 tests):** Real containers via testcontainers
  - `test_database_integration.py` - Real PostgreSQL (3)
  - `test_redis_integration.py` - Real Redis (5)

**Coverage: 84%** (28 tests total, 20 unit + 8 integration)

### Project Structure

```
api-gateway-hub/
├── app/
│   ├── api/
│   │   ├── weather.py       # Weather endpoint
│   │   ├── crypto.py        # Crypto endpoint
│   │   └── countries.py     # Countries endpoint
│   ├── integrations/
│   │   ├── base.py          # Base API client with retry
│   │   ├── openweather.py   # OpenWeather client
│   │   ├── coingecko.py     # CoinGecko client
│   │   └── countries.py     # REST Countries client
│   ├── services/
│   │   ├── cache_service.py # Redis caching
│   │   └── rate_limiter.py  # Rate limiting
│   ├── models/
│   │   ├── database.py      # Database setup
│   │   └── request_log.py   # Request logging model
│   ├── config.py            # Settings
│   ├── dependencies.py      # Dependency injection
│   ├── schemas.py           # Pydantic schemas
│   └── main.py              # FastAPI app
├── tests/                   # Unit tests
├── docker-compose.yml       # Docker services
├── Dockerfile               # API container
└── requirements.txt         # Python dependencies
```

## Testing Strategy

### Three-Layer Testing Pyramid

**1. Unit Tests (Fast, No Docker):**
- Mock external APIs with `respx`
- Mock Redis/PostgreSQL with `AsyncMock`
- Test business logic in isolation
- Run in CI/CD pipelines
- Fast feedback (~4s for 20 tests)

**2. Integration Tests (Slower, Requires Docker):**
- **Real PostgreSQL container** via testcontainers
  - Test actual SQL queries, transactions
  - Verify database models work end-to-end
- **Real Redis container** via testcontainers
  - Test cache expiry, key generation
  - Test rate limiting with real Redis operations
- Run before deployment (~12s for 8 tests)

**3. API Integration Tests:**
- Test FastAPI endpoints with mocked external services
- Verify request/response flow
- Test error handling, validation

**What's Tested End-to-End:**
- ✅ Database layer: Real PostgreSQL queries
- ✅ Cache layer: Real Redis operations
- ✅ Rate limiting: Real Redis counters with expiry
- ✅ API endpoints: Request validation, error handling
- ✅ External API clients: Retry logic, normalization

### Docker Setup for Testcontainers

**macOS/Linux:**
```bash
# Install Docker
# macOS: https://docs.docker.com/desktop/install/mac-install/
# Linux: https://docs.docker.com/engine/install/

# Verify
docker ps
```

**Windows (WSL2):**
```bash
# 1. Install Docker Desktop for Windows
#    https://docs.docker.com/desktop/install/windows-install/

# 2. Enable WSL integration
#    Docker Desktop → Settings → Resources → WSL Integration
#    ✅ Enable integration with your distro

# 3. Restart WSL
wsl --shutdown
# Reopen terminal

# 4. Verify Docker works in WSL
docker ps
```

**No Docker? Skip integration tests:**
```bash
pytest tests/ -v \
  --ignore=tests/test_database_integration.py \
  --ignore=tests/test_redis_integration.py
```

### Running Tests

```bash
# Fast: Unit tests only (no Docker)
pytest tests/ -v -k "not integration"

# Full: All tests (requires Docker)
pytest tests/ -v

# Coverage report
pytest tests/ --cov=app --cov-report=html
open htmlcov/index.html
```

## Architecture Patterns

### 1. Base API Client Pattern

All external API clients inherit from `BaseAPIClient`:
- Automatic retry with exponential backoff
- Timeout enforcement (10s)
- Response normalization

### 2. Cache-Aside Pattern

```python
# Check cache first
cached = await cache.get(api, params)
if cached:
    return cached

# Fetch from API
data = await client.fetch(**params)

# Update cache
await cache.set(api, params, data, ttl)
```

### 3. Stale Cache Fallback

On errors or rate limit exceeded:
1. Try API call
2. If fails, return stale cache (even if expired)
3. If no cache, return error

### 4. Rate Limiting

Per-API daily limits with Redis:
- Key: `ratelimit:{api}:{date}`
- Auto-expires at midnight
- Blocks requests over limit

## Deployment

### Production Checklist

- [ ] Set real API keys in environment
- [ ] Configure database backup
- [ ] Set up monitoring (Prometheus/Grafana)
- [ ] Add authentication to endpoints
- [ ] Configure CORS if needed
- [ ] Set up logging aggregation
- [ ] Configure rate limits per user

### Environment Variables

```bash
DATABASE_URL=postgresql+asyncpg://user:pass@host/db
REDIS_URL=redis://host:6379/0
OPENWEATHER_API_KEY=your-key
LOG_LEVEL=INFO
```

## API Keys Reference

### OpenWeather (Required for Weather Endpoint)

**Free Tier:** 1,000 calls/day, 60 calls/min

1. Sign up: https://openweathermap.org/api
2. Get API key: https://home.openweathermap.org/api_keys
3. Add to `.env`: `OPENWEATHER_API_KEY=your-key`
4. Wait ~10 minutes for activation

**Troubleshooting:**
- `401 Unauthorized`: Key not activated yet (wait 10min) or invalid key
- `429 Too Many Requests`: Daily limit exceeded (1000 calls)
- Empty weather data: City name misspelled or not found

### CoinGecko (No Key Required)

**Free Tier:** 10-50 calls/min (no daily limit)

- No signup needed
- Works immediately
- Supported symbols: `btc`, `eth`, `usdt`, `bnb`, `sol`, `usdc`, `xrp`, `ada`, `doge`, `trx`

### REST Countries (No Key Required)

**Free Tier:** No limits

- No signup needed
- Works immediately
- Search by country name (e.g., "Japan", "United States")

## Success Criteria

- ✅ 3+ external APIs integrated
- ✅ Redis caching with appropriate TTLs
- ✅ Rate limiting enforced
- ✅ Retry logic with exponential backoff
- ✅ Fallback to stale cache on errors
- ✅ Request logging models (PostgreSQL)
- ✅ Docker Compose works
- ✅ Tests >70% coverage

## License

MIT
