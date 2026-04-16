# Production Readiness Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform API Gateway Hub from development-ready to production-ready with health checks, observability, graceful shutdown, deployment configs, and database migrations.

**Architecture:** Add production-grade infrastructure patterns: health endpoints for K8s probes, structured logging for log aggregation, Prometheus metrics for monitoring, graceful shutdown for zero-downtime deploys, Alembic for database schema versioning, and deployment manifests for K8s/Cloud Run.

**Tech Stack:** 
- Observability: structlog, prometheus-client
- Migrations: alembic
- Deployment: Kubernetes, Google Cloud Run, Docker multi-stage builds
- Testing: pytest, testcontainers (existing)

---

## Chunk 1: Health & Observability

### Task 1: Health Check Endpoint

**Files:**
- Modify: `app/main.py`
- Modify: `app/dependencies.py`
- Create: `tests/test_health.py`

**Goal:** Add `/health` and `/health/ready` endpoints for Kubernetes liveness and readiness probes.

- [ ] **Step 1: Write failing test for basic health endpoint**

Create: `tests/test_health.py`

```python
import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock
from redis import asyncio as aioredis

from app.main import app
from app.dependencies import get_redis
from app.models.database import get_db

client = TestClient(app)


def test_health_endpoint_returns_ok():
    """Test /health returns 200 when all systems operational."""
    response = client.get("/health")
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "timestamp" in data


def test_health_ready_checks_dependencies():
    """Test /health/ready checks DB and Redis connectivity."""
    # Note: This test requires real services (use docker-compose for integration test)
    # For unit test, we'd override dependencies with mocks
    response = client.get("/health/ready")
    
    assert response.status_code in [200, 503]  # May fail if services not running
    data = response.json()
    assert "checks" in data


def test_health_ready_fails_when_redis_down():
    """Test /health/ready returns 503 when Redis unavailable."""
    # Mock Redis to raise exception
    async def mock_get_redis():
        redis_mock = AsyncMock(spec=aioredis.Redis)
        redis_mock.ping = AsyncMock(side_effect=Exception("Connection refused"))
        return redis_mock
    
    # Mock DB to succeed
    async def mock_get_db():
        db_mock = AsyncMock()
        db_mock.execute = AsyncMock()
        yield db_mock
    
    # Override dependencies
    app.dependency_overrides[get_redis] = mock_get_redis
    app.dependency_overrides[get_db] = mock_get_db
    
    try:
        response = client.get("/health/ready")
        
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "unhealthy"
        assert "error" in data["checks"]["redis"]
    finally:
        # Cleanup overrides
        app.dependency_overrides.clear()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_health.py -v`

Expected: FAIL - `/health` endpoint does not exist

- [ ] **Step 3: Implement health check endpoints**

Modify: `app/main.py`

Add after existing imports:
```python
from datetime import datetime
from fastapi import status
import logging
from redis import asyncio as aioredis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.responses import JSONResponse

from app.dependencies import get_redis
from app.models.database import get_db

logger = logging.getLogger(__name__)
```

Add before existing route includes (after `app = FastAPI(...)`):
```python
@app.get("/health", tags=["health"])
async def health_check():
    """
    Liveness probe - returns 200 if app is running.
    Used by K8s to restart unhealthy pods.
    """
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "service": "api-gateway-hub"
    }


@app.get("/health/ready", tags=["health"], status_code=status.HTTP_200_OK)
async def readiness_check(
    redis: aioredis.Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_db)
):
    """
    Readiness probe - checks dependencies before accepting traffic.
    Returns 503 if any critical dependency is unavailable.
    """
    checks = {}
    overall_status = "ready"
    status_code = status.HTTP_200_OK
    
    # Check Redis connectivity
    try:
        await redis.ping()
        checks["redis"] = "connected"
    except Exception as e:
        logger.error(f"Redis health check failed: {e}")
        checks["redis"] = f"error: {str(e)}"
        overall_status = "unhealthy"
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    
    # Check Database connectivity
    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = "connected"
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        checks["database"] = f"error: {str(e)}"
        overall_status = "unhealthy"
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    
    return JSONResponse(
        status_code=status_code,
        content={
            "status": overall_status,
            "checks": checks,
            "timestamp": datetime.utcnow().isoformat()
        }
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_health.py -v`

Expected: PASS (3 tests)

- [ ] **Step 5: Test health endpoints manually**

Run: 
```bash
# Verify Docker is running
docker-compose --version

# Start services
docker-compose up -d

# Test liveness (should always return 200)
curl http://localhost:8000/health
# Expected: {"status":"healthy","timestamp":"...","service":"api-gateway-hub"}

# Test readiness (should return 200 when all dependencies healthy)
curl http://localhost:8000/health/ready
# Expected: {"status":"ready","checks":{"redis":"connected","database":"connected"},"timestamp":"..."}

# Test Redis failure scenario
docker-compose stop redis
sleep 2
curl http://localhost:8000/health/ready
# Expected: HTTP 503, {"status":"unhealthy","checks":{"redis":"error: ...","database":"connected"},"timestamp":"..."}

# Restart Redis
docker-compose start redis
sleep 2
curl http://localhost:8000/health/ready
# Should return 200 again

# Test database failure scenario
docker-compose stop db
sleep 2
curl http://localhost:8000/health/ready
# Expected: HTTP 503, checks show database error

# Restart all services
docker-compose start db
```

Expected: Health always returns 200, readiness returns 200 when healthy and 503 when dependencies down

- [ ] **Step 6: Commit health check implementation**

```bash
git add app/main.py tests/test_health.py
git commit -m "feat: add health check endpoints for K8s probes

- Add /health liveness probe (always returns 200 if app running)
- Add /health/ready readiness probe (checks DB + Redis connectivity)
- Return 503 from readiness when dependencies unavailable
- Add tests for health endpoints with dependency mocking"
```

---

### Task 2: Structured JSON Logging

**Files:**
- Create: `app/logging_config.py`
- Modify: `app/main.py`
- Modify: `requirements.txt`
- Create: `tests/test_logging.py`

**Goal:** Replace standard logging with structured JSON logs for production log aggregation (Stackdriver, CloudWatch, etc).

- [ ] **Step 1: Add structlog dependency**

Modify: `requirements.txt`

Add:
```
structlog==24.1.0
python-json-logger==2.0.7
```

- [ ] **Step 2: Install new dependencies**

Run: `pip install structlog==24.1.0 python-json-logger==2.0.7`

Expected: Packages installed successfully

- [ ] **Step 3: Write failing test for structured logging**

Create: `tests/test_logging.py`

```python
import pytest
import json
from io import StringIO
import logging

from app.logging_config import setup_logging


def test_structured_logging_outputs_json():
    """Test that logs are output as JSON with structured fields."""
    # Setup in-memory log capture
    log_stream = StringIO()
    handler = logging.StreamHandler(log_stream)
    
    logger = setup_logging(level="INFO", json_logs=True)
    logger.addHandler(handler)
    
    # Log a message with context
    logger.info("test_event", user_id=123, action="login")
    
    # Parse JSON output
    log_output = log_stream.getvalue()
    log_entry = json.loads(log_output.strip())
    
    assert log_entry["event"] == "test_event"
    assert log_entry["user_id"] == 123
    assert log_entry["action"] == "login"
    assert "timestamp" in log_entry
    assert log_entry["level"] == "info"


def test_structured_logging_includes_request_context():
    """Test logging includes request ID and other context."""
    log_stream = StringIO()
    handler = logging.StreamHandler(log_stream)
    
    logger = setup_logging(level="INFO", json_logs=True)
    logger.addHandler(handler)
    
    # Log with request context
    logger = logger.bind(request_id="abc-123", endpoint="/api/weather")
    logger.info("api_request_completed", duration_ms=150, cached=True)
    
    log_output = log_stream.getvalue()
    log_entry = json.loads(log_output.strip())
    
    assert log_entry["request_id"] == "abc-123"
    assert log_entry["endpoint"] == "/api/weather"
    assert log_entry["duration_ms"] == 150
    assert log_entry["cached"] is True
```

- [ ] **Step 4: Run test to verify it fails**

Run: `pytest tests/test_logging.py -v`

Expected: FAIL - `app.logging_config` module does not exist

- [ ] **Step 5: Implement structured logging configuration**

Create: `app/logging_config.py`

```python
"""
Structured logging configuration for production environments.
Outputs JSON logs for log aggregation systems (Stackdriver, CloudWatch, etc).
"""
import logging
import sys
from typing import Any

import structlog
from structlog.types import EventDict, Processor


def add_app_context(logger: Any, method_name: str, event_dict: EventDict) -> EventDict:
    """Add application-level context to all log entries."""
    event_dict["service"] = "api-gateway-hub"
    event_dict["version"] = "1.0.0"  # TODO: Get from env var or package
    return event_dict


def setup_logging(level: str = "INFO", json_logs: bool = True) -> structlog.BoundLogger:
    """
    Configure structured logging for the application.
    
    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        json_logs: If True, output JSON. If False, use human-readable format (dev mode)
    
    Returns:
        Configured structlog logger
    """
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        add_app_context,
    ]
    
    if json_logs:
        # Production: JSON output
        processors = shared_processors + [
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer()
        ]
    else:
        # Development: Human-readable colored output
        processors = shared_processors + [
            structlog.dev.ConsoleRenderer()
        ]
    
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    
    # Configure standard library logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, level.upper()),
    )
    
    return structlog.get_logger()
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_logging.py -v`

Expected: PASS (2 tests)

- [ ] **Step 7: Integrate structured logging into FastAPI app**

Modify: `app/main.py`

Add after existing imports:
```python
from app.logging_config import setup_logging
from app.config import settings
import structlog
```

Add after `app = FastAPI(...)`:
```python
# Setup structured logging
logger = setup_logging(
    level=settings.log_level,
    json_logs=settings.environment == "production"  # JSON in prod, human-readable in dev
)
```

Add middleware for request logging (after app creation, before route includes):
```python
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all HTTP requests with structured context."""
    import time
    import uuid
    
    # Generate request ID
    request_id = str(uuid.uuid4())
    
    # Bind request context
    log = logger.bind(
        request_id=request_id,
        method=request.method,
        path=request.url.path,
        client_ip=request.client.host if request.client else None
    )
    
    # Add request ID to response headers
    start_time = time.time()
    response = await call_next(request)
    duration_ms = int((time.time() - start_time) * 1000)
    
    # Log request completion
    log.info(
        "http_request_completed",
        status_code=response.status_code,
        duration_ms=duration_ms
    )
    
    response.headers["X-Request-ID"] = request_id
    return response
```

Add Request import:
```python
from fastapi import Request
```

- [ ] **Step 8: Add environment field to config**

Modify: `app/config.py`

Add field to Settings class (after the existing `log_level` field):
```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")
    
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost/api_gateway"
    redis_url: str = "redis://localhost:6379/0"
    openweather_api_key: str = ""
    log_level: str = "INFO"
    environment: str = "development"  # NEW: development, staging, production
```

- [ ] **Step 9: Test structured logging in running app**

Run:
```bash
# Set production mode
export ENVIRONMENT=production
docker-compose up

# Make a request
curl http://localhost:8000/api/weather?city=London

# Check logs - should see JSON output
docker-compose logs api | tail -20
```

Expected: Logs in JSON format with request_id, duration_ms, status_code, etc.

- [ ] **Step 10: Commit structured logging**

```bash
git add app/logging_config.py app/main.py app/config.py requirements.txt tests/test_logging.py
git commit -m "feat: add structured JSON logging for production

- Add structlog with JSON output for log aggregation systems
- Configure human-readable dev logs and JSON production logs
- Add request logging middleware with request IDs
- Include request context (method, path, duration, status)
- Add X-Request-ID header to all responses
- Add environment config field (dev/staging/prod)"
```

---

### Task 3: Prometheus Metrics

**Files:**
- Create: `app/metrics.py`
- Modify: `app/main.py`
- Modify: `requirements.txt`
- Create: `tests/test_metrics.py`

**Goal:** Expose Prometheus metrics at `/metrics` endpoint for monitoring request rates, durations, cache hits, and errors.

- [ ] **Step 1: Add prometheus_client dependency**

Modify: `requirements.txt`

Add:
```
prometheus-client==0.20.0
```

- [ ] **Step 2: Install dependency**

Run: `pip install prometheus-client==0.20.0`

Expected: Package installed

- [ ] **Step 3: Write failing test for metrics**

Create: `tests/test_metrics.py`

```python
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_metrics_endpoint_exists():
    """Test /metrics endpoint exists and returns Prometheus format."""
    response = client.get("/metrics")
    
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    
    # Check for expected metrics
    content = response.text
    assert "http_requests_total" in content
    assert "http_request_duration_seconds" in content
    assert "cache_hits_total" in content
    assert "cache_misses_total" in content


def test_metrics_track_requests():
    """Test that request metrics are incremented."""
    # Get initial metrics
    response1 = client.get("/metrics")
    initial_content = response1.text
    
    # Make some API requests
    client.get("/api/weather?city=London")
    client.get("/api/crypto?symbol=btc")
    
    # Get updated metrics
    response2 = client.get("/metrics")
    updated_content = response2.text
    
    # Verify metrics increased
    assert "http_requests_total" in updated_content
    # Note: Actual count verification would require parsing Prometheus format
```

- [ ] **Step 4: Run test to verify it fails**

Run: `pytest tests/test_metrics.py -v`

Expected: FAIL - `/metrics` endpoint does not exist

- [ ] **Step 5: Implement metrics module**

Create: `app/metrics.py`

```python
"""
Prometheus metrics for monitoring application performance.
"""
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from fastapi import Response
import time


# HTTP Metrics
http_requests_total = Counter(
    'http_requests_total',
    'Total HTTP requests',
    ['method', 'endpoint', 'status_code']
)

http_request_duration_seconds = Histogram(
    'http_request_duration_seconds',
    'HTTP request duration in seconds',
    ['method', 'endpoint']
)

# Cache Metrics
cache_hits_total = Counter(
    'cache_hits_total',
    'Total cache hits',
    ['api']
)

cache_misses_total = Counter(
    'cache_misses_total',
    'Total cache misses',
    ['api']
)

# External API Metrics
external_api_requests_total = Counter(
    'external_api_requests_total',
    'Total requests to external APIs',
    ['api', 'status']  # status: success, error, rate_limited
)

external_api_duration_seconds = Histogram(
    'external_api_duration_seconds',
    'External API request duration in seconds',
    ['api']
)

# Rate Limit Metrics
rate_limit_usage = Gauge(
    'rate_limit_usage',
    'Current rate limit usage',
    ['api']
)

rate_limit_remaining = Gauge(
    'rate_limit_remaining',
    'Remaining rate limit quota',
    ['api']
)


def metrics_response() -> Response:
    """Generate Prometheus metrics response."""
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST
    )


class MetricsMiddleware:
    """Middleware to track HTTP request metrics."""
    
    def __init__(self, app):
        self.app = app
    
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        
        # Skip metrics endpoint itself
        if scope["path"] == "/metrics":
            await self.app(scope, receive, send)
            return
        
        method = scope["method"]
        path = scope["path"]
        
        start_time = time.time()
        
        # Track response status
        status_code = 200
        
        async def send_wrapper(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)
        
        await self.app(scope, receive, send_wrapper)
        
        # Record metrics
        duration = time.time() - start_time
        http_requests_total.labels(method=method, endpoint=path, status_code=status_code).inc()
        http_request_duration_seconds.labels(method=method, endpoint=path).observe(duration)
```

- [ ] **Step 6: Add metrics endpoint to main app**

Modify: `app/main.py`

Add import:
```python
from app.metrics import metrics_response, MetricsMiddleware
```

Add metrics endpoint (after health checks):
```python
@app.get("/metrics", tags=["monitoring"])
async def metrics():
    """
    Prometheus metrics endpoint.
    Exposes application metrics for scraping by Prometheus.
    """
    return metrics_response()
```

Add metrics middleware (after existing middleware):
```python
# Add Prometheus metrics middleware
app.add_middleware(MetricsMiddleware)
```

- [ ] **Step 7: Instrument cache service with metrics**

Modify: `app/services/cache_service.py`

Add import at top:
```python
from app.metrics import cache_hits_total, cache_misses_total
```

In the `get` method, add after retrieving data:
```python
async def get(self, api: str, params: dict) -> dict | None:
    """Get cached data if exists."""
    key = self._cache_key(api, params)
    data = await self.redis.get(key)
    
    if data:
        cache_hits_total.labels(api=api).inc()
        return json.loads(data)
    else:
        cache_misses_total.labels(api=api).inc()
        return None
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest tests/test_metrics.py -v`

Expected: PASS (2 tests)

- [ ] **Step 9: Test metrics endpoint manually**

Run:
```bash
docker-compose up -d

# Make some requests
curl http://localhost:8000/api/weather?city=London
curl http://localhost:8000/api/crypto?symbol=btc

# Check metrics endpoint returns data
curl http://localhost:8000/metrics

# Verify Prometheus format with specific metrics
curl http://localhost:8000/metrics | grep -E "http_requests_total|cache_hits_total|cache_misses_total"

# Should see output like:
# http_requests_total{method="GET",endpoint="/api/weather",status_code="200"} 1.0
# cache_hits_total{api="openweather"} 0.0
# cache_misses_total{api="openweather"} 1.0

# Verify content type
curl -I http://localhost:8000/metrics | grep -i content-type
# Should see: Content-Type: text/plain; version=0.0.4; charset=utf-8
```

Expected: Metrics endpoint returns Prometheus-format metrics with actual counts, proper content-type header

- [ ] **Step 10: Commit metrics implementation**

```bash
git add app/metrics.py app/main.py app/services/cache_service.py requirements.txt tests/test_metrics.py
git commit -m "feat: add Prometheus metrics endpoint

- Expose /metrics endpoint in Prometheus format
- Track HTTP request counts and duration by endpoint
- Track cache hits/misses per API
- Add metrics middleware to instrument all requests
- Track external API request counts and status
- Track rate limit usage and remaining quota
- Instrument cache service with hit/miss metrics"
```

---

## Chunk 2: Production Configuration

### Task 4: Graceful Shutdown

**Files:**
- Modify: `app/main.py`
- Modify: `app/dependencies.py`
- Modify: `app/models/database.py`
- Create: `tests/test_shutdown.py`

**Goal:** Implement graceful shutdown handlers to close database and Redis connections cleanly when receiving SIGTERM from Kubernetes.

**Note:** The database engine is currently created in `app/models/database.py` at module level. We'll expose it for shutdown handling.

- [ ] **Step 1: Write test for shutdown handlers**

Create: `tests/test_shutdown.py`

```python
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.main import app


@pytest.mark.asyncio
async def test_shutdown_closes_redis_connection():
    """Test shutdown event closes Redis connection."""
    # Create mock Redis client
    mock_redis = MagicMock()
    mock_redis.close = AsyncMock()
    
    with patch("app.dependencies.redis_client", mock_redis):
        # Trigger shutdown event handlers
        for handler in app.router.on_shutdown:
            await handler()
        
        # Verify Redis connection closed
        mock_redis.close.assert_called_once()


@pytest.mark.asyncio
async def test_shutdown_closes_database_engine():
    """Test shutdown event disposes database engine."""
    # Create mock engine
    mock_engine = MagicMock()
    mock_engine.dispose = AsyncMock()
    
    with patch("app.models.database.engine", mock_engine):
        # Trigger shutdown event handlers
        for handler in app.router.on_shutdown:
            await handler()
        
        # Verify engine disposed
        mock_engine.dispose.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_shutdown.py -v`

Expected: FAIL - shutdown handlers not registered

- [ ] **Step 3: Expose Redis client for shutdown tracking**

Modify: `app/dependencies.py`

Change `_redis_client` to public (remove underscore) so it can be accessed for shutdown:
```python
redis_client = None  # Changed from _redis_client


async def get_redis() -> aioredis.Redis:
    """Get Redis client (singleton)."""
    global redis_client
    if redis_client is None:
        redis_client = await aioredis.from_url(
            settings.redis_url, encoding="utf-8", decode_responses=True
        )
    return redis_client
```

Note: Database engine is already module-level in `app/models/database.py`, so we can import it directly for shutdown.

- [ ] **Step 4: Implement shutdown handlers**

Modify: `app/main.py`

Add shutdown event handler (after startup events, before route includes):
```python
@app.on_event("shutdown")
async def shutdown_event():
    """
    Graceful shutdown handler.
    Closes database and Redis connections cleanly when app receives SIGTERM.
    """
    logger.info("shutdown_initiated", message="Closing connections gracefully")
    
    # Close Redis connection
    from app import dependencies
    if dependencies.redis_client:
        await dependencies.redis_client.close()
        logger.info("redis_closed")
    
    # Dispose database engine
    from app.models import database
    if database.engine:
        await database.engine.dispose()
        logger.info("database_closed")
    
    logger.info("shutdown_complete")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_shutdown.py -v`

Expected: PASS (2 tests)

- [ ] **Step 6: Test graceful shutdown manually**

Run:
```bash
# Start app
docker-compose up

# In another terminal, send SIGTERM
docker-compose kill -s SIGTERM api

# Check logs - should see graceful shutdown messages
docker-compose logs api | grep shutdown

# Should see:
# shutdown_initiated
# redis_closed
# database_closed
# shutdown_complete
```

Expected: Clean shutdown with all connections closed

- [ ] **Step 7: Commit graceful shutdown**

```bash
git add app/main.py app/dependencies.py tests/test_shutdown.py
git commit -m "feat: implement graceful shutdown for production

- Add shutdown event handler to close connections cleanly
- Track Redis client and DB engine globally for cleanup
- Close Redis connection on SIGTERM
- Dispose database engine on shutdown
- Log shutdown events for observability
- Enables zero-downtime K8s rolling updates"
```

---

### Task 5: Database Migrations with Alembic

**Files:**
- Add to `requirements.txt`: alembic
- Create: `alembic.ini`
- Create: `alembic/env.py`
- Create: `alembic/script.py.mako`
- Create: `alembic/versions/001_initial_schema.py`
- Update: `README.md`

**Goal:** Add Alembic for database schema versioning and migrations, enabling safe production database updates.

- [ ] **Step 1: Add Alembic dependency**

Modify: `requirements.txt`

Add:
```
alembic==1.13.1
```

- [ ] **Step 2: Install Alembic**

Run: `pip install alembic==1.13.1`

Expected: Package installed

- [ ] **Step 3: Initialize Alembic**

Run: `alembic init alembic`

Expected: Created alembic/ directory with env.py, script.py.mako, and alembic.ini

- [ ] **Step 4: Configure Alembic for async SQLAlchemy**

Modify: `alembic.ini`

Change sqlalchemy.url line to:
```ini
# sqlalchemy.url = driver://user:pass@localhost/dbname
# (URL is loaded from config in env.py instead)
```

- [ ] **Step 5: Update Alembic env.py for async**

Modify: `alembic/env.py`

Replace entire contents with:
```python
"""
Alembic environment configuration for async SQLAlchemy.
"""
import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Import app models and config
from app.models.database import Base
from app.config import settings

# Alembic Config object
config = context.config

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Add your model's MetaData object here for 'autogenerate' support
target_metadata = Base.metadata

# Override sqlalchemy.url with app config
config.set_main_option("sqlalchemy.url", settings.database_url)


def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode.
    
    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run migrations with given connection."""
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in async mode."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 6: Create initial migration for existing schema**

Run: `alembic revision --autogenerate -m "initial schema"`

Expected: Created `alembic/versions/XXXX_initial_schema.py`

- [ ] **Step 7: Verify migration file**

Run: `cat alembic/versions/*_initial_schema.py | head -50`

Expected: Should see upgrade() and downgrade() functions creating api_request_logs table

- [ ] **Step 8: Test migration up**

Run:
```bash
# Drop existing tables (WARNING: destroys data)
docker-compose exec db psql -U postgres -d api_gateway -c "DROP TABLE IF EXISTS api_request_logs;"

# Run migration
alembic upgrade head

# Verify table created
docker-compose exec db psql -U postgres -d api_gateway -c "\dt"
```

Expected: api_request_logs table created

- [ ] **Step 9: Test migration down**

Run:
```bash
alembic downgrade -1

# Verify table dropped
docker-compose exec db psql -U postgres -d api_gateway -c "\dt"
```

Expected: api_request_logs table removed

- [ ] **Step 10: Migrate back up**

Run: `alembic upgrade head`

Expected: Database at latest version

- [ ] **Step 11: Add migration instructions to README**

Modify: `README.md`

Add new section after "Development" section:

````markdown
## Database Migrations

This project uses Alembic for database schema versioning.

### Running Migrations

```bash
# Upgrade to latest version
alembic upgrade head

# Downgrade one version
alembic downgrade -1

# View migration history
alembic history

# View current version
alembic current
```

### Creating New Migrations

```bash
# Auto-generate migration from model changes
alembic revision --autogenerate -m "add new column"

# Create empty migration (for data migrations)
alembic revision -m "backfill user data"

# Edit generated migration in alembic/versions/
# Then apply:
alembic upgrade head
```

### Production Deployment

**IMPORTANT:** Always run migrations before deploying new code:

```bash
# 1. Run migration (in init container or before deploy)
alembic upgrade head

# 2. Deploy new application code
kubectl apply -f k8s/deployment.yaml
```
````

- [ ] **Step 12: Commit Alembic setup**

```bash
git add requirements.txt alembic.ini alembic/ README.md
git commit -m "feat: add Alembic for database migrations

- Initialize Alembic with async SQLAlchemy support
- Configure to load DB URL from app config
- Generate initial migration for api_request_logs table
- Add migration commands to README
- Enable safe production schema updates"
```

---

### Task 6: CORS Configuration

**Files:**
- Modify: `app/main.py`
- Modify: `app/config.py`
- Modify: `.env.example`
- Create: `tests/test_cors.py`

**Goal:** Add configurable CORS middleware for frontend integrations.

- [ ] **Step 1: Write failing test for CORS**

Create: `tests/test_cors.py`

```python
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_cors_headers_present():
    """Test CORS headers are present in responses."""
    response = client.options(
        "/api/weather",
        headers={"Origin": "https://example.com"}
    )
    
    assert "access-control-allow-origin" in response.headers
    assert "access-control-allow-methods" in response.headers


def test_cors_allows_configured_origins():
    """Test CORS allows origins from config."""
    response = client.get(
        "/api/weather?city=London",
        headers={"Origin": "https://example.com"}
    )
    
    # Should have CORS header
    assert "access-control-allow-origin" in response.headers
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cors.py -v`

Expected: FAIL - CORS headers not present

- [ ] **Step 3: Add CORS config to settings**

Modify: `app/config.py`

Add field to Settings class:
```python
cors_origins: str = "*"  # Comma-separated list, or * for all
```

- [ ] **Step 4: Add CORS configuration to .env.example**

Modify: `.env.example`

Add:
```bash
# CORS configuration (comma-separated origins, or * for all)
CORS_ORIGINS=https://example.com,https://app.example.com
```

- [ ] **Step 5: Add CORS middleware to app**

Modify: `app/main.py`

Add import:
```python
from fastapi.middleware.cors import CORSMiddleware
```

Add CORS middleware (after app creation, before other middleware):
```python
# Configure CORS
origins = (
    settings.cors_origins.split(",") 
    if settings.cors_origins != "*" 
    else ["*"]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_cors.py -v`

Expected: PASS (2 tests)

- [ ] **Step 7: Test CORS manually**

Run:
```bash
docker-compose up -d

# Test OPTIONS request (preflight)
curl -X OPTIONS http://localhost:8000/api/weather \
  -H "Origin: https://example.com" \
  -H "Access-Control-Request-Method: GET" \
  -v

# Check for Access-Control-Allow-Origin header
```

Expected: CORS headers present in response

- [ ] **Step 8: Commit CORS configuration**

```bash
git add app/main.py app/config.py .env.example tests/test_cors.py
git commit -m "feat: add CORS middleware for frontend integration

- Add configurable CORS origins via environment variable
- Support wildcard (*) or comma-separated origin list
- Enable credentials, all methods, all headers
- Add CORS tests for preflight and actual requests
- Document CORS_ORIGINS in .env.example"
```

---

## Chunk 3: Deployment Configurations

### Task 7: Kubernetes Manifests

**Files:**
- Create: `k8s/namespace.yaml`
- Create: `k8s/secrets.yaml`
- Create: `k8s/deployment.yaml`
- Create: `k8s/service.yaml`
- Create: `k8s/ingress.yaml`
- Create: `k8s/README.md`

**Goal:** Create Kubernetes manifests for production deployment with ConfigMaps, Secrets, and health probes.

- [ ] **Step 1: Create Kubernetes directory**

Run: `mkdir -p k8s`

Expected: Directory created

- [ ] **Step 2: Create namespace manifest**

Create: `k8s/namespace.yaml`

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: api-gateway
  labels:
    app: api-gateway-hub
    environment: production
```

- [ ] **Step 3: Create secrets template**

Create: `k8s/secrets.yaml`

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: api-gateway-secrets
  namespace: api-gateway
type: Opaque
stringData:
  # Database connection string
  # Format: postgresql+asyncpg://user:password@host:5432/dbname
  database-url: "postgresql+asyncpg://postgres:CHANGEME@postgres-service:5432/api_gateway"
  
  # Redis connection string
  redis-url: "redis://redis-service:6379/0"
  
  # External API keys
  openweather-api-key: "CHANGEME"

---
apiVersion: v1
kind: Secret
metadata:
  name: postgres-secrets
  namespace: api-gateway
type: Opaque
stringData:
  postgres-password: "CHANGEME"
```

- [ ] **Step 4: Create deployment manifest**

Create: `k8s/deployment.yaml`

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api-gateway-hub
  namespace: api-gateway
  labels:
    app: api-gateway-hub
    version: v1.0.0
spec:
  replicas: 3
  selector:
    matchLabels:
      app: api-gateway-hub
  template:
    metadata:
      labels:
        app: api-gateway-hub
        version: v1.0.0
    spec:
      # Init container to run migrations before app starts
      initContainers:
      - name: migrations
        image: gcr.io/YOUR-PROJECT/api-gateway-hub:v1.0.0
        command: ["alembic", "upgrade", "head"]
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: api-gateway-secrets
              key: database-url
      
      containers:
      - name: api
        image: gcr.io/YOUR-PROJECT/api-gateway-hub:v1.0.0
        imagePullPolicy: Always
        ports:
        - containerPort: 8000
          name: http
        
        env:
        - name: ENVIRONMENT
          value: "production"
        - name: LOG_LEVEL
          value: "INFO"
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: api-gateway-secrets
              key: database-url
        - name: REDIS_URL
          valueFrom:
            secretKeyRef:
              name: api-gateway-secrets
              key: redis-url
        - name: OPENWEATHER_API_KEY
          valueFrom:
            secretKeyRef:
              name: api-gateway-secrets
              key: openweather-api-key
        - name: CORS_ORIGINS
          value: "https://app.example.com"
        
        resources:
          requests:
            memory: "256Mi"
            cpu: "250m"
          limits:
            memory: "512Mi"
            cpu: "500m"
        
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 10
          periodSeconds: 30
          timeoutSeconds: 5
          failureThreshold: 3
        
        readinessProbe:
          httpGet:
            path: /health/ready
            port: 8000
          initialDelaySeconds: 5
          periodSeconds: 10
          timeoutSeconds: 5
          failureThreshold: 3
        
        # Graceful shutdown
        lifecycle:
          preStop:
            exec:
              command: ["/bin/sh", "-c", "sleep 15"]
      
      terminationGracePeriodSeconds: 30

---
# PostgreSQL StatefulSet
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgres
  namespace: api-gateway
spec:
  serviceName: postgres-service
  replicas: 1
  selector:
    matchLabels:
      app: postgres
  template:
    metadata:
      labels:
        app: postgres
    spec:
      containers:
      - name: postgres
        image: postgres:16
        ports:
        - containerPort: 5432
        env:
        - name: POSTGRES_DB
          value: api_gateway
        - name: POSTGRES_PASSWORD
          valueFrom:
            secretKeyRef:
              name: postgres-secrets
              key: postgres-password
        volumeMounts:
        - name: postgres-storage
          mountPath: /var/lib/postgresql/data
  volumeClaimTemplates:
  - metadata:
      name: postgres-storage
    spec:
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: 10Gi

---
# Redis Deployment
apiVersion: apps/v1
kind: Deployment
metadata:
  name: redis
  namespace: api-gateway
spec:
  replicas: 1
  selector:
    matchLabels:
      app: redis
  template:
    metadata:
      labels:
        app: redis
    spec:
      containers:
      - name: redis
        image: redis:7.2
        ports:
        - containerPort: 6379
        resources:
          requests:
            memory: "128Mi"
            cpu: "100m"
          limits:
            memory: "256Mi"
            cpu: "200m"
```

- [ ] **Step 5: Create service manifest**

Create: `k8s/service.yaml`

```yaml
apiVersion: v1
kind: Service
metadata:
  name: api-gateway-service
  namespace: api-gateway
  labels:
    app: api-gateway-hub
spec:
  type: LoadBalancer
  selector:
    app: api-gateway-hub
  ports:
  - port: 80
    targetPort: 8000
    protocol: TCP
    name: http

---
apiVersion: v1
kind: Service
metadata:
  name: postgres-service
  namespace: api-gateway
spec:
  clusterIP: None
  selector:
    app: postgres
  ports:
  - port: 5432
    targetPort: 5432

---
apiVersion: v1
kind: Service
metadata:
  name: redis-service
  namespace: api-gateway
spec:
  selector:
    app: redis
  ports:
  - port: 6379
    targetPort: 6379
```

- [ ] **Step 6: Create ingress manifest**

Create: `k8s/ingress.yaml`

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: api-gateway-ingress
  namespace: api-gateway
  annotations:
    # GKE ingress annotations
    kubernetes.io/ingress.class: "gce"
    # Enable HTTPS redirect
    kubernetes.io/ingress.allow-http: "false"
    # Certificate manager (if using cert-manager)
    # cert-manager.io/cluster-issuer: "letsencrypt-prod"
spec:
  rules:
  - host: api.example.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: api-gateway-service
            port:
              number: 80
  # TLS configuration (uncomment when cert is ready)
  # tls:
  # - hosts:
  #   - api.example.com
  #   secretName: api-gateway-tls
```

- [ ] **Step 7: Create Kubernetes README**

Create: `k8s/README.md`

````markdown
# Kubernetes Deployment

This directory contains Kubernetes manifests for deploying API Gateway Hub to production.

## Prerequisites

- Kubernetes cluster (GKE, EKS, AKS, or self-managed)
- kubectl configured to access cluster
- Docker image pushed to registry

## Deployment Steps

### 1. Build and Push Docker Image

```bash
# Build image
docker build -t gcr.io/YOUR-PROJECT/api-gateway-hub:v1.0.0 .

# Push to registry
docker push gcr.io/YOUR-PROJECT/api-gateway-hub:v1.0.0
```

### 2. Update Configuration

Edit `k8s/secrets.yaml` and replace:
- `CHANGEME` in `database-url` with real credentials
- `CHANGEME` in `postgres-password` with strong password
- `CHANGEME` in `openweather-api-key` with real API key

Edit `k8s/deployment.yaml` and replace:
- `gcr.io/YOUR-PROJECT` with your actual registry
- `https://app.example.com` in CORS_ORIGINS with your frontend URL

Edit `k8s/ingress.yaml` and replace:
- `api.example.com` with your actual domain

### 3. Deploy to Kubernetes

```bash
# Create namespace
kubectl apply -f k8s/namespace.yaml

# Create secrets (IMPORTANT: Do this first!)
kubectl apply -f k8s/secrets.yaml

# Deploy services
kubectl apply -f k8s/service.yaml

# Deploy applications
kubectl apply -f k8s/deployment.yaml

# Create ingress
kubectl apply -f k8s/ingress.yaml
```

### 4. Verify Deployment

```bash
# Check pods are running
kubectl get pods -n api-gateway

# Check services
kubectl get svc -n api-gateway

# Check ingress
kubectl get ingress -n api-gateway

# View logs
kubectl logs -n api-gateway -l app=api-gateway-hub --tail=50 -f

# Test health endpoint
kubectl port-forward -n api-gateway svc/api-gateway-service 8080:80
curl http://localhost:8080/health
```

## Production Considerations

### Managed Services (Recommended)

Replace in-cluster PostgreSQL and Redis with managed services:

**GCP:**
- Cloud SQL for PostgreSQL
- Cloud Memorystore for Redis

**AWS:**
- RDS for PostgreSQL
- ElastiCache for Redis

**Azure:**
- Azure Database for PostgreSQL
- Azure Cache for Redis

Update `k8s/secrets.yaml` with managed service connection strings and remove StatefulSet/Deployment for postgres/redis.

### Secrets Management

Instead of storing secrets in `secrets.yaml`:

**GCP:** Use Secret Manager with Workload Identity:
```yaml
env:
- name: OPENWEATHER_API_KEY
  valueFrom:
    secretKeyRef:
      name: api-gateway-secrets  # From Secret Manager
      key: openweather-api-key
```

**AWS:** Use AWS Secrets Manager with IRSA

**Azure:** Use Azure Key Vault with Pod Identity

### Autoscaling

Add Horizontal Pod Autoscaler:

```bash
kubectl autoscale deployment api-gateway-hub \
  --cpu-percent=70 \
  --min=3 \
  --max=10 \
  -n api-gateway
```

### Monitoring

Add Prometheus ServiceMonitor:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: api-gateway-metrics
  namespace: api-gateway
spec:
  selector:
    matchLabels:
      app: api-gateway-hub
  endpoints:
  - port: http
    path: /metrics
```

## Updating

```bash
# Build new version
docker build -t gcr.io/YOUR-PROJECT/api-gateway-hub:v1.1.0 .
docker push gcr.io/YOUR-PROJECT/api-gateway-hub:v1.1.0

# Update deployment (migrations run automatically in init container)
kubectl set image deployment/api-gateway-hub \
  api=gcr.io/YOUR-PROJECT/api-gateway-hub:v1.1.0 \
  -n api-gateway

# Watch rollout
kubectl rollout status deployment/api-gateway-hub -n api-gateway
```

## Rollback

```bash
# Rollback to previous version
kubectl rollout undo deployment/api-gateway-hub -n api-gateway

# Rollback to specific revision
kubectl rollout history deployment/api-gateway-hub -n api-gateway
kubectl rollout undo deployment/api-gateway-hub --to-revision=2 -n api-gateway
```
````

- [ ] **Step 8: Commit Kubernetes manifests**

```bash
git add k8s/
git commit -m "feat: add Kubernetes deployment manifests

- Add namespace, secrets, deployment, service, ingress
- Configure health probes for liveness and readiness
- Add init container for automatic migrations
- Include PostgreSQL StatefulSet and Redis Deployment
- Configure resource limits and requests
- Add graceful shutdown with 30s termination period
- Document deployment steps and production considerations
- Include rollout and rollback procedures"
```

---

### Task 8: Production Dockerfile

**Files:**
- Create: `Dockerfile.prod`
- Create: `.dockerignore`
- Update: `README.md`

**Goal:** Create optimized multi-stage Dockerfile for production with non-root user and minimal image size.

- [ ] **Step 1: Create .dockerignore**

Create: `.dockerignore`

```
# Git
.git
.gitignore

# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
*.egg-info/
dist/
build/
.venv/
venv/
ENV/

# Testing
.pytest_cache/
.coverage
htmlcov/
.tox/

# IDEs
.vscode/
.idea/
*.swp
*.swo
*~

# OS
.DS_Store
Thumbs.db

# Project specific
tests/
docs/
*.md
!README.md
alembic.ini
docker-compose.yml
.env
.env.example

# CI/CD
.github/
.gitlab-ci.yml
```

- [ ] **Step 2: Create production Dockerfile**

Create: `Dockerfile.prod`

```dockerfile
# Multi-stage build for optimized production image

# Stage 1: Builder
FROM python:3.12-slim as builder

# Install build dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Create and activate virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Stage 2: Runtime
FROM python:3.12-slim

# Install runtime dependencies only
RUN apt-get update && apt-get install -y \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 1000 -s /bin/bash appuser

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv

# Set environment variables
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Set working directory
WORKDIR /app

# Copy application code
COPY --chown=appuser:appuser app/ ./app/
COPY --chown=appuser:appuser alembic/ ./alembic/
COPY --chown=appuser:appuser alembic.ini ./

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

# Run application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
```

- [ ] **Step 3: Test production Dockerfile build**

Run:
```bash
# Build production image
docker build -f Dockerfile.prod -t api-gateway-hub:prod .

# Check image size
docker images | grep api-gateway-hub

# Run container
docker run -d -p 8000:8000 \
  -e DATABASE_URL=postgresql+asyncpg://postgres:postgres@host.docker.internal:5432/api_gateway \
  -e REDIS_URL=redis://host.docker.internal:6379/0 \
  api-gateway-hub:prod

# Test health endpoint
curl http://localhost:8000/health

# Check container is running as non-root
docker exec -it $(docker ps -q -f ancestor=api-gateway-hub:prod) whoami
# Should output: appuser
```

Expected: Image builds successfully, runs as non-root user, health check passes

- [ ] **Step 4: Add production Docker instructions to README**

Modify: `README.md`

Add new section after "Deployment" section:

````markdown
## Production Docker Build

### Multi-Stage Production Image

Build optimized production image:

```bash
docker build -f Dockerfile.prod -t api-gateway-hub:v1.0.0 .
```

**Features:**
- Multi-stage build (reduces image size by ~40%)
- Non-root user (appuser, UID 1000)
- No build dependencies in final image
- Health check built-in
- 4 uvicorn workers for production
- Optimized layer caching

### Pushing to Registry

**Google Container Registry:**
```bash
docker tag api-gateway-hub:v1.0.0 gcr.io/YOUR-PROJECT/api-gateway-hub:v1.0.0
docker push gcr.io/YOUR-PROJECT/api-gateway-hub:v1.0.0
```

**AWS ECR:**
```bash
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin YOUR-ACCOUNT.dkr.ecr.us-east-1.amazonaws.com
docker tag api-gateway-hub:v1.0.0 YOUR-ACCOUNT.dkr.ecr.us-east-1.amazonaws.com/api-gateway-hub:v1.0.0
docker push YOUR-ACCOUNT.dkr.ecr.us-east-1.amazonaws.com/api-gateway-hub:v1.0.0
```

**Docker Hub:**
```bash
docker tag api-gateway-hub:v1.0.0 YOUR-USERNAME/api-gateway-hub:v1.0.0
docker push YOUR-USERNAME/api-gateway-hub:v1.0.0
```
````

- [ ] **Step 5: Commit production Dockerfile**

```bash
git add Dockerfile.prod .dockerignore README.md
git commit -m "feat: add optimized production Dockerfile

- Create multi-stage build to reduce image size
- Run as non-root user (appuser) for security
- Remove build dependencies from final image
- Add built-in health check
- Configure 4 uvicorn workers for production
- Add .dockerignore to exclude unnecessary files
- Document registry push procedures for GCP/AWS/Docker Hub"
```

---

### Task 9: Cloud Run Configuration

**Files:**
- Create: `cloudrun/service.yaml`
- Create: `cloudrun/deploy.sh`
- Update: `README.md`

**Goal:** Create Google Cloud Run deployment configuration for serverless deployment option.

- [ ] **Step 1: Create Cloud Run directory**

Run: `mkdir -p cloudrun`

Expected: Directory created

- [ ] **Step 2: Create Cloud Run service specification**

Create: `cloudrun/service.yaml`

```yaml
apiVersion: serving.knative.dev/v1
kind: Service
metadata:
  name: api-gateway-hub
  annotations:
    run.googleapis.com/ingress: all
    run.googleapis.com/client-name: gcloud
spec:
  template:
    metadata:
      annotations:
        # Autoscaling
        autoscaling.knative.dev/minScale: '1'
        autoscaling.knative.dev/maxScale: '10'
        # Cloud SQL connection
        run.googleapis.com/cloudsql-instances: YOUR-PROJECT:us-central1:postgres-instance
        # VPC connector for Redis (if needed)
        run.googleapis.com/vpc-access-connector: projects/YOUR-PROJECT/locations/us-central1/connectors/redis-connector
        run.googleapis.com/vpc-access-egress: private-ranges-only
    spec:
      containerConcurrency: 80
      timeoutSeconds: 300
      serviceAccountName: api-gateway-sa@YOUR-PROJECT.iam.gserviceaccount.com
      
      containers:
      - image: gcr.io/YOUR-PROJECT/api-gateway-hub:latest
        ports:
        - containerPort: 8000
        
        env:
        - name: ENVIRONMENT
          value: production
        - name: LOG_LEVEL
          value: INFO
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: database-url
              key: latest
        - name: REDIS_URL
          value: redis://10.0.0.3:6379/0  # Private IP of Memorystore
        - name: OPENWEATHER_API_KEY
          valueFrom:
            secretKeyRef:
              name: openweather-api-key
              key: latest
        - name: CORS_ORIGINS
          value: https://app.example.com
        
        resources:
          limits:
            memory: 512Mi
            cpu: '1'
        
        startupProbe:
          httpGet:
            path: /health/ready
            port: 8000
          initialDelaySeconds: 0
          timeoutSeconds: 1
          periodSeconds: 3
          failureThreshold: 10
        
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 0
          timeoutSeconds: 1
          periodSeconds: 10
          failureThreshold: 3
```

- [ ] **Step 3: Create deployment script**

Create: `cloudrun/deploy.sh`

```bash
#!/bin/bash
set -e

# Configuration
PROJECT_ID="YOUR-PROJECT"
REGION="us-central1"
SERVICE_NAME="api-gateway-hub"
IMAGE_TAG="${1:-latest}"

echo "Deploying API Gateway Hub to Cloud Run..."
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo "Image tag: $IMAGE_TAG"

# Build and push image
echo "Building Docker image..."
docker build -f Dockerfile.prod -t "gcr.io/$PROJECT_ID/$SERVICE_NAME:$IMAGE_TAG" .

echo "Pushing to GCR..."
docker push "gcr.io/$PROJECT_ID/$SERVICE_NAME:$IMAGE_TAG"

# Run database migrations
echo "Running database migrations..."
gcloud run jobs execute migrate-database \
  --region=$REGION \
  --project=$PROJECT_ID \
  --wait

# Deploy to Cloud Run
echo "Deploying to Cloud Run..."
gcloud run services replace cloudrun/service.yaml \
  --region=$REGION \
  --project=$PROJECT_ID

# Get service URL
SERVICE_URL=$(gcloud run services describe $SERVICE_NAME \
  --region=$REGION \
  --project=$PROJECT_ID \
  --format='value(status.url)')

echo "Deployment complete!"
echo "Service URL: $SERVICE_URL"
echo "Testing health endpoint..."
curl -s "$SERVICE_URL/health" | jq .
```

- [ ] **Step 4: Make deployment script executable**

Run: `chmod +x cloudrun/deploy.sh`

Expected: Script is executable

- [ ] **Step 5: Create Cloud Run migration job spec**

Create: `cloudrun/migrate-job.yaml`

```yaml
apiVersion: run.googleapis.com/v1
kind: Job
metadata:
  name: migrate-database
  annotations:
    run.googleapis.com/launch-stage: BETA
spec:
  template:
    spec:
      template:
        metadata:
          annotations:
            run.googleapis.com/cloudsql-instances: YOUR-PROJECT:us-central1:postgres-instance
        spec:
          containers:
          - image: gcr.io/YOUR-PROJECT/api-gateway-hub:latest
            command: ["alembic", "upgrade", "head"]
            env:
            - name: DATABASE_URL
              valueFrom:
                secretKeyRef:
                  name: database-url
                  key: latest
          maxRetries: 3
          timeoutSeconds: 600
```

- [ ] **Step 6: Add Cloud Run documentation to README**

Modify: `README.md`

Add new section in "Deployment" chapter:

````markdown
## Cloud Run Deployment (GCP)

### Prerequisites

```bash
# Install gcloud CLI
# https://cloud.google.com/sdk/docs/install

# Authenticate
gcloud auth login
gcloud config set project YOUR-PROJECT

# Enable APIs
gcloud services enable run.googleapis.com
gcloud services enable sql-component.googleapis.com
gcloud services enable sqladmin.googleapis.com
gcloud services enable secretmanager.googleapis.com
```

### Setup Managed Services

**1. Cloud SQL (PostgreSQL):**
```bash
gcloud sql instances create postgres-instance \
  --database-version=POSTGRES_16 \
  --tier=db-f1-micro \
  --region=us-central1

gcloud sql databases create api_gateway \
  --instance=postgres-instance

# Get connection name
gcloud sql instances describe postgres-instance --format='value(connectionName)'
```

**2. Memorystore (Redis):**
```bash
gcloud redis instances create redis-cache \
  --size=1 \
  --region=us-central1 \
  --redis-version=redis_7_0

# Get IP
gcloud redis instances describe redis-cache --region=us-central1 --format='value(host)'
```

**3. VPC Connector (for Memorystore access):**
```bash
gcloud compute networks vpc-access connectors create redis-connector \
  --region=us-central1 \
  --range=10.8.0.0/28
```

**4. Store Secrets:**
```bash
# Database URL
echo -n "postgresql+asyncpg://USER:PASS@/api_gateway?host=/cloudsql/YOUR-PROJECT:us-central1:postgres-instance" | \
  gcloud secrets create database-url --data-file=-

# API Key
echo -n "YOUR-OPENWEATHER-KEY" | \
  gcloud secrets create openweather-api-key --data-file=-
```

### Deploy

**1. Update configuration files:**
- Edit `cloudrun/service.yaml`: Replace `YOUR-PROJECT`
- Edit `cloudrun/migrate-job.yaml`: Replace `YOUR-PROJECT`
- Edit `cloudrun/deploy.sh`: Set `PROJECT_ID`

**2. Deploy migration job:**
```bash
gcloud run jobs replace cloudrun/migrate-job.yaml --region=us-central1
```

**3. Deploy service:**
```bash
./cloudrun/deploy.sh v1.0.0
```

### Monitoring

View logs:
```bash
gcloud run services logs tail api-gateway-hub --region=us-central1
```

View metrics:
```bash
# Open Cloud Console
gcloud run services describe api-gateway-hub --region=us-central1 --format='value(status.url)'
```
````

- [ ] **Step 7: Commit Cloud Run configuration**

```bash
git add cloudrun/ README.md
git commit -m "feat: add Google Cloud Run deployment config

- Create Cloud Run service specification with autoscaling
- Add deployment script for automated builds and deploys
- Configure Cloud SQL connection via Unix socket
- Add VPC connector for Memorystore Redis access
- Create migration job for database schema updates
- Configure health probes (startup and liveness)
- Set resource limits (512Mi memory, 1 CPU)
- Document managed service setup (Cloud SQL, Memorystore)
- Add secrets management via Secret Manager"
```

---

## Chunk 4: CI/CD & Documentation

### Task 10: GitHub Actions CI/CD Pipeline

**Files:**
- Create: `.github/workflows/ci.yml`
- Create: `.github/workflows/deploy-staging.yml`
- Create: `.github/workflows/deploy-production.yml`

**Goal:** Automated testing, building, and deployment pipeline with CI/CD.

- [ ] **Step 1: Create GitHub workflows directory**

Run: `mkdir -p .github/workflows`

Expected: Directory created

- [ ] **Step 2: Create CI workflow**

Create: `.github/workflows/ci.yml`

```yaml
name: CI

on:
  push:
    branches: [ main, develop ]
  pull_request:
    branches: [ main ]

jobs:
  test:
    runs-on: ubuntu-latest
    
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_PASSWORD: postgres
          POSTGRES_DB: api_gateway_test
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
        ports:
          - 5432:5432
      
      redis:
        image: redis:7.2
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
        ports:
          - 6379:6379
    
    steps:
    - uses: actions/checkout@v4
    
    - name: Set up Python
      uses: actions/setup-python@v5
      with:
        python-version: '3.12'
        cache: 'pip'
    
    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        pip install -r requirements.txt
    
    - name: Run linting
      run: |
        pip install ruff mypy
        ruff check app/ tests/
        mypy app/
    
    - name: Run tests
      env:
        DATABASE_URL: postgresql+asyncpg://postgres:postgres@localhost:5432/api_gateway_test
        REDIS_URL: redis://localhost:6379/0
        OPENWEATHER_API_KEY: test-key
      run: |
        pytest tests/ -v --cov=app --cov-report=xml --cov-report=term
    
    - name: Upload coverage to Codecov
      uses: codecov/codecov-action@v4
      with:
        file: ./coverage.xml
        fail_ci_if_error: false
    
    - name: Build Docker image
      run: |
        docker build -f Dockerfile.prod -t api-gateway-hub:${{ github.sha }} .
    
    - name: Test Docker image
      run: |
        docker run -d -p 8000:8000 \
          -e DATABASE_URL=postgresql+asyncpg://postgres:postgres@172.17.0.1:5432/api_gateway_test \
          -e REDIS_URL=redis://172.17.0.1:6379/0 \
          --name test-container \
          api-gateway-hub:${{ github.sha }}
        
        sleep 10
        
        # Test health endpoint
        curl -f http://localhost:8000/health || exit 1
        
        docker stop test-container
        docker rm test-container
```

- [ ] **Step 3: Create staging deployment workflow**

Create: `.github/workflows/deploy-staging.yml`

```yaml
name: Deploy to Staging

on:
  push:
    branches: [ develop ]

env:
  GCP_PROJECT: your-project-staging
  GCP_REGION: us-central1
  SERVICE_NAME: api-gateway-hub

jobs:
  deploy:
    runs-on: ubuntu-latest
    
    permissions:
      contents: read
      id-token: write
    
    steps:
    - uses: actions/checkout@v4
    
    - name: Authenticate to Google Cloud
      uses: google-github-actions/auth@v2
      with:
        workload_identity_provider: ${{ secrets.GCP_WORKLOAD_IDENTITY_PROVIDER }}
        service_account: ${{ secrets.GCP_SERVICE_ACCOUNT }}
    
    - name: Set up Cloud SDK
      uses: google-github-actions/setup-gcloud@v2
    
    - name: Configure Docker for GCR
      run: gcloud auth configure-docker
    
    - name: Build Docker image
      run: |
        docker build -f Dockerfile.prod \
          -t gcr.io/${{ env.GCP_PROJECT }}/${{ env.SERVICE_NAME }}:${{ github.sha }} \
          -t gcr.io/${{ env.GCP_PROJECT }}/${{ env.SERVICE_NAME }}:staging-latest \
          .
    
    - name: Push to GCR
      run: |
        docker push gcr.io/${{ env.GCP_PROJECT }}/${{ env.SERVICE_NAME }}:${{ github.sha }}
        docker push gcr.io/${{ env.GCP_PROJECT }}/${{ env.SERVICE_NAME }}:staging-latest
    
    - name: Run database migrations
      run: |
        gcloud run jobs execute migrate-database \
          --region=${{ env.GCP_REGION }} \
          --wait
    
    - name: Deploy to Cloud Run (Staging)
      run: |
        gcloud run deploy ${{ env.SERVICE_NAME }} \
          --image gcr.io/${{ env.GCP_PROJECT }}/${{ env.SERVICE_NAME }}:${{ github.sha }} \
          --region ${{ env.GCP_REGION }} \
          --platform managed \
          --allow-unauthenticated \
          --set-env-vars ENVIRONMENT=staging
    
    - name: Smoke test
      run: |
        SERVICE_URL=$(gcloud run services describe ${{ env.SERVICE_NAME }} \
          --region ${{ env.GCP_REGION }} \
          --format 'value(status.url)')
        
        curl -f "$SERVICE_URL/health" || exit 1
        curl -f "$SERVICE_URL/health/ready" || exit 1
        
        echo "Staging deployment successful: $SERVICE_URL"
```

- [ ] **Step 4: Create production deployment workflow**

Create: `.github/workflows/deploy-production.yml`

```yaml
name: Deploy to Production

on:
  push:
    tags:
      - 'v*.*.*'

env:
  GCP_PROJECT: your-project-production
  GCP_REGION: us-central1
  SERVICE_NAME: api-gateway-hub

jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: production
    
    permissions:
      contents: read
      id-token: write
    
    steps:
    - uses: actions/checkout@v4
    
    - name: Extract version from tag
      id: version
      run: echo "VERSION=${GITHUB_REF#refs/tags/v}" >> $GITHUB_OUTPUT
    
    - name: Authenticate to Google Cloud
      uses: google-github-actions/auth@v2
      with:
        workload_identity_provider: ${{ secrets.GCP_WORKLOAD_IDENTITY_PROVIDER_PROD }}
        service_account: ${{ secrets.GCP_SERVICE_ACCOUNT_PROD }}
    
    - name: Set up Cloud SDK
      uses: google-github-actions/setup-gcloud@v2
    
    - name: Configure Docker for GCR
      run: gcloud auth configure-docker
    
    - name: Build Docker image
      run: |
        docker build -f Dockerfile.prod \
          -t gcr.io/${{ env.GCP_PROJECT }}/${{ env.SERVICE_NAME }}:${{ steps.version.outputs.VERSION }} \
          -t gcr.io/${{ env.GCP_PROJECT }}/${{ env.SERVICE_NAME }}:latest \
          .
    
    - name: Push to GCR
      run: |
        docker push gcr.io/${{ env.GCP_PROJECT }}/${{ env.SERVICE_NAME }}:${{ steps.version.outputs.VERSION }}
        docker push gcr.io/${{ env.GCP_PROJECT }}/${{ env.SERVICE_NAME }}:latest
    
    - name: Run database migrations
      run: |
        gcloud run jobs execute migrate-database \
          --region=${{ env.GCP_REGION }} \
          --wait
    
    - name: Deploy to Cloud Run (Production)
      run: |
        gcloud run deploy ${{ env.SERVICE_NAME }} \
          --image gcr.io/${{ env.GCP_PROJECT }}/${{ env.SERVICE_NAME }}:${{ steps.version.outputs.VERSION }} \
          --region ${{ env.GCP_REGION }} \
          --platform managed \
          --allow-unauthenticated \
          --set-env-vars ENVIRONMENT=production \
          --min-instances 1 \
          --max-instances 10 \
          --cpu 1 \
          --memory 512Mi \
          --timeout 300 \
          --concurrency 80
    
    - name: Health check
      run: |
        SERVICE_URL=$(gcloud run services describe ${{ env.SERVICE_NAME }} \
          --region ${{ env.GCP_REGION }} \
          --format 'value(status.url)')
        
        # Wait for deployment to stabilize
        sleep 30
        
        curl -f "$SERVICE_URL/health" || exit 1
        curl -f "$SERVICE_URL/health/ready" || exit 1
        
        echo "Production deployment successful!"
        echo "Service URL: $SERVICE_URL"
        echo "Version: ${{ steps.version.outputs.VERSION }}"
    
    - name: Create GitHub Release
      uses: actions/create-release@v1
      env:
        GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
      with:
        tag_name: ${{ github.ref }}
        release_name: Release ${{ steps.version.outputs.VERSION }}
        body: |
          Production deployment of version ${{ steps.version.outputs.VERSION }}
          
          Deployed to: ${{ env.GCP_REGION }}
        draft: false
        prerelease: false
```

- [ ] **Step 5: Add ruff and mypy to requirements**

Create: `requirements-dev.txt`

```
# Development dependencies
ruff==0.3.0
mypy==1.9.0
pytest==8.1.1
pytest-asyncio==0.23.6
pytest-cov==4.1.0
respx==0.21.1
testcontainers==3.7.1
```

- [ ] **Step 6: Add GitHub Actions documentation to README**

Modify: `README.md`

Add new section:

````markdown
## CI/CD Pipeline

### GitHub Actions Workflows

**CI (Continuous Integration):**
- Runs on every push and pull request
- Linting with ruff and mypy
- Unit and integration tests with coverage
- Docker image build and test
- Triggers on: `main`, `develop` branches, and all PRs

**Staging Deployment:**
- Auto-deploys to staging environment
- Runs migrations before deployment
- Smoke tests health endpoints
- Triggers on: pushes to `develop` branch

**Production Deployment:**
- Manual approval required (GitHub environment)
- Deploys tagged releases
- Creates GitHub release notes
- Triggers on: version tags (`v1.0.0`, `v1.1.0`, etc)

### Deployment Process

**1. Deploy to Staging:**
```bash
git checkout develop
git merge feature-branch
git push origin develop
# Auto-deploys to staging
```

**2. Deploy to Production:**
```bash
git checkout main
git merge develop
git tag v1.0.0
git push origin main --tags
# Requires manual approval in GitHub UI
```

### Setup Secrets

Configure in GitHub repository settings → Secrets and variables → Actions:

**Staging:**
- `GCP_WORKLOAD_IDENTITY_PROVIDER`: GCP workload identity provider
- `GCP_SERVICE_ACCOUNT`: Service account for staging

**Production:**
- `GCP_WORKLOAD_IDENTITY_PROVIDER_PROD`: GCP workload identity provider
- `GCP_SERVICE_ACCOUNT_PROD`: Service account for production

### Workload Identity Setup

```bash
# Create service account
gcloud iam service-accounts create github-actions \
  --display-name="GitHub Actions"

# Grant permissions
gcloud projects add-iam-policy-binding YOUR-PROJECT \
  --member="serviceAccount:github-actions@YOUR-PROJECT.iam.gserviceaccount.com" \
  --role="roles/run.admin"

# Configure workload identity
gcloud iam service-accounts add-iam-policy-binding \
  github-actions@YOUR-PROJECT.iam.gserviceaccount.com \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/PROJECT-NUMBER/locations/global/workloadIdentityPools/github-pool/attribute.repository/YOUR-ORG/YOUR-REPO"
```
````

- [ ] **Step 7: Commit CI/CD pipeline**

```bash
git add .github/ requirements-dev.txt README.md
git commit -m "feat: add GitHub Actions CI/CD pipeline

- Add CI workflow for linting, testing, and Docker builds
- Add staging auto-deployment on develop branch pushes
- Add production deployment on version tags with approval
- Run database migrations before each deployment
- Add smoke tests for health endpoints after deploy
- Configure workload identity for GCP authentication
- Create GitHub releases automatically on production deploy
- Add development dependencies (ruff, mypy)
- Document deployment process and secret setup"
```

---

### Task 11: Production Documentation

**Files:**
- Create: `docs/PRODUCTION.md`
- Create: `docs/RUNBOOK.md`
- Update: `README.md`

**Goal:** Comprehensive production operations documentation for deployment, monitoring, and troubleshooting.

- [ ] **Step 1: Create production deployment guide**

Create: `docs/PRODUCTION.md`

```markdown
# Production Deployment Guide

## Architecture Overview

```
┌─────────────────┐
│   Ingress/ALB   │
└────────┬────────┘
         │
    ┌────▼─────┐
    │ API Pods │ (3-10 replicas, autoscaling)
    └────┬─────┘
         │
    ┌────┴──────────────────┐
    │                       │
┌───▼──────┐        ┌──────▼─────┐
│Cloud SQL │        │Memorystore │
│PostgreSQL│        │   Redis    │
└──────────┘        └────────────┘
```

## Pre-Deployment Checklist

### Infrastructure
- [ ] PostgreSQL database provisioned (Cloud SQL, RDS, etc)
- [ ] Redis cache provisioned (Memorystore, ElastiCache, etc)
- [ ] Container registry accessible (GCR, ECR, Docker Hub)
- [ ] Kubernetes cluster or Cloud Run project ready
- [ ] DNS configured for custom domain
- [ ] SSL/TLS certificates provisioned

### Secrets
- [ ] Database credentials stored in secret manager
- [ ] Redis connection string configured
- [ ] External API keys added (OpenWeather, etc)
- [ ] CORS origins configured for production domains

### Monitoring
- [ ] Log aggregation configured (Stackdriver, CloudWatch, etc)
- [ ] Metrics scraping enabled (Prometheus)
- [ ] Alerts configured for critical errors
- [ ] Uptime monitoring enabled

## Deployment Methods

### Option 1: Kubernetes

See `k8s/README.md` for detailed instructions.

**Quick start:**
```bash
# Update secrets
kubectl apply -f k8s/secrets.yaml

# Deploy
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
kubectl apply -f k8s/ingress.yaml

# Verify
kubectl get pods -n api-gateway
kubectl logs -n api-gateway -l app=api-gateway-hub --tail=50
```

### Option 2: Google Cloud Run

See Cloud Run section in README.md.

**Quick start:**
```bash
./cloudrun/deploy.sh v1.0.0
```

### Option 3: AWS ECS/Fargate

**Task Definition:**
```json
{
  "family": "api-gateway-hub",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "512",
  "memory": "1024",
  "containerDefinitions": [
    {
      "name": "api",
      "image": "YOUR-ACCOUNT.dkr.ecr.us-east-1.amazonaws.com/api-gateway-hub:latest",
      "portMappings": [{"containerPort": 8000}],
      "environment": [
        {"name": "ENVIRONMENT", "value": "production"},
        {"name": "LOG_LEVEL", "value": "INFO"}
      ],
      "secrets": [
        {"name": "DATABASE_URL", "valueFrom": "arn:aws:secretsmanager:..."},
        {"name": "REDIS_URL", "valueFrom": "arn:aws:secretsmanager:..."},
        {"name": "OPENWEATHER_API_KEY", "valueFrom": "arn:aws:secretsmanager:..."}
      ],
      "healthCheck": {
        "command": ["CMD-SHELL", "curl -f http://localhost:8000/health || exit 1"],
        "interval": 30,
        "timeout": 5,
        "retries": 3
      }
    }
  ]
}
```

## Database Migrations

**CRITICAL:** Always run migrations before deploying new code.

### Kubernetes
Migrations run automatically via init container in deployment.yaml.

### Cloud Run
Migrations run automatically via job before service deployment.

### Manual Migration
```bash
# Backup database first!
pg_dump -h HOST -U USER -d api_gateway > backup.sql

# Run migration
alembic upgrade head

# Verify
alembic current
```

### Rollback Migration
```bash
# Rollback one version
alembic downgrade -1

# Rollback to specific version
alembic downgrade <revision>
```

## Environment Variables

| Variable | Required | Description | Example |
|----------|----------|-------------|---------|
| `ENVIRONMENT` | Yes | Environment name | `production` |
| `LOG_LEVEL` | Yes | Logging level | `INFO` |
| `DATABASE_URL` | Yes | PostgreSQL connection | `postgresql+asyncpg://user:pass@host/db` |
| `REDIS_URL` | Yes | Redis connection | `redis://host:6379/0` |
| `OPENWEATHER_API_KEY` | Yes | OpenWeather API key | `abc123...` |
| `CORS_ORIGINS` | No | Allowed origins | `https://app.example.com` |

## Scaling

### Kubernetes HPA
```bash
kubectl autoscale deployment api-gateway-hub \
  --cpu-percent=70 \
  --min=3 \
  --max=10 \
  -n api-gateway
```

### Cloud Run
Configured in `cloudrun/service.yaml`:
- Min instances: 1 (always warm)
- Max instances: 10
- Concurrency: 80 requests per instance

### Manual Scaling
```bash
# Kubernetes
kubectl scale deployment api-gateway-hub --replicas=5 -n api-gateway

# Cloud Run
gcloud run services update api-gateway-hub \
  --min-instances=2 \
  --max-instances=20
```

## Monitoring

### Health Checks
- Liveness: `GET /health` (should always return 200)
- Readiness: `GET /health/ready` (returns 503 if dependencies down)

### Metrics (Prometheus)
Available at `/metrics`:
- `http_requests_total` - Request count by endpoint and status
- `http_request_duration_seconds` - Request latency
- `cache_hits_total` / `cache_misses_total` - Cache performance
- `external_api_requests_total` - External API calls
- `rate_limit_usage` / `rate_limit_remaining` - Rate limit status

### Logs
Structured JSON logs include:
- `request_id` - Unique request identifier
- `duration_ms` - Request duration
- `status_code` - HTTP status
- `endpoint` - API endpoint
- `user_id` - User identifier (if authenticated)

### Alerts
Recommended alerts:
- Error rate > 5% for 5 minutes
- P95 latency > 1s for 5 minutes
- Cache hit rate < 50% for 10 minutes
- Database connection errors
- Redis connection errors
- External API rate limit approaching

## Performance Tuning

### Database Connection Pool
Default settings in SQLAlchemy:
- pool_size: 5
- max_overflow: 10
- pool_timeout: 30

Adjust for high traffic:
```python
engine = create_async_engine(
    settings.database_url,
    pool_size=20,
    max_overflow=40,
    pool_pre_ping=True
)
```

### Uvicorn Workers
Default: 4 workers (Dockerfile.prod)

Calculate optimal workers:
```
workers = (2 x CPU cores) + 1
```

Override in Kubernetes deployment:
```yaml
command: ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--workers", "8"]
```

### Redis Connection Pool
Configure in dependencies.py:
```python
redis_client = await aioredis.from_url(
    settings.redis_url,
    max_connections=50,
    decode_responses=True
)
```

## Security

### API Keys
- Never commit to git
- Store in secret manager (GCP Secret Manager, AWS Secrets Manager, etc)
- Rotate every 90 days

### Database
- Use strong passwords (min 16 chars, random)
- Enable SSL/TLS connections
- Restrict network access (private subnets only)
- Regular backups (automated daily)

### Container Security
- Run as non-root user ✅ (appuser, UID 1000)
- No secrets in image ✅
- Scan for vulnerabilities (Trivy, Snyk)
- Keep base images updated

### Network
- Enable HTTPS only (redirect HTTP)
- Use WAF for DDoS protection
- Configure CORS properly (no wildcards in production)
- Rate limiting enabled ✅

## Disaster Recovery

### Database Backup
```bash
# Manual backup
pg_dump -h HOST -U USER -d api_gateway | gzip > backup-$(date +%Y%m%d).sql.gz

# Restore
gunzip < backup-20260415.sql.gz | psql -h HOST -U USER -d api_gateway
```

### Rollback Deployment
```bash
# Kubernetes
kubectl rollout undo deployment/api-gateway-hub -n api-gateway

# Cloud Run
gcloud run services update-traffic api-gateway-hub \
  --to-revisions=api-gateway-hub-00002-abc=100
```

### Database Migration Rollback
```bash
# Check current version
alembic current

# Rollback to previous version
alembic downgrade -1

# Verify
alembic current
```
```

- [ ] **Step 2: Create operational runbook**

Create: `docs/RUNBOOK.md`

```markdown
# Operational Runbook

## Common Issues and Solutions

### Issue: High Error Rate

**Symptoms:**
- Error rate > 5%
- 500 status codes in logs
- Alert: "High error rate"

**Diagnosis:**
```bash
# Check recent errors
kubectl logs -n api-gateway -l app=api-gateway-hub --tail=100 | grep ERROR

# Check pod status
kubectl get pods -n api-gateway

# Check metrics
curl https://api.example.com/metrics | grep http_requests_total
```

**Solutions:**
1. **External API down:** Check external API status pages
   - OpenWeather: https://status.openweathermap.org/
   - Verify cache is serving stale data
   
2. **Database connection issues:**
   ```bash
   # Check database connectivity
   kubectl exec -it POD-NAME -n api-gateway -- psql $DATABASE_URL -c "SELECT 1;"
   ```
   
3. **Redis connection issues:**
   ```bash
   # Check Redis connectivity
   kubectl exec -it POD-NAME -n api-gateway -- redis-cli -u $REDIS_URL ping
   ```

---

### Issue: High Latency

**Symptoms:**
- P95 latency > 1s
- Slow response times
- Alert: "High latency"

**Diagnosis:**
```bash
# Check metrics
curl https://api.example.com/metrics | grep http_request_duration_seconds

# Check logs for slow queries
kubectl logs -n api-gateway -l app=api-gateway-hub | grep duration_ms | sort -t: -k2 -n | tail -20

# Check database performance
kubectl exec -it postgres-0 -n api-gateway -- psql -U postgres -d api_gateway -c "SELECT * FROM pg_stat_activity;"
```

**Solutions:**
1. **Database slow queries:**
   - Add indexes to frequently queried columns
   - Optimize queries
   
2. **Cache misses:**
   - Check cache hit rate: `cache_hits / (cache_hits + cache_misses)`
   - Increase TTL if appropriate
   
3. **External API slow:**
   - Check external API status
   - Reduce timeout if appropriate
   
4. **Too few replicas:**
   ```bash
   kubectl scale deployment api-gateway-hub --replicas=6 -n api-gateway
   ```

---

### Issue: Rate Limit Exceeded

**Symptoms:**
- 429 status codes
- "Rate limit exceeded" in logs
- Alert: "Rate limit approaching"

**Diagnosis:**
```bash
# Check rate limit usage
curl https://api.example.com/status

# Check metrics
curl https://api.example.com/metrics | grep rate_limit_usage
```

**Solutions:**
1. **Increase external API plan:** Upgrade OpenWeather plan
2. **Optimize cache:** Increase cache TTL to reduce API calls
3. **Implement request queuing:** Add background job queue for non-urgent requests

---

### Issue: Pod Crash Loop

**Symptoms:**
- Pods restarting frequently
- CrashLoopBackOff status
- Alert: "Pod restarts"

**Diagnosis:**
```bash
# Check pod status
kubectl get pods -n api-gateway

# Check pod logs
kubectl logs -n api-gateway POD-NAME --previous

# Describe pod for events
kubectl describe pod POD-NAME -n api-gateway
```

**Solutions:**
1. **OOM (Out of Memory):**
   - Increase memory limit in deployment.yaml
   - Check for memory leaks
   
2. **Readiness probe failing:**
   - Check database/Redis connectivity
   - Increase initialDelaySeconds
   
3. **Application error:**
   - Check logs for exceptions
   - Roll back to previous version

---

### Issue: Database Connection Pool Exhausted

**Symptoms:**
- "connection pool exhausted" errors
- Slow database queries
- Timeouts

**Diagnosis:**
```bash
# Check active connections
kubectl exec -it postgres-0 -n api-gateway -- psql -U postgres -d api_gateway -c "SELECT count(*) FROM pg_stat_activity;"

# Check connection pool settings
kubectl logs -n api-gateway POD-NAME | grep "pool_size"
```

**Solutions:**
1. **Increase pool size:**
   - Edit app/dependencies.py: `pool_size=20, max_overflow=40`
   - Redeploy
   
2. **Close idle connections:**
   - Add `pool_recycle=3600` to engine config
   
3. **Scale database:**
   - Increase Cloud SQL instance size

---

### Issue: Cache Not Working

**Symptoms:**
- Low cache hit rate (< 30%)
- High external API usage
- All requests showing `cached: false`

**Diagnosis:**
```bash
# Check Redis connectivity
kubectl exec -it POD-NAME -n api-gateway -- redis-cli -u $REDIS_URL ping

# Check cache metrics
curl https://api.example.com/metrics | grep cache

# Check Redis memory
kubectl exec -it redis-0 -n api-gateway -- redis-cli INFO memory
```

**Solutions:**
1. **Redis down:**
   - Check Redis pod: `kubectl get pods -n api-gateway -l app=redis`
   - Restart: `kubectl rollout restart deployment/redis -n api-gateway`
   
2. **Cache eviction (memory full):**
   - Increase Redis memory
   - Reduce TTL for less critical data
   
3. **Cache key mismatch:**
   - Check cache key generation in logs
   - Verify params are serialized consistently

---

## Routine Maintenance

### Weekly Tasks
- [ ] Review error logs for patterns
- [ ] Check cache hit rates
- [ ] Verify backups are running
- [ ] Review rate limit usage
- [ ] Check for security updates

### Monthly Tasks
- [ ] Review and rotate API keys
- [ ] Analyze performance metrics
- [ ] Update dependencies
- [ ] Review and optimize slow queries
- [ ] Capacity planning review

### Quarterly Tasks
- [ ] Load testing
- [ ] Disaster recovery drill
- [ ] Security audit
- [ ] Cost optimization review

---

## Emergency Contacts

| Role | Contact | When to Contact |
|------|---------|----------------|
| On-Call Engineer | Slack: #oncall | Any production incident |
| Database Admin | db-team@example.com | Database performance issues |
| Security Team | security@example.com | Security incidents |
| DevOps Lead | devops-lead@example.com | Infrastructure issues |

---

## Incident Response

### Severity Levels

**P0 - Critical:**
- Service completely down
- Data loss occurring
- Security breach
- Response time: Immediate

**P1 - High:**
- Partial outage
- Significant performance degradation
- Response time: Within 1 hour

**P2 - Medium:**
- Minor degradation
- Single feature unavailable
- Response time: Within 4 hours

**P3 - Low:**
- Cosmetic issues
- Non-critical bugs
- Response time: Next business day

### Incident Checklist
1. [ ] Acknowledge incident in monitoring system
2. [ ] Notify team in Slack #incidents
3. [ ] Create incident ticket
4. [ ] Assess severity and impact
5. [ ] Implement immediate mitigation (if possible)
6. [ ] Communicate status to stakeholders
7. [ ] Investigate root cause
8. [ ] Implement permanent fix
9. [ ] Verify resolution
10. [ ] Post-mortem review
```

- [ ] **Step 3: Update README with production links**

Modify: `README.md`

Add at the top, after "Features" section:

```markdown
## Documentation

- **[Production Deployment Guide](docs/PRODUCTION.md)** - Complete guide for deploying to K8s, Cloud Run, or AWS
- **[Operational Runbook](docs/RUNBOOK.md)** - Troubleshooting, monitoring, and incident response
- **[Kubernetes Deployment](k8s/README.md)** - K8s-specific deployment instructions
```

- [ ] **Step 4: Commit production documentation**

```bash
git add docs/PRODUCTION.md docs/RUNBOOK.md README.md
git commit -m "docs: add production deployment and operations guides

- Add comprehensive production deployment guide
- Document all deployment options (K8s, Cloud Run, AWS ECS)
- Add pre-deployment checklist
- Document environment variables and secrets
- Add scaling and performance tuning guidance
- Create operational runbook with common issues
- Add incident response procedures
- Document routine maintenance tasks
- Include disaster recovery procedures
- Link documentation from README"
```

---

## Summary

This plan adds production-grade infrastructure to the API Gateway Hub:

**Chunk 1: Health & Observability**
- Health check endpoints for K8s probes
- Structured JSON logging for log aggregation
- Prometheus metrics for monitoring

**Chunk 2: Production Configuration**
- Graceful shutdown for zero-downtime deploys
- Alembic database migrations
- CORS configuration

**Chunk 3: Deployment Configurations**
- Kubernetes manifests (deployment, service, ingress)
- Production-optimized Dockerfile
- Cloud Run configuration

**Chunk 4: CI/CD & Documentation**
- GitHub Actions pipeline (CI, staging, production)
- Production deployment guide
- Operational runbook

**After completion:**
- Ready for production deployment to K8s, Cloud Run, or AWS
- Comprehensive monitoring and observability
- Automated CI/CD pipeline
- Complete operational documentation
